#ifndef POCKETPET_MARKER_H
#define POCKETPET_MARKER_H

#include <stdbool.h>
#include <stdint.h>

#include "adv_policy.h"

/*
 * Layout of the logic lines that label a power capture.
 *
 * The lowest MARKER_STATE_CHANNELS lines carry the operating state as a binary
 * code, least significant line first. Each line above them is high while one
 * event is in progress. The analysis attributes every sample to the state on
 * the state lines and charges an event only for what it draws above that
 * state's background, so the firmware must keep exactly one state selected.
 *
 * The values below are part of the capture format: changing one changes what
 * existing captures mean. marker_map prints them as a run-manifest fragment.
 */
enum marker_state {
    /* No link and not advertising: boot, or the gap before advertising restarts. */
    MARKER_STATE_IDLE,
    MARKER_STATE_ADV_FAST,
    MARKER_STATE_ADV_SLOW,
    MARKER_STATE_CONNECTED,
    MARKER_STATE_COUNT,
};

enum marker_event {
    /* From an accepted button press to the end of its display refresh. */
    MARKER_EVENT_BUTTON,
    /* While the Find indication is on. */
    MARKER_EVENT_HAPTIC,
    /* From handing a state update to the stack until it has been transmitted. */
    MARKER_EVENT_TRANSFER,
    MARKER_EVENT_COUNT,
};

enum {
    MARKER_STATE_CHANNELS = 2,
    MARKER_CHANNEL_COUNT = MARKER_STATE_CHANNELS + MARKER_EVENT_COUNT,
};

/* The operating state for a link status and an advertising phase. A link wins. */
enum marker_state marker_state_for(bool connected, enum adv_phase phase);

/* The logic line that marks an event. */
unsigned int marker_event_channel(enum marker_event event);

/*
 * Line levels for a state and a set of active events. Bit n of the result is
 * the level of line n; bit e of active_events is set while event e is active.
 */
uint8_t marker_levels(enum marker_state state, uint8_t active_events);

/* Names used in run manifests and summaries; NULL for an out-of-range value. */
const char *marker_state_name(enum marker_state state);
const char *marker_event_name(enum marker_event event);

#endif
