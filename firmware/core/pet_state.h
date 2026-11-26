#ifndef POCKETPET_PET_STATE_H
#define POCKETPET_PET_STATE_H

#include <stdbool.h>
#include <stdint.h>

enum pet_event {
    PET_EVENT_BUTTON,
    PET_EVENT_LINK_CONNECTED,
    PET_EVENT_LINK_DISCONNECTED,
    PET_EVENT_FIND,
    PET_EVENT_ROUTINE_SYNC_DUE,
    PET_EVENT_FLUSH_ROUTINE_SYNC,
};

enum pet_action {
    PET_ACTION_NONE,
    PET_ACTION_REFRESH_DISPLAY,
    PET_ACTION_START_HAPTIC,
    PET_ACTION_SEND_STATE,
};

struct pet_state {
    uint64_t last_event_ms;
    uint64_t last_decay_ms;
    uint8_t mood;
    bool connected;
    bool routine_sync_pending;
};

void pet_init(struct pet_state *state, uint64_t now_ms);

/*
 * Apply an event using the caller's monotonic clock. Equal timestamps are
 * processed in call order. An unknown event or a backward timestamp returns
 * false and leaves state and action unchanged.
 */
bool pet_step(struct pet_state *state, enum pet_event event, uint64_t now_ms,
              enum pet_action *action);

#endif
