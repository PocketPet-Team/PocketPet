#include "sync_policy.h"

void sync_policy_init(struct sync_policy *policy, const struct sync_policy_config *config,
                      uint64_t now_ms)
{
    *policy = (struct sync_policy){
        .config = *config,
        .last_event_ms = now_ms,
    };
}

static void flush(struct sync_policy *policy, struct sync_action *action)
{
    action->flush = true;
    action->flushed_updates = policy->pending_updates;
    policy->pending_updates = 0;
}

/* Send now if the oldest update has waited long enough, otherwise wait for its deadline. */
static void flush_or_wait(struct sync_policy *policy, uint64_t now_ms, struct sync_action *action)
{
    if (now_ms >= policy->hold_deadline_ms) {
        flush(policy, action);
    } else {
        action->arm_hold_timer = true;
        action->hold_deadline_ms = policy->hold_deadline_ms;
    }
}

bool sync_policy_step(struct sync_policy *policy, enum sync_event event, uint64_t now_ms,
                      struct sync_action *action)
{
    if (now_ms < policy->last_event_ms) {
        return false;
    }

    struct sync_action next_action = {0};
    switch (event) {
    case SYNC_EVENT_UPDATE: {
        const bool first = policy->pending_updates == 0;
        if (first) {
            // Saturate so a clock near its maximum cannot wrap to an early deadline.
            const uint32_t max_hold_ms = policy->config.max_hold_ms;
            const uint64_t room = UINT64_MAX - now_ms;
            policy->hold_deadline_ms = max_hold_ms > room ? UINT64_MAX : now_ms + max_hold_ms;
        }
        if (policy->pending_updates < UINT32_MAX) {
            policy->pending_updates++;
        }
        // A later update joins the wait the first one started, so only the
        // first arms the timer. An overdue wait ends here even if its timer is late.
        if (policy->link_ready && (first || now_ms >= policy->hold_deadline_ms)) {
            flush_or_wait(policy, now_ms, &next_action);
        }
        break;
    }
    case SYNC_EVENT_RADIO_ACTIVE:
        if (policy->link_ready && policy->pending_updates > 0) {
            flush(policy, &next_action);
            next_action.cancel_hold_timer = true;
        }
        break;
    case SYNC_EVENT_HOLD_TIMER:
        if (policy->link_ready && policy->pending_updates > 0 &&
            now_ms >= policy->hold_deadline_ms) {
            flush(policy, &next_action);
        }
        break;
    case SYNC_EVENT_LINK_READY:
        if (!policy->link_ready) {
            policy->link_ready = true;
            if (policy->pending_updates > 0) {
                flush_or_wait(policy, now_ms, &next_action);
            }
        }
        break;
    case SYNC_EVENT_LINK_LOST:
        // The updates stay pending; only their timer goes.
        next_action.cancel_hold_timer = policy->link_ready && policy->pending_updates > 0;
        policy->link_ready = false;
        break;
    default:
        return false;
    }

    policy->last_event_ms = now_ms;
    *action = next_action;
    return true;
}
