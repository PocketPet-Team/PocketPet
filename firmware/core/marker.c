#include "marker.h"

#include <stddef.h>

enum {
    STATE_MASK = (1 << MARKER_STATE_CHANNELS) - 1,
    EVENT_MASK = (1 << MARKER_EVENT_COUNT) - 1,
};

/* Every state code must fit on the state lines. */
_Static_assert(MARKER_STATE_COUNT <= (1 << MARKER_STATE_CHANNELS), "too many marker states");
_Static_assert(MARKER_CHANNEL_COUNT <= 8, "a PPK2 has eight logic channels");

enum marker_state marker_state_for(bool connected, enum adv_phase phase)
{
    if (connected) {
        return MARKER_STATE_CONNECTED;
    }
    switch (phase) {
    case ADV_PHASE_FAST:
        return MARKER_STATE_ADV_FAST;
    case ADV_PHASE_SLOW:
        return MARKER_STATE_ADV_SLOW;
    case ADV_PHASE_STOPPED:
    default:
        return MARKER_STATE_IDLE;
    }
}

unsigned int marker_event_channel(enum marker_event event)
{
    return MARKER_STATE_CHANNELS + (unsigned int)event;
}

uint8_t marker_levels(enum marker_state state, uint8_t active_events)
{
    const unsigned int state_bits = (unsigned int)state & STATE_MASK;
    const unsigned int event_bits = active_events & EVENT_MASK;

    return (uint8_t)(state_bits | (event_bits << MARKER_STATE_CHANNELS));
}

const char *marker_state_name(enum marker_state state)
{
    switch (state) {
    case MARKER_STATE_IDLE:
        return "idle";
    case MARKER_STATE_ADV_FAST:
        return "adv_fast";
    case MARKER_STATE_ADV_SLOW:
        return "adv_slow";
    case MARKER_STATE_CONNECTED:
        return "connected";
    case MARKER_STATE_COUNT:
    default:
        return NULL;
    }
}

const char *marker_event_name(enum marker_event event)
{
    switch (event) {
    case MARKER_EVENT_BUTTON:
        return "button";
    case MARKER_EVENT_HAPTIC:
        return "haptic";
    case MARKER_EVENT_TRANSFER:
        return "transfer";
    case MARKER_EVENT_COUNT:
    default:
        return NULL;
    }
}
