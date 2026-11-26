#include "adv_policy.h"

#include <stdio.h>
#include <stdlib.h>

#define CHECK(condition)                                                    \
    do {                                                                    \
        if (!(condition)) {                                                 \
            fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #condition); \
            exit(EXIT_FAILURE);                                             \
        }                                                                   \
    } while (0)

enum {
    FAST_UNITS = 160,
    SLOW_UNITS = 1600,
    FAST_DURATION_MS = 30000,
};

static const struct adv_policy_config fast_then_slow = {
    .fast_interval_units = FAST_UNITS,
    .slow_interval_units = SLOW_UNITS,
    .fast_duration_ms = FAST_DURATION_MS,
};

static const struct adv_policy_config fixed_rate = {
    .fast_interval_units = FAST_UNITS,
    .slow_interval_units = FAST_UNITS,
};

static struct adv_action step(struct adv_policy *policy, enum adv_event event, uint64_t now_ms)
{
    struct adv_action action;
    CHECK(adv_policy_step(policy, event, now_ms, &action));
    return action;
}

static bool is_no_action(struct adv_action action)
{
    return !action.start && !action.arm_switch_timer && !action.cancel_switch_timer;
}

static void test_fast_then_slow_switches_at_the_deadline(void)
{
    struct adv_policy policy;
    CHECK(adv_policy_init(&policy, &fast_then_slow, 1000));

    struct adv_action action = step(&policy, ADV_EVENT_LINK_LOST, 5000);
    CHECK(action.start && action.interval_units == FAST_UNITS);
    CHECK(action.arm_switch_timer && action.switch_deadline_ms == 5000 + FAST_DURATION_MS);
    CHECK(policy.phase == ADV_PHASE_FAST);

    action = step(&policy, ADV_EVENT_SWITCH_TIMER, 5000 + FAST_DURATION_MS);
    CHECK(action.start && action.interval_units == SLOW_UNITS);
    CHECK(!action.arm_switch_timer && !action.cancel_switch_timer);
    CHECK(policy.phase == ADV_PHASE_SLOW);

    // Nothing is left to cancel once the switch has happened.
    CHECK(is_no_action(step(&policy, ADV_EVENT_LINK_CONNECTED, 90000)));
    CHECK(policy.phase == ADV_PHASE_STOPPED);
}

static void test_return_before_the_switch_cancels_the_timer(void)
{
    struct adv_policy policy;
    CHECK(adv_policy_init(&policy, &fast_then_slow, 0));
    step(&policy, ADV_EVENT_LINK_LOST, 0);

    const struct adv_action action = step(&policy, ADV_EVENT_LINK_CONNECTED, 10000);
    CHECK(action.cancel_switch_timer && !action.start);
    CHECK(policy.phase == ADV_PHASE_STOPPED);
}

static void test_fixed_rate_never_switches(void)
{
    struct adv_policy policy;
    CHECK(adv_policy_init(&policy, &fixed_rate, 0));

    const struct adv_action action = step(&policy, ADV_EVENT_LINK_LOST, 0);
    CHECK(action.start && action.interval_units == FAST_UNITS);
    CHECK(!action.arm_switch_timer);

    CHECK(is_no_action(step(&policy, ADV_EVENT_SWITCH_TIMER, UINT64_MAX - 1)));
    CHECK(policy.phase == ADV_PHASE_FAST);
    CHECK(is_no_action(step(&policy, ADV_EVENT_LINK_CONNECTED, UINT64_MAX)));
}

static void test_both_policies_start_at_the_same_rate(void)
{
    struct adv_policy fixed, switching;
    CHECK(adv_policy_init(&fixed, &fixed_rate, 0));
    CHECK(adv_policy_init(&switching, &fast_then_slow, 0));

    CHECK(step(&fixed, ADV_EVENT_LINK_LOST, 7).interval_units ==
          step(&switching, ADV_EVENT_LINK_LOST, 7).interval_units);
}

static void test_stale_and_early_timers_do_nothing(void)
{
    struct adv_policy policy;
    CHECK(adv_policy_init(&policy, &fast_then_slow, 0));

    // A timer left over from a first separation fires early in the second one.
    step(&policy, ADV_EVENT_LINK_LOST, 0);
    step(&policy, ADV_EVENT_LINK_CONNECTED, 20000);
    CHECK(is_no_action(step(&policy, ADV_EVENT_SWITCH_TIMER, 25000)));
    CHECK(policy.phase == ADV_PHASE_STOPPED);

    step(&policy, ADV_EVENT_LINK_LOST, 28000);
    CHECK(is_no_action(step(&policy, ADV_EVENT_SWITCH_TIMER, FAST_DURATION_MS)));
    CHECK(policy.phase == ADV_PHASE_FAST);
    CHECK(is_no_action(step(&policy, ADV_EVENT_SWITCH_TIMER, 28000 + FAST_DURATION_MS - 1)));
    CHECK(step(&policy, ADV_EVENT_SWITCH_TIMER, 28000 + FAST_DURATION_MS).start);
    CHECK(policy.phase == ADV_PHASE_SLOW);

    CHECK(is_no_action(step(&policy, ADV_EVENT_SWITCH_TIMER, 90000)));
    CHECK(policy.phase == ADV_PHASE_SLOW);
}

static void test_repeated_link_events_do_not_restart_advertising(void)
{
    struct adv_policy policy;
    CHECK(adv_policy_init(&policy, &fast_then_slow, 0));

    CHECK(is_no_action(step(&policy, ADV_EVENT_LINK_CONNECTED, 0)));
    step(&policy, ADV_EVENT_LINK_LOST, 100);
    // A second report must not push the switch deadline back.
    CHECK(is_no_action(step(&policy, ADV_EVENT_LINK_LOST, 20000)));
    CHECK(policy.switch_deadline_ms == 100 + FAST_DURATION_MS);
}

static void test_deadline_saturates_near_the_clock_maximum(void)
{
    struct adv_policy policy;
    CHECK(adv_policy_init(&policy, &fast_then_slow, 0));

    const struct adv_action action = step(&policy, ADV_EVENT_LINK_LOST, UINT64_MAX - 10);
    CHECK(action.arm_switch_timer && action.switch_deadline_ms == UINT64_MAX);
    CHECK(is_no_action(step(&policy, ADV_EVENT_SWITCH_TIMER, UINT64_MAX - 1)));
    CHECK(step(&policy, ADV_EVENT_SWITCH_TIMER, UINT64_MAX).start);
}

static void test_rejects_invalid_config(void)
{
    struct adv_policy policy = {.phase = ADV_PHASE_SLOW, .last_event_ms = 42};
    struct adv_policy_config config = fast_then_slow;

    config.fast_interval_units = ADV_INTERVAL_UNITS_MIN - 1;
    CHECK(!adv_policy_init(&policy, &config, 0));
    config = fast_then_slow;
    config.slow_interval_units = ADV_INTERVAL_UNITS_MAX + 1;
    CHECK(!adv_policy_init(&policy, &config, 0));
    config = fast_then_slow;
    config.slow_interval_units = FAST_UNITS - 1;
    CHECK(!adv_policy_init(&policy, &config, 0));
    config = fast_then_slow;
    config.fast_duration_ms = 0;
    CHECK(!adv_policy_init(&policy, &config, 0));
    CHECK(policy.phase == ADV_PHASE_SLOW && policy.last_event_ms == 42);

    config.fast_interval_units = ADV_INTERVAL_UNITS_MIN;
    config.slow_interval_units = ADV_INTERVAL_UNITS_MAX;
    config.fast_duration_ms = 1;
    CHECK(adv_policy_init(&policy, &config, 0));
}

static void test_rejects_invalid_input(void)
{
    struct adv_policy policy;
    CHECK(adv_policy_init(&policy, &fast_then_slow, 1000));
    struct adv_action action = {.interval_units = 77};

    CHECK(!adv_policy_step(&policy, ADV_EVENT_LINK_LOST, 999, &action));
    CHECK(!adv_policy_step(&policy, (enum adv_event)99, 2000, &action));
    CHECK(action.interval_units == 77);
    CHECK(policy.phase == ADV_PHASE_STOPPED && policy.last_event_ms == 1000);
}

int main(void)
{
    test_fast_then_slow_switches_at_the_deadline();
    test_return_before_the_switch_cancels_the_timer();
    test_fixed_rate_never_switches();
    test_both_policies_start_at_the_same_rate();
    test_stale_and_early_timers_do_nothing();
    test_repeated_link_events_do_not_restart_advertising();
    test_deadline_saturates_near_the_clock_maximum();
    test_rejects_invalid_config();
    test_rejects_invalid_input();
    return EXIT_SUCCESS;
}
