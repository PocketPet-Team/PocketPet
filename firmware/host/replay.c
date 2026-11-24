#include "pet_state.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

int main(void)
{
    static const struct {
        uint64_t time_ms;
        enum pet_event event;
        const char *label;
    } trace[] = {
        {0, PET_EVENT_LINK_CONNECTED, "connected"},
        {1800000, PET_EVENT_BUTTON, "button"},
        {1800000, PET_EVENT_ROUTINE_SYNC_DUE, "sync due"},
        {1800000, PET_EVENT_FIND, "find"},
        {1800000, PET_EVENT_FLUSH_ROUTINE_SYNC, "flush sync"},
    };
    static const char *const action_labels[] = {
        [PET_ACTION_NONE] = "none",
        [PET_ACTION_REFRESH_DISPLAY] = "refresh display",
        [PET_ACTION_START_HAPTIC] = "start haptic",
        [PET_ACTION_SEND_STATE] = "send state",
    };
    struct pet_state state;
    pet_init(&state, 0);

    for (size_t i = 0; i < sizeof(trace) / sizeof(trace[0]); ++i) {
        enum pet_action action;
        if (!pet_step(&state, trace[i].event, trace[i].time_ms, &action)) {
            fprintf(stderr, "Invalid replay event at index %zu\n", i);
            return EXIT_FAILURE;
        }

        printf("%7" PRIu64 " ms  %-10s  mood=%3u  action=%s\n",
               trace[i].time_ms, trace[i].label, (unsigned int)state.mood,
               action_labels[action]);
    }

    return EXIT_SUCCESS;
}
