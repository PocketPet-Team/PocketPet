#include "adv_policy.h"

static bool interval_in_range(uint16_t units)
{
    return units >= ADV_INTERVAL_UNITS_MIN && units <= ADV_INTERVAL_UNITS_MAX;
}

static bool switches_rate(const struct adv_policy_config *config)
{
    return config->slow_interval_units != config->fast_interval_units;
}

bool adv_policy_init(struct adv_policy *policy, const struct adv_policy_config *config,
                     uint64_t now_ms)
{
    if (!interval_in_range(config->fast_interval_units) ||
        !interval_in_range(config->slow_interval_units) ||
        config->slow_interval_units < config->fast_interval_units ||
        (switches_rate(config) && config->fast_duration_ms == 0)) {
        return false;
    }

    *policy = (struct adv_policy){
        .config = *config,
        .phase = ADV_PHASE_STOPPED,
        .last_event_ms = now_ms,
    };
    return true;
}

bool adv_policy_step(struct adv_policy *policy, enum adv_event event, uint64_t now_ms,
                     struct adv_action *action)
{
    if (now_ms < policy->last_event_ms) {
        return false;
    }

    const struct adv_policy_config *config = &policy->config;
    struct adv_action next_action = {0};
    switch (event) {
    case ADV_EVENT_LINK_LOST:
        if (policy->phase != ADV_PHASE_STOPPED) {
            break;
        }
        policy->phase = ADV_PHASE_FAST;
        next_action.start = true;
        next_action.interval_units = config->fast_interval_units;
        if (switches_rate(config)) {
            // Saturate so a clock near its maximum cannot wrap to an early deadline.
            const uint64_t room = UINT64_MAX - now_ms;
            policy->switch_deadline_ms =
                config->fast_duration_ms > room ? UINT64_MAX : now_ms + config->fast_duration_ms;
            next_action.arm_switch_timer = true;
            next_action.switch_deadline_ms = policy->switch_deadline_ms;
        }
        break;
    case ADV_EVENT_SWITCH_TIMER:
        if (policy->phase == ADV_PHASE_FAST && switches_rate(config) &&
            now_ms >= policy->switch_deadline_ms) {
            policy->phase = ADV_PHASE_SLOW;
            next_action.start = true;
            next_action.interval_units = config->slow_interval_units;
        }
        break;
    case ADV_EVENT_LINK_CONNECTED:
        // The controller stops connectable advertising itself once a link forms.
        next_action.cancel_switch_timer =
            policy->phase == ADV_PHASE_FAST && switches_rate(config);
        policy->phase = ADV_PHASE_STOPPED;
        break;
    default:
        return false;
    }

    policy->last_event_ms = now_ms;
    *action = next_action;
    return true;
}
