#ifndef POCKETPET_ADV_POLICY_H
#define POCKETPET_ADV_POLICY_H

#include <stdbool.h>
#include <stdint.h>

/*
 * Advertising intervals use the Bluetooth unit of 0.625 ms, the form a
 * controller takes. Legacy advertising allows 20 ms to 10.24 s.
 */
enum {
    ADV_INTERVAL_UNITS_MIN = 0x0020,
    ADV_INTERVAL_UNITS_MAX = 0x4000,
};

enum adv_event {
    /* The tag has no link. Boot counts, as does a dropped connection. */
    ADV_EVENT_LINK_LOST,
    ADV_EVENT_SWITCH_TIMER,
    ADV_EVENT_LINK_CONNECTED,
};

enum adv_phase {
    ADV_PHASE_STOPPED,
    ADV_PHASE_FAST,
    ADV_PHASE_SLOW,
};

/*
 * A fixed-rate policy sets slow_interval_units equal to fast_interval_units.
 * A fixed and a fast-then-slow policy that share fast_interval_units then
 * start at the same rate, as a matched comparison requires.
 */
struct adv_policy_config {
    uint16_t fast_interval_units;
    uint16_t slow_interval_units;
    /* Time at the fast rate before the switch. Unused by a fixed-rate policy. */
    uint32_t fast_duration_ms;
};

struct adv_policy {
    struct adv_policy_config config;
    enum adv_phase phase;
    uint64_t last_event_ms;
    uint64_t switch_deadline_ms;
};

/* What the caller must do after a step. All fields are false or zero for no action. */
struct adv_action {
    /* Advertise at interval_units, restarting if advertising is already running. */
    bool start;
    uint16_t interval_units;
    /* Deliver ADV_EVENT_SWITCH_TIMER at switch_deadline_ms. */
    bool arm_switch_timer;
    uint64_t switch_deadline_ms;
    bool cancel_switch_timer;
};

/*
 * Returns false and leaves the policy unchanged when an interval is out of
 * range, the slow interval is shorter than the fast one, or a switching policy
 * has a zero fast duration.
 */
bool adv_policy_init(struct adv_policy *policy, const struct adv_policy_config *config,
                     uint64_t now_ms);

/*
 * Apply an event using the caller's monotonic clock. An unknown event or a
 * backward timestamp returns false and leaves the policy and action unchanged.
 * A switch timer that fires before the deadline, or after the link is back, is
 * accepted and does nothing, so a stale timer cannot slow advertising early.
 */
bool adv_policy_step(struct adv_policy *policy, enum adv_event event, uint64_t now_ms,
                     struct adv_action *action);

#endif
