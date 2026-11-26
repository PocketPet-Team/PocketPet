/*
 * Print the firmware's marker layout as the "markers" object of a run
 * manifest, assuming marker line n is wired to PPK2 logic channel Dn.
 */

#include "marker.h"

#include <stdio.h>
#include <stdlib.h>

int main(void)
{
    printf("{\n  \"state_channels\": [");
    for (int channel = 0; channel < MARKER_STATE_CHANNELS; channel++) {
        printf("%s%d", channel == 0 ? "" : ", ", channel);
    }
    printf("],\n  \"states\": {\n");
    for (int state = 0; state < MARKER_STATE_COUNT; state++) {
        printf("    \"%d\": \"%s\"%s\n", state, marker_state_name((enum marker_state)state),
               state + 1 < MARKER_STATE_COUNT ? "," : "");
    }
    printf("  },\n  \"events\": {\n");
    for (int event = 0; event < MARKER_EVENT_COUNT; event++) {
        printf("    \"%u\": \"%s\"%s\n", marker_event_channel((enum marker_event)event),
               marker_event_name((enum marker_event)event),
               event + 1 < MARKER_EVENT_COUNT ? "," : "");
    }
    printf("  }\n}\n");
    return EXIT_SUCCESS;
}
