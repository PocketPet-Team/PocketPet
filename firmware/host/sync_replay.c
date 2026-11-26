/*
 * Replays a day of routine updates through the sync policy and counts the
 * transfers it makes with and without a hold.
 *
 * The link stays up for the whole replay. The counts are transfers, not
 * charge: what a transfer costs, and what sharing one with a Find exchange
 * saves, must be measured on the device.
 */

#include "sync_policy.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

struct replay_result {
    uint64_t updates;
    uint64_t transfers;
    uint64_t shared_with_find;
    uint64_t longest_wait_ms;
    uint32_t left_pending;
};

static bool replay(uint32_t max_hold_ms, uint64_t update_period_ms, uint64_t find_period_ms,
                   uint64_t duration_ms, struct replay_result *result)
{
    const struct sync_policy_config config = {.max_hold_ms = max_hold_ms};
    struct sync_policy policy;
    struct sync_action action;
    sync_policy_init(&policy, &config, 0);
    if (!sync_policy_step(&policy, SYNC_EVENT_LINK_READY, 0, &action)) {
        return false;
    }

    *result = (struct replay_result){0};
    // UINT64_MAX marks a source with nothing scheduled.
    uint64_t update_ms = update_period_ms;
    uint64_t find_ms = find_period_ms == 0 ? UINT64_MAX : find_period_ms;
    uint64_t timer_ms = UINT64_MAX;
    uint64_t oldest_pending_ms = 0;
    for (;;) {
        // At equal times an update comes first, so it can join a transfer due
        // then, and a Find comes before the timer, so the transfer is shared.
        enum sync_event event = SYNC_EVENT_UPDATE;
        uint64_t event_ms = update_ms;
        if (find_ms < event_ms) {
            event = SYNC_EVENT_RADIO_ACTIVE;
            event_ms = find_ms;
        }
        if (timer_ms < event_ms) {
            event = SYNC_EVENT_HOLD_TIMER;
            event_ms = timer_ms;
        }
        if (event_ms > duration_ms) {
            break;
        }

        const bool had_pending = policy.pending_updates > 0;
        if (!sync_policy_step(&policy, event, event_ms, &action)) {
            return false;
        }
        if (event == SYNC_EVENT_UPDATE) {
            update_ms += update_period_ms;
            result->updates++;
            if (!had_pending) {
                oldest_pending_ms = event_ms;
            }
        } else if (event == SYNC_EVENT_RADIO_ACTIVE) {
            find_ms += find_period_ms;
        }
        if (event == SYNC_EVENT_HOLD_TIMER || action.cancel_hold_timer) {
            timer_ms = UINT64_MAX;
        }
        if (action.arm_hold_timer) {
            timer_ms = action.hold_deadline_ms;
        }
        if (action.flush) {
            const uint64_t wait_ms = event_ms - oldest_pending_ms;
            result->transfers++;
            result->shared_with_find += event == SYNC_EVENT_RADIO_ACTIVE;
            if (wait_ms > result->longest_wait_ms) {
                result->longest_wait_ms = wait_ms;
            }
        }
    }
    result->left_pending = policy.pending_updates;
    return true;
}

static void print_row(const char *label, const struct replay_result *result)
{
    const double per_transfer = result->transfers == 0
                                    ? 0.0
                                    : (double)(result->updates - result->left_pending) /
                                          (double)result->transfers;
    printf("%-12s  updates=%6" PRIu64 "  transfers=%6" PRIu64 "  alone=%6" PRIu64
           "  with Find=%6" PRIu64 "  updates/transfer=%6.2f  longest wait=%6" PRIu64
           " s  left pending=%" PRIu32 "\n",
           label, result->updates, result->transfers,
           result->transfers - result->shared_with_find, result->shared_with_find, per_transfer,
           result->longest_wait_ms / 1000, result->left_pending);
}

static bool parse_seconds(const char *text, bool allow_zero, uint64_t limit_s,
                          uint64_t *milliseconds)
{
    char *end;
    const unsigned long long seconds = strtoull(text, &end, 10);
    if (*text == '-' || end == text || *end != '\0' || (seconds == 0 && !allow_zero) ||
        seconds > limit_s) {
        return false;
    }
    *milliseconds = (uint64_t)seconds * 1000;
    return true;
}

static int run(int argc, const char *const *argv)
{
    enum { MAX_DURATION_S = 366 * 24 * 3600 };
    uint64_t update_period_ms = 0;
    uint64_t max_hold_ms = 0;
    uint64_t duration_ms = 0;
    uint64_t find_period_ms = 0;
    if (argc < 4 || argc > 5 || !parse_seconds(argv[1], false, MAX_DURATION_S, &update_period_ms) ||
        !parse_seconds(argv[2], false, UINT32_MAX / 1000, &max_hold_ms) ||
        !parse_seconds(argv[3], false, MAX_DURATION_S, &duration_ms) ||
        (argc == 5 && !parse_seconds(argv[4], true, MAX_DURATION_S, &find_period_ms))) {
        fprintf(stderr,
                "Usage: sync_replay [UPDATE_PERIOD_S MAX_HOLD_S DURATION_S [FIND_PERIOD_S]]\n"
                "A Find period of 0, or none, replays no Find requests.\n");
        return EXIT_FAILURE;
    }

    struct replay_result at_once;
    struct replay_result held;
    if (!replay(0, update_period_ms, find_period_ms, duration_ms, &at_once) ||
        !replay((uint32_t)max_hold_ms, update_period_ms, find_period_ms, duration_ms, &held)) {
        fprintf(stderr, "Replay failed\n");
        return EXIT_FAILURE;
    }

    char label[32];
    snprintf(label, sizeof(label), "hold %" PRIu64 " s", max_hold_ms / 1000);
    print_row("at once", &at_once);
    print_row(label, &held);
    return EXIT_SUCCESS;
}

int main(int argc, char **argv)
{
    // Example values for the built-in replay. They are not frozen pilot parameters.
    static const char *const example[] = {"sync_replay", "300", "900", "86400", "2000"};
    if (argc == 1) {
        return run((int)(sizeof(example) / sizeof(example[0])), example);
    }
    return run(argc, (const char *const *)argv);
}
