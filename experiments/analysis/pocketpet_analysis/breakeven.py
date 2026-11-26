"""Break-even trigger rate: how many unwanted wakes per hour cancel a wake policy's saving.

Each matched pair runs a baseline and a candidate policy against the same trigger
schedule. The candidate is expected to draw less with no triggers and to pay for each
trigger, so the within-pair difference in mean current rises with the trigger rate. The
rate where a line through those differences crosses zero is the break-even rate.
"""

from __future__ import annotations

from typing import Any

from pocketpet_analysis.compare import matched_pairs, single_value
from pocketpet_analysis.schedule import Schedule
from pocketpet_analysis.stats import (
    DEFAULT_RESAMPLES,
    MIN_FORMAL_PAIRS,
    line_crossing_ci,
    paired_difference_ci,
)

SECONDS_PER_HOUR = 3600.0
# Mean current, not charge, so runs of different lengths stay comparable.
METRIC = "total.mean_current_ua"
DURATION_TOLERANCE = 0.01


def break_even(
    summaries: list[dict[str, Any]],
    schedules: dict[str, Schedule],
    *,
    seed: int,
    resamples: int = DEFAULT_RESAMPLES,
) -> dict[str, Any]:
    """Fit candidate-minus-baseline mean current against trigger rate and find its zero.

    ``schedules`` maps each run's ``workload`` to the schedule it replayed. The trigger
    rate of a pair is the rate of that schedule, not a count of wakes seen in the capture.
    """
    pairs_by_condition = matched_pairs(summaries)
    rqs = sorted({rq for rq, _ in pairs_by_condition})
    if len(rqs) != 1:
        raise ValueError(f"the runs must belong to one research question, found {rqs}")

    by_rate: dict[float, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    warnings: list[str] = []
    for pairs in pairs_by_condition.values():
        for pair_id, baseline, candidate in pairs:
            schedule = schedules.get(baseline["workload"])
            if schedule is None:
                raise ValueError(
                    f"pair {pair_id!r} replayed {baseline['workload']!r}, which is not among "
                    "the schedules given"
                )
            warnings += _duration_warnings(pair_id, schedule, (baseline, candidate))
            by_rate.setdefault(schedule.rate_per_h, []).append((baseline, candidate))

    rates, differences = [], []
    for rate, pairs in by_rate.items():
        rates += [rate] * len(pairs)
        differences += [_mean_ua(candidate) - _mean_ua(baseline) for baseline, candidate in pairs]
    fit = line_crossing_ci(rates, differences, seed=seed, resamples=resamples)

    rows = [
        _rate_row(rate, by_rate[rate], fit, seed, resamples, warnings) for rate in sorted(by_rate)
    ]
    break_even_rate = fit["crossing"]
    if break_even_rate is None:
        warnings.append(
            "the difference does not rise with the trigger rate, so there is no break-even rate"
        )
    else:
        if fit["crossing_ci"] is None:
            warnings.append(
                "the slope is not distinguishable from zero, so the break-even rate has no "
                "bounded interval"
            )
        if not rows[0]["trigger_rate_per_h"] <= break_even_rate <= rows[-1]["trigger_rate_per_h"]:
            warnings.append("the break-even rate lies outside the measured rates (extrapolated)")
    if fit["intercept_ci"][1] >= 0.0:
        warnings.append("the candidate's saving with no triggers is not distinguishable from zero")

    baselines = [baseline for pairs in by_rate.values() for baseline, _ in pairs]
    candidates = [candidate for pairs in by_rate.values() for _, candidate in pairs]
    runs = baselines + candidates
    all_formal = all(run["metadata"]["phase"] == "formal-frozen" for run in runs)
    return {
        "rq": rqs[0],
        "metric": METRIC,
        "baseline_variant": single_value(baselines, "variant", rqs[0]),
        "candidate_variant": single_value(candidates, "variant", rqs[0]),
        "phase": "formal-frozen" if all_formal else "pilot",
        "board_revs": sorted({run["metadata"]["board_rev"] for run in runs}),
        "baseline_firmware_shas": sorted({run["metadata"]["firmware_sha"] for run in baselines}),
        "candidate_firmware_shas": sorted({run["metadata"]["firmware_sha"] for run in candidates}),
        "pairs": len(baselines),
        "meets_min_pairs": all(row["pairs"] >= MIN_FORMAL_PAIRS for row in rows),
        "rates": rows,
        "saving_at_zero_ua": -fit["intercept"],
        "saving_at_zero_ci": [-fit["intercept_ci"][1], -fit["intercept_ci"][0]],
        # The slope is in uA per trigger/h; an hour of it is the charge one trigger adds.
        "charge_per_trigger_uc": fit["slope"] * SECONDS_PER_HOUR,
        "charge_per_trigger_ci": [bound * SECONDS_PER_HOUR for bound in fit["slope_ci"]],
        "break_even_rate_per_h": break_even_rate,
        "break_even_ci": fit["crossing_ci"],
        "nonpositive_slope_draws": fit["nonpositive_slope_draws"],
        "method": fit["method"],
        "confidence": fit["confidence"],
        "resamples": resamples,
        "seed": seed,
        "warnings": warnings,
    }


def _rate_row(
    rate: float,
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    fit: dict[str, Any],
    seed: int,
    resamples: int,
    warnings: list[str],
) -> dict[str, Any]:
    """Summarize one trigger rate and note it in ``warnings`` if it sits off the line."""
    result = paired_difference_ci(
        [_mean_ua(baseline) for baseline, _ in pairs],
        [_mean_ua(candidate) for _, candidate in pairs],
        seed=seed,
        resamples=resamples,
    )
    fitted = fit["intercept"] + fit["slope"] * rate
    low, high = result["mean_difference_ci"]
    if not low <= fitted <= high:
        warnings.append(
            f"at {rate:g} triggers/h the fitted line ({fitted:.3g} uA) is outside the measured "
            f"interval [{low:.3g}, {high:.3g}] uA; check that the cost per trigger is constant"
        )
    return {
        "trigger_rate_per_h": rate,
        "pairs": result["pairs"],
        "workloads": sorted({baseline["workload"] for baseline, _ in pairs}),
        "mean_difference_ua": result["mean_difference"],
        "mean_difference_ci": result["mean_difference_ci"],
        "fitted_difference_ua": fitted,
    }


def _duration_warnings(
    pair_id: str, schedule: Schedule, runs: tuple[dict[str, Any], dict[str, Any]]
) -> list[str]:
    """A run cut short missed triggers; one left running dilutes them."""
    scheduled_s = schedule.duration_ms / 1000.0
    return [
        f"pair {pair_id!r} {run['role']} ran {run['total']['duration_s']:.1f} s against a "
        f"{scheduled_s:.1f} s schedule"
        for run in runs
        if abs(run["total"]["duration_s"] - scheduled_s) > DURATION_TOLERANCE * scheduled_s
    ]


def _mean_ua(summary: dict[str, Any]) -> float:
    return float(summary["total"]["mean_current_ua"])
