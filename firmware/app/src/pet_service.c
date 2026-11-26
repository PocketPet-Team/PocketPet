#include "pet_service.h"

#include <errno.h>

#include <zephyr/bluetooth/att.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/sys/atomic.h>

#define FIND_REQUEST 0x01

static const struct bt_uuid_128 service_uuid = BT_UUID_INIT_128(PET_SERVICE_UUID_VAL);
static const struct bt_uuid_128 state_uuid = BT_UUID_INIT_128(PET_STATE_UUID_VAL);
static const struct bt_uuid_128 find_uuid = BT_UUID_INIT_128(PET_FIND_UUID_VAL);

static const struct pet_service_callbacks *service_callbacks;
/* Written by the application work item, read by the Bluetooth RX thread. */
static atomic_t stored_mood;

static void encode_state(uint8_t value[2])
{
    value[0] = PET_STATE_FORMAT_VERSION;
    value[1] = (uint8_t)atomic_get(&stored_mood);
}

static ssize_t read_state(struct bt_conn *conn, const struct bt_gatt_attr *attr, void *buf,
                          uint16_t len, uint16_t offset)
{
    uint8_t value[2];

    encode_state(value);
    return bt_gatt_attr_read(conn, attr, buf, len, offset, value, sizeof(value));
}

static ssize_t write_find(struct bt_conn *conn, const struct bt_gatt_attr *attr, const void *buf,
                          uint16_t len, uint16_t offset, uint8_t flags)
{
    ARG_UNUSED(conn);
    ARG_UNUSED(attr);
    ARG_UNUSED(flags);

    if (offset != 0) {
        return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
    }
    if (len != 1) {
        return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
    }
    if (((const uint8_t *)buf)[0] != FIND_REQUEST) {
        return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
    }

    if (service_callbacks != NULL && service_callbacks->find_requested != NULL) {
        service_callbacks->find_requested();
    }
    return len;
}

static void state_ccc_changed(const struct bt_gatt_attr *attr, uint16_t value)
{
    ARG_UNUSED(attr);

    if (service_callbacks != NULL && service_callbacks->notifications_changed != NULL) {
        service_callbacks->notifications_changed(value == BT_GATT_CCC_NOTIFY);
    }
}

/*
 * No characteristic requires pairing yet, so any nearby central can read the
 * mood and trigger Find. Add security before the tag leaves the bench.
 */
BT_GATT_SERVICE_DEFINE(pet_service,
    BT_GATT_PRIMARY_SERVICE(&service_uuid),
    BT_GATT_CHARACTERISTIC(&state_uuid.uuid, BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
                           BT_GATT_PERM_READ, read_state, NULL, NULL),
    BT_GATT_CCC(state_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
    BT_GATT_CHARACTERISTIC(&find_uuid.uuid,
                           BT_GATT_CHRC_WRITE | BT_GATT_CHRC_WRITE_WITHOUT_RESP,
                           BT_GATT_PERM_WRITE, NULL, write_find, NULL),
);

/* Index of the state value attribute in pet_service.attrs. */
#define STATE_VALUE_ATTR 2

void pet_service_init(const struct pet_service_callbacks *callbacks)
{
    service_callbacks = callbacks;
}

void pet_service_set_mood(uint8_t mood)
{
    atomic_set(&stored_mood, mood);
}

static void state_notification_sent(struct bt_conn *conn, void *user_data)
{
    ARG_UNUSED(conn);
    ARG_UNUSED(user_data);

    if (service_callbacks != NULL && service_callbacks->state_sent != NULL) {
        service_callbacks->state_sent();
    }
}

int pet_service_notify_state(void)
{
    uint8_t value[2];
    struct bt_gatt_notify_params params = {
        .attr = &pet_service.attrs[STATE_VALUE_ATTR],
        .data = value,
        .len = sizeof(value),
        .func = state_notification_sent,
    };

    encode_state(value);
    return bt_gatt_notify_cb(NULL, &params);
}
