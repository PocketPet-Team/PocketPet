#ifndef POCKETPET_PET_SERVICE_H
#define POCKETPET_PET_SERVICE_H

#include <stdbool.h>
#include <stdint.h>

#include <zephyr/bluetooth/uuid.h>

/*
 * Provisional 128-bit UUIDs for the PocketPet GATT service. They share one
 * random base and differ in the first 32 bits.
 */
#define PET_UUID_ENCODE(id) \
    BT_UUID_128_ENCODE(0xd0f80000U | (id), 0xb8bf, 0x4fa6, 0xa92b, 0xfad4ab69a07dULL)
#define PET_SERVICE_UUID_VAL PET_UUID_ENCODE(0x0001)
#define PET_STATE_UUID_VAL PET_UUID_ENCODE(0x0002)
#define PET_FIND_UUID_VAL PET_UUID_ENCODE(0x0003)

/* Version byte at the start of the state characteristic value. */
#define PET_STATE_FORMAT_VERSION 1

struct pet_service_callbacks {
    /* A peer wrote the Find characteristic. Runs in the Bluetooth RX thread. */
    void (*find_requested)(void);
    /* A peer enabled or disabled state notifications. Runs in the Bluetooth RX thread. */
    void (*notifications_changed)(bool enabled);
    /*
     * A state notification has been transmitted. Not called for one the stack
     * drops, for example on disconnection. May run in a Bluetooth thread.
     */
    void (*state_sent)(void);
};

void pet_service_init(const struct pet_service_callbacks *callbacks);

/* Store the mood a peer reads from the state characteristic. */
void pet_service_set_mood(uint8_t mood);

/* Notify subscribed peers of the stored mood; returns 0 or a negative errno. */
int pet_service_notify_state(void);

#endif
