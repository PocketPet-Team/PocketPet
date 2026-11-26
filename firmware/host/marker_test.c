#include "marker.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(condition)                                                    \
    do {                                                                    \
        if (!(condition)) {                                                 \
            fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #condition); \
            exit(EXIT_FAILURE);                                             \
        }                                                                   \
    } while (0)

static void test_a_link_overrides_the_advertising_phase(void)
{
    CHECK(marker_state_for(true, ADV_PHASE_STOPPED) == MARKER_STATE_CONNECTED);
    CHECK(marker_state_for(true, ADV_PHASE_FAST) == MARKER_STATE_CONNECTED);
    CHECK(marker_state_for(true, ADV_PHASE_SLOW) == MARKER_STATE_CONNECTED);
}

static void test_without_a_link_the_state_follows_the_advertising_phase(void)
{
    CHECK(marker_state_for(false, ADV_PHASE_STOPPED) == MARKER_STATE_IDLE);
    CHECK(marker_state_for(false, ADV_PHASE_FAST) == MARKER_STATE_ADV_FAST);
    CHECK(marker_state_for(false, ADV_PHASE_SLOW) == MARKER_STATE_ADV_SLOW);
}

/* Decode the lines the way the analysis does: state code first, then one line per event. */
static void test_levels_decode_back_to_the_state_and_events(void)
{
    const unsigned int state_mask = (1U << MARKER_STATE_CHANNELS) - 1U;

    for (int state = 0; state < MARKER_STATE_COUNT; state++) {
        for (unsigned int events = 0; events < (1U << MARKER_EVENT_COUNT); events++) {
            const uint8_t levels = marker_levels((enum marker_state)state, (uint8_t)events);

            CHECK((levels & state_mask) == (unsigned int)state);
            for (int event = 0; event < MARKER_EVENT_COUNT; event++) {
                const unsigned int channel = marker_event_channel((enum marker_event)event);
                CHECK(((levels >> channel) & 1U) == ((events >> event) & 1U));
            }
            CHECK((levels >> MARKER_CHANNEL_COUNT) == 0);
        }
    }
}

static void test_idle_with_no_event_drives_every_line_low(void)
{
    // Lines are low before the firmware configures them, so boot must read as idle.
    CHECK(marker_levels(MARKER_STATE_IDLE, 0) == 0);
}

static void test_undefined_event_bits_are_ignored(void)
{
    CHECK(marker_levels(MARKER_STATE_CONNECTED, 0xff) ==
          marker_levels(MARKER_STATE_CONNECTED, (1U << MARKER_EVENT_COUNT) - 1U));
}

static void test_event_channels_sit_above_the_state_lines_without_overlap(void)
{
    for (int event = 0; event < MARKER_EVENT_COUNT; event++) {
        const unsigned int channel = marker_event_channel((enum marker_event)event);

        CHECK(channel >= MARKER_STATE_CHANNELS && channel < MARKER_CHANNEL_COUNT);
        for (int other = 0; other < event; other++) {
            CHECK(channel != marker_event_channel((enum marker_event)other));
        }
    }
}

static void test_names_are_defined_and_distinct(void)
{
    for (int state = 0; state < MARKER_STATE_COUNT; state++) {
        const char *name = marker_state_name((enum marker_state)state);

        CHECK(name != NULL);
        for (int other = 0; other < state; other++) {
            CHECK(strcmp(name, marker_state_name((enum marker_state)other)) != 0);
        }
    }
    for (int event = 0; event < MARKER_EVENT_COUNT; event++) {
        const char *name = marker_event_name((enum marker_event)event);

        CHECK(name != NULL);
        for (int other = 0; other < event; other++) {
            CHECK(strcmp(name, marker_event_name((enum marker_event)other)) != 0);
        }
    }
    CHECK(marker_state_name(MARKER_STATE_COUNT) == NULL);
    CHECK(marker_event_name(MARKER_EVENT_COUNT) == NULL);
}

int main(void)
{
    test_a_link_overrides_the_advertising_phase();
    test_without_a_link_the_state_follows_the_advertising_phase();
    test_levels_decode_back_to_the_state_and_events();
    test_idle_with_no_event_drives_every_line_low();
    test_undefined_event_bits_are_ignored();
    test_event_channels_sit_above_the_state_lines_without_overlap();
    test_names_are_defined_and_distinct();
    puts("marker tests passed");
    return EXIT_SUCCESS;
}
