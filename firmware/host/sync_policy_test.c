#include "sync_policy.h"

#include <stdio.h>
#include <stdlib.h>

#define CHECK(condition)                                                    \
    do {                                                                    \
        if (!(condition)) {                                                 \
            fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #condition); \
            exit(EXIT_FAILURE);                                             \
        }                                                                   \
    } while (0)

enum { HOLD_MS = 900000 };

static const struct sync_policy_config held = {.max_hold_ms = HOLD_MS};
static const struct sync_policy_config at_once = {.max_hold_ms = 0};

static struct sync_action step(struct sync_policy *policy, enum sync_event event, uint64_t now_ms)
{
    struct sync_action action;
    CHECK(sync_policy_step(policy, event, now_ms, &action));
    return action;
}

static bool is_no_action(struct sync_action action)
{
    return !action.flush && !action.arm_hold_timer && !action.cancel_hold_timer;
}

/* A policy at time zero with a peer that can already receive. */
static struct sync_policy ready_policy(const struct sync_policy_config *config)
{
    struct sync_policy policy;
    sync_policy_init(&policy, config, 0);
    CHECK(is_no_action(step(&policy, SYNC_EVENT_LINK_READY, 0)));
    return policy;
}

static void test_zero_hold_sends_every_update_at_once(void)
{
    struct sync_policy policy = ready_policy(&at_once);

    for (uint64_t now_ms = 1000; now_ms <= 3000; now_ms += 1000) {
        const struct sync_action action = step(&policy, SYNC_EVENT_UPDATE, now_ms);
        CHECK(action.flush && action.flushed_updates == 1);
        CHECK(!action.arm_hold_timer && !action.cancel_hold_timer);
    }
}

static void test_updates_inside_the_hold_share_one_transfer(void)
{
    struct sync_policy policy = ready_policy(&held);

    struct sync_action action = step(&policy, SYNC_EVENT_UPDATE, 1000);
    CHECK(!action.flush && action.arm_hold_timer && action.hold_deadline_ms == 1000 + HOLD_MS);

    // Later updates join the wait without moving its deadline.
    CHECK(is_no_action(step(&policy, SYNC_EVENT_UPDATE, 300000)));
    CHECK(is_no_action(step(&policy, SYNC_EVENT_UPDATE, 600000)));

    action = step(&policy, SYNC_EVENT_HOLD_TIMER, 1000 + HOLD_MS);
    CHECK(action.flush && action.flushed_updates == 3);
    CHECK(!action.arm_hold_timer && !action.cancel_hold_timer);

    // The next update starts a new wait from its own time.
    action = step(&policy, SYNC_EVENT_UPDATE, 2000000);
    CHECK(action.arm_hold_timer && action.hold_deadline_ms == 2000000 + HOLD_MS);
}

static void test_early_and_stale_timers_do_nothing(void)
{
    struct sync_policy policy = ready_policy(&held);
    CHECK(is_no_action(step(&policy, SYNC_EVENT_HOLD_TIMER, 500)));

    step(&policy, SYNC_EVENT_UPDATE, 1000);
    CHECK(is_no_action(step(&policy, SYNC_EVENT_HOLD_TIMER, 1000 + HOLD_MS - 1)));
    CHECK(policy.pending_updates == 1);

    CHECK(step(&policy, SYNC_EVENT_HOLD_TIMER, 1000 + HOLD_MS).flush);
    CHECK(is_no_action(step(&policy, SYNC_EVENT_HOLD_TIMER, 1000 + HOLD_MS)));
}

static void test_radio_activity_carries_pending_updates_and_cancels_the_timer(void)
{
    struct sync_policy policy = ready_policy(&held);
    CHECK(is_no_action(step(&policy, SYNC_EVENT_RADIO_ACTIVE, 500)));

    step(&policy, SYNC_EVENT_UPDATE, 1000);
    step(&policy, SYNC_EVENT_UPDATE, 2000);
    const struct sync_action action = step(&policy, SYNC_EVENT_RADIO_ACTIVE, 3000);
    CHECK(action.flush && action.flushed_updates == 2 && action.cancel_hold_timer);
    CHECK(!action.arm_hold_timer);

    // Nothing is left, so the cancelled timer firing anyway is harmless.
    CHECK(is_no_action(step(&policy, SYNC_EVENT_HOLD_TIMER, 1000 + HOLD_MS)));
}

static void test_updates_wait_for_a_peer_and_keep_their_deadline(void)
{
    struct sync_policy policy;
    sync_policy_init(&policy, &held, 0);

    // No peer can receive, so nothing is sent and no timer runs.
    CHECK(is_no_action(step(&policy, SYNC_EVENT_UPDATE, 1000)));
    CHECK(is_no_action(step(&policy, SYNC_EVENT_UPDATE, 2000)));
    CHECK(is_no_action(step(&policy, SYNC_EVENT_RADIO_ACTIVE, 3000)));

    // The wait is measured from the first update, not from when the peer arrived.
    struct sync_policy early = policy;
    struct sync_action action = step(&early, SYNC_EVENT_LINK_READY, 5000);
    CHECK(!action.flush && action.arm_hold_timer && action.hold_deadline_ms == 1000 + HOLD_MS);

    // A peer that arrives after the deadline gets the updates at once.
    CHECK(is_no_action(step(&policy, SYNC_EVENT_HOLD_TIMER, 1000 + HOLD_MS)));
    action = step(&policy, SYNC_EVENT_LINK_READY, 1000 + HOLD_MS + 5);
    CHECK(action.flush && action.flushed_updates == 2 && !action.arm_hold_timer);
}

static void test_zero_hold_sends_held_updates_as_soon_as_a_peer_can_receive(void)
{
    struct sync_policy policy;
    sync_policy_init(&policy, &at_once, 0);
    CHECK(is_no_action(step(&policy, SYNC_EVENT_UPDATE, 1000)));
    CHECK(is_no_action(step(&policy, SYNC_EVENT_UPDATE, 2000)));

    const struct sync_action action = step(&policy, SYNC_EVENT_LINK_READY, 3000);
    CHECK(action.flush && action.flushed_updates == 2);
}

static void test_link_loss_cancels_the_timer_and_keeps_the_updates(void)
{
    struct sync_policy policy = ready_policy(&held);
    CHECK(is_no_action(step(&policy, SYNC_EVENT_LINK_LOST, 500)));

    step(&policy, SYNC_EVENT_LINK_READY, 600);
    step(&policy, SYNC_EVENT_UPDATE, 1000);
    struct sync_action action = step(&policy, SYNC_EVENT_LINK_LOST, 2000);
    CHECK(action.cancel_hold_timer && !action.flush);
    CHECK(policy.pending_updates == 1);
    CHECK(is_no_action(step(&policy, SYNC_EVENT_LINK_LOST, 2500)));

    action = step(&policy, SYNC_EVENT_LINK_READY, 3000);
    CHECK(action.arm_hold_timer && action.hold_deadline_ms == 1000 + HOLD_MS);
    CHECK(is_no_action(step(&policy, SYNC_EVENT_LINK_READY, 3500)));
}

static void test_an_update_after_an_overdue_deadline_does_not_wait_for_the_late_timer(void)
{
    struct sync_policy policy = ready_policy(&held);
    step(&policy, SYNC_EVENT_UPDATE, 1000);

    const struct sync_action action = step(&policy, SYNC_EVENT_UPDATE, 1000 + HOLD_MS + 50);
    CHECK(action.flush && action.flushed_updates == 2);
    CHECK(is_no_action(step(&policy, SYNC_EVENT_HOLD_TIMER, 1000 + HOLD_MS + 60)));
}

static void test_deadline_saturates_at_the_end_of_the_clock(void)
{
    struct sync_policy policy;
    sync_policy_init(&policy, &held, UINT64_MAX - 10);
    step(&policy, SYNC_EVENT_LINK_READY, UINT64_MAX - 10);

    const struct sync_action action = step(&policy, SYNC_EVENT_UPDATE, UINT64_MAX - 5);
    CHECK(action.arm_hold_timer && action.hold_deadline_ms == UINT64_MAX);
    CHECK(step(&policy, SYNC_EVENT_HOLD_TIMER, UINT64_MAX).flush);
}

static void test_bad_input_leaves_the_policy_and_action_unchanged(void)
{
    struct sync_policy policy = ready_policy(&held);
    step(&policy, SYNC_EVENT_UPDATE, 1000);
    const struct sync_policy before = policy;
    struct sync_action action = {.flushed_updates = 77};

    CHECK(!sync_policy_step(&policy, SYNC_EVENT_UPDATE, 999, &action));
    CHECK(!sync_policy_step(&policy, (enum sync_event)99, 2000, &action));
    CHECK(policy.pending_updates == before.pending_updates);
    CHECK(policy.hold_deadline_ms == before.hold_deadline_ms);
    CHECK(policy.last_event_ms == before.last_event_ms && policy.link_ready);
    CHECK(action.flushed_updates == 77 && !action.flush);
}

int main(void)
{
    test_zero_hold_sends_every_update_at_once();
    test_updates_inside_the_hold_share_one_transfer();
    test_early_and_stale_timers_do_nothing();
    test_radio_activity_carries_pending_updates_and_cancels_the_timer();
    test_updates_wait_for_a_peer_and_keep_their_deadline();
    test_zero_hold_sends_held_updates_as_soon_as_a_peer_can_receive();
    test_link_loss_cancels_the_timer_and_keeps_the_updates();
    test_an_update_after_an_overdue_deadline_does_not_wait_for_the_late_timer();
    test_deadline_saturates_at_the_end_of_the_clock();
    test_bad_input_leaves_the_policy_and_action_unchanged();
    puts("sync policy tests passed");
    return EXIT_SUCCESS;
}
