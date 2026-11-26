"""Pair run summaries into baseline-candidate comparisons and check that pairs match."""

from __future__ import annotations

from typing import Any

from pocketpet_analysis.manifest import PAIRING_FIELDS
from pocketpet_analysis.stats import DEFAULT_RESAMPLES, paired_difference_ci

# A pair must share these, because a difference in any of them is a competing explanation
# for a charge difference. ``board_id`` is checked too when a manifest records it.
MATCHED_METADATA = ("board_rev", "board_id", "supply_v", "phone_model", "os_version")
DURATION_TOLERANCE = 0.01


def compare_runs(
    summaries: list[dict[str, Any]],
    *,
    metric: str = "total.charge_uc",
    seed: int,
    resamples: int = DEFAULT_RESAMPLES,
) -> list[dict[str, Any]]:
    """Return one comparison per (rq, condition), built from complete matched pairs."""
    conditions: dict[tuple[str, str], dict[str, dict[str, dict[str, Any]]]] = {}
    for summary in summaries:
        missing = [name for name in PAIRING_FIELDS if name not in summary]
        if missing:
            raise ValueError(f"run {summary['run_id']!r} is missing pairing fields {missing}")
        pairs = conditions.setdefault((summary["rq"], summary["condition"]), {})
        roles = pairs.setdefault(summary["pair_id"], {})
        if summary["role"] in roles:
            raise ValueError(
                f"pair {summary['pair_id']!r} in {summary['condition']!r} has two "
                f"{summary['role']} runs"
            )
        roles[summary["role"]] = summary

    return [
        _compare_condition(rq, condition, pairs, metric, seed, resamples)
        for (rq, condition), pairs in sorted(conditions.items())
    ]


def _compare_condition(
    rq: str,
    condition: str,
    pairs: dict[str, dict[str, dict[str, Any]]],
    metric: str,
    seed: int,
    resamples: int,
) -> dict[str, Any]:
    baselines, candidates, warnings = [], [], []
    for pair_id, roles in sorted(pairs.items()):
        if set(roles) != {"baseline", "candidate"}:
            raise ValueError(f"pair {pair_id!r} in {condition!r} needs a baseline and a candidate")
        baseline, candidate = roles["baseline"], roles["candidate"]
        _require_matched(pair_id, baseline, candidate)
        durations = [run["total"]["duration_s"] for run in (baseline, candidate)]
        if abs(durations[0] - durations[1]) > DURATION_TOLERANCE * max(durations):
            warnings.append(
                f"pair {pair_id!r} durations differ: {durations[0]:.3f} s and {durations[1]:.3f} s"
            )
        baselines.append(baseline)
        candidates.append(candidate)

    runs = baselines + candidates
    result = paired_difference_ci(
        [_metric(run, metric) for run in baselines],
        [_metric(run, metric) for run in candidates],
        seed=seed,
        resamples=resamples,
    )
    all_formal = all(run["metadata"]["phase"] == "formal-frozen" for run in runs)
    return {
        "rq": rq,
        "condition": condition,
        "metric": metric,
        "baseline_variant": _single(baselines, "variant", condition),
        "candidate_variant": _single(candidates, "variant", condition),
        "phase": "formal-frozen" if all_formal else "pilot",
        "board_revs": sorted({run["metadata"]["board_rev"] for run in runs}),
        "baseline_firmware_shas": sorted({run["metadata"]["firmware_sha"] for run in baselines}),
        "candidate_firmware_shas": sorted({run["metadata"]["firmware_sha"] for run in candidates}),
        **result,
        "warnings": warnings,
    }


def _require_matched(pair_id: str, baseline: dict[str, Any], candidate: dict[str, Any]) -> None:
    mismatched = [
        name
        for name in MATCHED_METADATA
        if baseline["metadata"].get(name) != candidate["metadata"].get(name)
    ]
    if baseline["workload"] != candidate["workload"]:
        mismatched.append("workload")
    if mismatched:
        raise ValueError(f"pair {pair_id!r} is not matched on {mismatched}")


def _single(runs: list[dict[str, Any]], name: str, condition: str) -> str:
    values = {run[name] for run in runs}
    if len(values) != 1:
        raise ValueError(f"{condition!r} mixes several {name} values in one role: {sorted(values)}")
    return values.pop()


def _metric(summary: dict[str, Any], dotted_path: str) -> float:
    value: Any = summary
    for part in dotted_path.split("."):
        value = value[part]
    return float(value)
