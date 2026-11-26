/*
 * Replays separations through the advertising policy and counts the advertising
 * events each policy schedules while the phone is away.
 *
 * Counts are nominal: the controller adds a random 0 to 10 ms delay to every
 * event, so a real separation holds slightly fewer events than printed here.
 */

#include "adv_policy.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

enum {
    MICROSECONDS_PER_UNIT = 625,
    MAX_ADV_DELAY_US = 10000,
};

struct separation_result {
    uint64_t fast_events;
    uint64_t slow_events;
    enum adv_phase phase_at_return;
    uint16_t interval_at_return;
};

/* Events at start, start + interval, ... that fall before end. */
static uint64_t events_between(uint64_t start_us, uint64_t end_us, uint16_t interval_units)
{
    const uint64_t interval_us = (uint64_t)interval_units * MICROSECONDS_PER_UNIT;
    return end_us <= start_us ? 0 : (end_us - start_us + interval_us - 1) / interval_us;
}

static bool replay_separation(const struct adv_policy_config *config, uint64_t separation_ms,
                              struct separation_result *result)
{
    struct adv_policy policy;
    struct adv_action action;
    if (!adv_policy_init(&policy, config, 0) ||
        !adv_policy_step(&policy, ADV_EVENT_LINK_LOST, 0, &action)) {
        return false;
    }

    *result = (struct separation_result){.interval_at_return = action.interval_units};
    uint64_t fast_end_ms = separation_ms;
    if (action.arm_switch_timer && action.switch_deadline_ms < separation_ms) {
        fast_end_ms = action.switch_deadline_ms;
        if (!adv_policy_step(&policy, ADV_EVENT_SWITCH_TIMER, fast_end_ms, &action)) {
            return false;
        }
        // Advertising restarts at the switch, so the slow schedule begins there.
        result->slow_events =
            events_between(fast_end_ms * 1000, separation_ms * 1000, action.interval_units);
        result->interval_at_return = action.interval_units;
    }
    result->fast_events = events_between(0, fast_end_ms * 1000, config->fast_interval_units);
    result->phase_at_return = policy.phase;
    return adv_policy_step(&policy, ADV_EVENT_LINK_CONNECTED, separation_ms, &action);
}

static void print_row(const char *label, const struct adv_policy_config *config,
                      uint64_t separation_ms)
{
    struct separation_result result;
    if (!replay_separation(config, separation_ms, &result)) {
        fprintf(stderr, "Invalid advertising policy\n");
        exit(EXIT_FAILURE);
    }

    const uint64_t worst_wait_us =
        (uint64_t)result.interval_at_return * MICROSECONDS_PER_UNIT + MAX_ADV_DELAY_US;
    printf("%6" PRIu64 " s  %-14s  fast=%7" PRIu64 "  slow=%7" PRIu64 "  total=%7" PRIu64
           "  at return: %-4s  next event within %8.3f ms\n",
           separation_ms / 1000, label, result.fast_events, result.slow_events,
           result.fast_events + result.slow_events,
           result.phase_at_return == ADV_PHASE_SLOW ? "slow" : "fast",
           (double)worst_wait_us / 1000.0);
}

/* Accept only intervals a controller can represent exactly. */
static bool parse_interval(const char *text, uint16_t *units)
{
    char *end;
    const double scaled = strtod(text, &end) / 0.625;
    if (*end != '\0' || !(scaled >= ADV_INTERVAL_UNITS_MIN && scaled <= ADV_INTERVAL_UNITS_MAX)) {
        return false;
    }
    *units = (uint16_t)(scaled + 0.5);
    const double error = scaled - *units;
    return error < 1e-9 && error > -1e-9;
}

static bool parse_seconds(const char *text, uint64_t limit_s, uint64_t *milliseconds)
{
    char *end;
    const unsigned long long seconds = strtoull(text, &end, 10);
    if (*text == '-' || end == text || *end != '\0' || seconds == 0 || seconds > limit_s) {
        return false;
    }
    *milliseconds = (uint64_t)seconds * 1000;
    return true;
}

static int run(int argc, const char *const *argv)
{
    struct adv_policy_config switching;
    uint64_t fast_duration_ms = 0;
    if (argc < 5 || !parse_interval(argv[1], &switching.fast_interval_units) ||
        !parse_interval(argv[2], &switching.slow_interval_units) ||
        !parse_seconds(argv[3], UINT32_MAX / 1000, &fast_duration_ms)) {
        fprintf(stderr,
                "Usage: adv_replay [FAST_MS SLOW_MS FAST_DURATION_S SEPARATION_S...]\n"
                "Intervals are multiples of 0.625 ms from 20 to 10240.\n");
        return EXIT_FAILURE;
    }
    switching.fast_duration_ms = (uint32_t)fast_duration_ms;
    const struct adv_policy_config fixed = {
        .fast_interval_units = switching.fast_interval_units,
        .slow_interval_units = switching.fast_interval_units,
    };

    for (int i = 4; i < argc; ++i) {
        uint64_t separation_ms;
        // The limit keeps the microsecond arithmetic far from overflow.
        if (!parse_seconds(argv[i], UINT32_MAX, &separation_ms)) {
            fprintf(stderr, "Invalid separation: %s\n", argv[i]);
            return EXIT_FAILURE;
        }
        print_row("fixed", &fixed, separation_ms);
        print_row("fast-then-slow", &switching, separation_ms);
    }
    return EXIT_SUCCESS;
}

int main(int argc, char **argv)
{
    // Example values for the built-in replay. They are not frozen pilot parameters.
    static const char *const example[] = {"adv_replay", "100", "1000", "30", "10", "60", "600"};
    if (argc == 1) {
        return run((int)(sizeof(example) / sizeof(example[0])), example);
    }
    return run(argc, (const char *const *)argv);
}
