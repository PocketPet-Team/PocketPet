#include "pet_state.h"

enum {
    MAX_MOOD = 100,
    MOOD_DECAY_PERIOD_MS = 5 * 60 * 1000,
    BUTTON_MOOD_GAIN = 4,
};

void pet_init(struct pet_state *state, uint64_t now_ms)
{
    *state = (struct pet_state){
        .last_event_ms = now_ms,
        .last_decay_ms = now_ms,
        .mood = MAX_MOOD,
    };
}

bool pet_step(struct pet_state *state, enum pet_event event, uint64_t now_ms,
              enum pet_action *action)
{
    if (now_ms < state->last_event_ms) {
        return false;
    }

    enum pet_action next_action = PET_ACTION_NONE;
    unsigned int mood_gain = 0;
    switch (event) {
    case PET_EVENT_BUTTON:
        next_action = PET_ACTION_REFRESH_DISPLAY;
        mood_gain = BUTTON_MOOD_GAIN;
        break;
    case PET_EVENT_LINK_CONNECTED:
        state->connected = true;
        break;
    case PET_EVENT_LINK_DISCONNECTED:
        state->connected = false;
        break;
    case PET_EVENT_FIND:
        if (state->connected) {
            next_action = PET_ACTION_START_HAPTIC;
        }
        break;
    case PET_EVENT_ROUTINE_SYNC_DUE:
        state->routine_sync_pending = true;
        break;
    case PET_EVENT_FLUSH_ROUTINE_SYNC:
        if (state->connected && state->routine_sync_pending) {
            state->routine_sync_pending = false;
            next_action = PET_ACTION_SEND_STATE;
        }
        break;
    default:
        return false;
    }

    const uint64_t elapsed_periods =
        (now_ms - state->last_decay_ms) / MOOD_DECAY_PERIOD_MS;
    // Keep the partial period so frequent events cannot delay decay.
    state->last_decay_ms += elapsed_periods * MOOD_DECAY_PERIOD_MS;
    const unsigned int decayed_mood =
        elapsed_periods >= state->mood ? 0 : state->mood - (unsigned int)elapsed_periods;
    const unsigned int new_mood = decayed_mood + mood_gain;
    state->mood = (uint8_t)(new_mood > MAX_MOOD ? MAX_MOOD : new_mood);
    state->last_event_ms = now_ms;
    *action = next_action;
    return true;
}
