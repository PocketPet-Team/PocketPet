#ifndef POCKETPET_SYNC_POLICY_H
#define POCKETPET_SYNC_POLICY_H

#include <stdbool.h>
#include <stdint.h>

/*
 * Decides when routine state updates go out over the link (RQ4).
 *
 * An update may be held so that later updates, or a button or Find exchange
 * that uses the radio anyway, share its transfer. While a peer can receive,
 * no update waits longer than max_hold_ms. Button and Find handling never
 * waits on this policy: it only times routine updates.
 */

enum sync_event {
    /* A routine state update is ready to send. */
    SYNC_EVENT_UPDATE,
    /* The link is carrying a button or Find exchange right now. */
    SYNC_EVENT_RADIO_ACTIVE,
    SYNC_EVENT_HOLD_TIMER,
    /* A peer can receive updates. */
    SYNC_EVENT_LINK_READY,
    SYNC_EVENT_LINK_LOST,
};

struct sync_policy_config {
    /*
     * Longest an update may wait while a peer can receive it. Zero sends
     * every update at once, which is the unbatched baseline.
     */
    uint32_t max_hold_ms;
};

struct sync_policy {
    struct sync_policy_config config;
    bool link_ready;
    uint32_t pending_updates;
    /* When the oldest pending update must go out; valid while one is pending. */
    uint64_t hold_deadline_ms;
    uint64_t last_event_ms;
};

struct sync_action {
    /* Send one transfer that covers every pending update. */
    bool flush;
    uint32_t flushed_updates;
    bool arm_hold_timer;
    /* Absolute time for SYNC_EVENT_HOLD_TIMER; valid when arm_hold_timer is set. */
    uint64_t hold_deadline_ms;
    bool cancel_hold_timer;
};

void sync_policy_init(struct sync_policy *policy, const struct sync_policy_config *config,
                      uint64_t now_ms);

/*
 * Apply an event using the caller's monotonic clock. Equal timestamps are
 * processed in call order. An unknown event or a backward timestamp returns
 * false and leaves the policy and action unchanged. Updates that arrive
 * without a link stay pending and go out once a peer can receive them. A
 * hold timer that fires early, or after its updates have gone, does nothing.
 */
bool sync_policy_step(struct sync_policy *policy, enum sync_event event, uint64_t now_ms,
                      struct sync_action *action);

#endif
