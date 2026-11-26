/*
 * PocketPet tag application for bench bring-up on the nRF52840 DK.
 *
 * Every input (button, Bluetooth callbacks, timers) is queued and applied to
 * the portable state machines from one work item, so pet_step() and
 * adv_policy_step() always see events in order and never run concurrently.
 * The board's LED1 stands in for the display and LED2 for the haptic motor
 * until those drivers exist.
 */

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/atomic.h>

#include <hal/nrf_clock.h>

#include "adv_policy.h"
#include "pet_service.h"
#include "pet_state.h"

LOG_MODULE_REGISTER(pocketpet, LOG_LEVEL_INF);

#define BUTTON_LOCKOUT_MS 50
#define EVENT_QUEUE_LENGTH 16

enum app_event_source {
    SOURCE_PET,
    SOURCE_ADV,
};

struct app_event {
    uint8_t source;
    uint8_t code;
};

/*
 * Initialized in main() instead of with K_MSGQ_DEFINE, which names a linker
 * section after __FILE__ and breaks the build when the path contains a space.
 */
static struct k_msgq event_queue;
static char __aligned(4) event_queue_buffer[EVENT_QUEUE_LENGTH * sizeof(struct app_event)];

static const struct gpio_dt_spec button = GPIO_DT_SPEC_GET(DT_ALIAS(sw0), gpios);
static const struct gpio_dt_spec display_led = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
static const struct gpio_dt_spec haptic_led = GPIO_DT_SPEC_GET(DT_ALIAS(led1), gpios);
static struct gpio_callback button_callback;

static const struct bt_data advertising_data[] = {
    BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
    BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
};
static const struct bt_data scan_response_data[] = {
    BT_DATA_BYTES(BT_DATA_UUID128_ALL, PET_SERVICE_UUID_VAL),
};

/* Owned by the event work item. */
static struct pet_state pet;
static struct adv_policy advertising;

/* Shared with the Bluetooth RX thread. */
static struct bt_conn *current_conn;
static atomic_t notifications_enabled;

static void process_events(struct k_work *work);
static void switch_timer_expired(struct k_work *work);
static void routine_sync_due(struct k_work *work);
static void find_indication_done(struct k_work *work);

static K_WORK_DEFINE(event_work, process_events);
static K_WORK_DELAYABLE_DEFINE(switch_timer, switch_timer_expired);
static K_WORK_DELAYABLE_DEFINE(routine_sync_timer, routine_sync_due);
static K_WORK_DELAYABLE_DEFINE(find_indication_timer, find_indication_done);

/* Safe from interrupts and any thread. */
static void queue_event(enum app_event_source source, uint8_t code)
{
    const struct app_event event = {.source = source, .code = code};

    if (k_msgq_put(&event_queue, &event, K_NO_WAIT) != 0) {
        LOG_ERR("Event queue full, dropped source %u code %u", source, code);
        return;
    }
    k_work_submit(&event_work);
}

static void start_advertising(uint16_t interval_units)
{
    const struct bt_le_adv_param param =
        BT_LE_ADV_PARAM_INIT(BT_LE_ADV_OPT_CONN, interval_units, interval_units, NULL);

    // The new interval only takes effect after a restart.
    (void)bt_le_adv_stop();
    const int err = bt_le_adv_start(&param, advertising_data, ARRAY_SIZE(advertising_data),
                                    scan_response_data, ARRAY_SIZE(scan_response_data));
    if (err != 0) {
        LOG_ERR("Advertising start failed (%d)", err);
        return;
    }
    LOG_INF("Advertising every %u.%03u ms", (interval_units * 625U) / 1000U,
            (interval_units * 625U) % 1000U);
}

static void apply_adv_action(const struct adv_action *action, uint64_t now_ms)
{
    if (action->cancel_switch_timer) {
        (void)k_work_cancel_delayable(&switch_timer);
    }
    if (action->start) {
        start_advertising(action->interval_units);
    }
    if (action->arm_switch_timer) {
        (void)k_work_reschedule(&switch_timer, K_MSEC(action->switch_deadline_ms - now_ms));
    }
}

static void apply_pet_action(enum pet_action action)
{
    switch (action) {
    case PET_ACTION_REFRESH_DISPLAY:
        (void)gpio_pin_toggle_dt(&display_led);
        LOG_INF("Display refresh, mood %u", pet.mood);
        break;
    case PET_ACTION_START_HAPTIC:
        (void)gpio_pin_set_dt(&haptic_led, 1);
        (void)k_work_reschedule(&find_indication_timer,
                                K_MSEC(CONFIG_POCKETPET_FIND_INDICATION_MS));
        LOG_INF("Find indication");
        break;
    case PET_ACTION_SEND_STATE: {
        const int err = pet_service_notify_state();
        if (err != 0) {
            LOG_WRN("State notification failed (%d)", err);
        }
        break;
    }
    case PET_ACTION_NONE:
    default:
        break;
    }
}

static void process_events(struct k_work *work)
{
    ARG_UNUSED(work);
    struct app_event event;

    while (k_msgq_get(&event_queue, &event, K_NO_WAIT) == 0) {
        // Timestamps are taken here, in processing order, so they never go backwards.
        const uint64_t now_ms = (uint64_t)k_uptime_get();

        if (event.source == SOURCE_ADV) {
            struct adv_action action;
            if (adv_policy_step(&advertising, (enum adv_event)event.code, now_ms, &action)) {
                apply_adv_action(&action, now_ms);
            }
            continue;
        }

        // Keep a routine update pending until a peer can receive it.
        if (event.code == PET_EVENT_FLUSH_ROUTINE_SYNC && !atomic_get(&notifications_enabled)) {
            continue;
        }
        enum pet_action action;
        if (pet_step(&pet, (enum pet_event)event.code, now_ms, &action)) {
            pet_service_set_mood(pet.mood);
            apply_pet_action(action);
        }
    }
}

static void switch_timer_expired(struct k_work *work)
{
    ARG_UNUSED(work);
    queue_event(SOURCE_ADV, ADV_EVENT_SWITCH_TIMER);
}

static void routine_sync_due(struct k_work *work)
{
    ARG_UNUSED(work);
    queue_event(SOURCE_PET, PET_EVENT_ROUTINE_SYNC_DUE);
    queue_event(SOURCE_PET, PET_EVENT_FLUSH_ROUTINE_SYNC);
    (void)k_work_schedule(&routine_sync_timer, K_SECONDS(CONFIG_POCKETPET_ROUTINE_SYNC_PERIOD_S));
}

static void find_indication_done(struct k_work *work)
{
    ARG_UNUSED(work);
    (void)gpio_pin_set_dt(&haptic_led, 0);
}

static void button_pressed(const struct device *port, struct gpio_callback *callback,
                           uint32_t pins)
{
    ARG_UNUSED(port);
    ARG_UNUSED(callback);
    ARG_UNUSED(pins);
    static int64_t last_press_ms = -BUTTON_LOCKOUT_MS;

    // The first edge is acted on at once; contact bounce right after it is ignored.
    const int64_t now_ms = k_uptime_get();
    if (now_ms - last_press_ms < BUTTON_LOCKOUT_MS) {
        return;
    }
    last_press_ms = now_ms;
    queue_event(SOURCE_PET, PET_EVENT_BUTTON);
}

static void log_connection_parameters(struct bt_conn *conn, const char *when)
{
    struct bt_conn_info info;

    if (bt_conn_get_info(conn, &info) == 0) {
        LOG_INF("%s: interval %u us, latency %u, timeout %u ms", when, info.le.interval_us,
                info.le.latency, info.le.timeout * 10U);
    }
}

static void connected(struct bt_conn *conn, uint8_t err)
{
    if (err != 0) {
        LOG_WRN("Connection failed (0x%02x)", err);
        return;
    }
    current_conn = bt_conn_ref(conn);
    log_connection_parameters(conn, "Connected");
    queue_event(SOURCE_ADV, ADV_EVENT_LINK_CONNECTED);
    queue_event(SOURCE_PET, PET_EVENT_LINK_CONNECTED);
}

static void disconnected(struct bt_conn *conn, uint8_t reason)
{
    ARG_UNUSED(conn);
    LOG_INF("Disconnected (0x%02x)", reason);
    atomic_set(&notifications_enabled, false);
    if (current_conn != NULL) {
        bt_conn_unref(current_conn);
        current_conn = NULL;
    }
    queue_event(SOURCE_PET, PET_EVENT_LINK_DISCONNECTED);
}

/*
 * Advertising restarts here rather than in disconnected(): until the
 * connection object is released, starting connectable advertising can fail.
 */
static void recycled(void)
{
    queue_event(SOURCE_ADV, ADV_EVENT_LINK_LOST);
}

static void parameters_updated(struct bt_conn *conn, uint16_t interval, uint16_t latency,
                               uint16_t timeout)
{
    ARG_UNUSED(interval);
    ARG_UNUSED(latency);
    ARG_UNUSED(timeout);
    log_connection_parameters(conn, "Parameters updated");
}

BT_CONN_CB_DEFINE(connection_callbacks) = {
    .connected = connected,
    .disconnected = disconnected,
    .recycled = recycled,
    .le_param_updated = parameters_updated,
};

static void find_requested(void)
{
    queue_event(SOURCE_PET, PET_EVENT_FIND);
}

static void notifications_changed(bool enabled)
{
    atomic_set(&notifications_enabled, enabled);
    if (enabled) {
        // Deliver an update that was queued while no peer could receive it.
        queue_event(SOURCE_PET, PET_EVENT_FLUSH_ROUTINE_SYNC);
    }
}

static const struct pet_service_callbacks service_callbacks = {
    .find_requested = find_requested,
    .notifications_changed = notifications_changed,
};

static int init_gpio(void)
{
    if (!gpio_is_ready_dt(&button) || !gpio_is_ready_dt(&display_led) ||
        !gpio_is_ready_dt(&haptic_led)) {
        return -ENODEV;
    }

    int err = gpio_pin_configure_dt(&display_led, GPIO_OUTPUT_INACTIVE);
    err = err ? err : gpio_pin_configure_dt(&haptic_led, GPIO_OUTPUT_INACTIVE);
    err = err ? err : gpio_pin_configure_dt(&button, GPIO_INPUT);
    err = err ? err : gpio_pin_interrupt_configure_dt(&button, GPIO_INT_EDGE_TO_ACTIVE);
    if (err != 0) {
        return err;
    }
    gpio_init_callback(&button_callback, button_pressed, BIT(button.pin));
    return gpio_add_callback_dt(&button, &button_callback);
}

/* Report the LF clock that is running, not only the one configured. */
static void log_lf_clock(void)
{
    nrf_clock_lfclk_t source;
    const char *name = "not running";

    if (nrf_clock_is_running(NRF_CLOCK, NRF_CLOCK_DOMAIN_LFCLK, &source)) {
        switch (source) {
        case NRF_CLOCK_LFCLK_RC:
            name = "RC";
            break;
        case NRF_CLOCK_LFCLK_XTAL:
            name = "crystal";
            break;
        case NRF_CLOCK_LFCLK_SYNTH:
            name = "synthesized";
            break;
        default:
            name = "unknown";
            break;
        }
    }
    LOG_INF("LF clock: %s (configured %s)", name,
            IS_ENABLED(CONFIG_CLOCK_CONTROL_NRF_K32SRC_RC) ? "RC" : "crystal");
}

int main(void)
{
    static const struct adv_policy_config adv_config = {
        .fast_interval_units = CONFIG_POCKETPET_ADV_FAST_INTERVAL,
        .slow_interval_units = CONFIG_POCKETPET_ADV_SLOW_INTERVAL,
        .fast_duration_ms = CONFIG_POCKETPET_ADV_FAST_DURATION_MS,
    };
    const uint64_t now_ms = (uint64_t)k_uptime_get();

    k_msgq_init(&event_queue, event_queue_buffer, sizeof(struct app_event), EVENT_QUEUE_LENGTH);
    pet_init(&pet, now_ms);
    pet_service_set_mood(pet.mood);
    if (!adv_policy_init(&advertising, &adv_config, now_ms)) {
        LOG_ERR("Invalid advertising configuration");
        return 0;
    }

    int err = init_gpio();
    if (err != 0) {
        LOG_ERR("GPIO init failed (%d)", err);
        return 0;
    }

    pet_service_init(&service_callbacks);
    err = bt_enable(NULL);
    if (err != 0) {
        LOG_ERR("Bluetooth init failed (%d)", err);
        return 0;
    }
    log_lf_clock();

    // Boot counts as a lost link, so advertising starts at the fast rate.
    queue_event(SOURCE_ADV, ADV_EVENT_LINK_LOST);
    (void)k_work_schedule(&routine_sync_timer, K_SECONDS(CONFIG_POCKETPET_ROUTINE_SYNC_PERIOD_S));
    return 0;
}
