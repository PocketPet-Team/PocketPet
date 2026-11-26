#include "markers.h"

#include <errno.h>

#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/util.h>

#define DT_DRV_COMPAT pocketpet_ppk2_markers

#define MARKER_LINE(node, property, index) GPIO_DT_SPEC_GET_BY_IDX(node, property, index),

static const struct gpio_dt_spec lines[] = {
    DT_FOREACH_PROP_ELEM(DT_DRV_INST(0), gpios, MARKER_LINE)
};

BUILD_ASSERT(ARRAY_SIZE(lines) == MARKER_CHANNEL_COUNT,
             "ppk2-markers must list one GPIO per line in marker.h");

/* Guards the fields below and keeps a level change from being interrupted. */
static struct k_spinlock lock;
static enum marker_state current_state = MARKER_STATE_IDLE;
static uint8_t active_events;
static uint8_t driven_levels;

/* Call with the lock held. Writes only the lines whose level changes. */
static void drive_lines(void)
{
    const uint8_t levels = marker_levels(current_state, active_events);
    const uint8_t changed = levels ^ driven_levels;

    for (size_t line = 0; line < ARRAY_SIZE(lines); line++) {
        if (changed & BIT(line)) {
            (void)gpio_pin_set_dt(&lines[line], (levels >> line) & 1U);
        }
    }
    driven_levels = levels;
}

int markers_init(void)
{
    for (size_t line = 0; line < ARRAY_SIZE(lines); line++) {
        if (!gpio_is_ready_dt(&lines[line])) {
            return -ENODEV;
        }
        const int err = gpio_pin_configure_dt(&lines[line], GPIO_OUTPUT_INACTIVE);
        if (err != 0) {
            return err;
        }
    }
    return 0;
}

void markers_set_state(enum marker_state state)
{
    const k_spinlock_key_t key = k_spin_lock(&lock);

    current_state = state;
    drive_lines();
    k_spin_unlock(&lock, key);
}

void markers_set_event(enum marker_event event, bool active)
{
    const k_spinlock_key_t key = k_spin_lock(&lock);

    WRITE_BIT(active_events, event, active);
    drive_lines();
    k_spin_unlock(&lock, key);
}
