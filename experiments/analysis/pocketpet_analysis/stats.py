"""Bootstrap confidence intervals that resample whole pairs or whole runs.

Samples inside one run are correlated, so the resampling unit is always the run (or the
matched pair of runs), never an individual sample or trial.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

MIN_FORMAL_PAIRS = 10
DEFAULT_RESAMPLES = 10_000


def paired_difference_ci(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    seed: int,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Bootstrap-t interval for the mean within-pair difference, candidate minus baseline.

    ``relative_change`` is the ratio of mean candidate to mean baseline minus one. Its
    interval uses the same pair draws and a linearized standard error.
    """
    base = np.asarray(baseline, dtype=float)
    cand = np.asarray(candidate, dtype=float)
    if base.shape != cand.shape or base.ndim != 1:
        raise ValueError("baseline and candidate must be equal-length sequences")
    if base.size < 2:
        raise ValueError("at least two pairs are needed for a confidence interval")

    draws = np.random.default_rng(seed).integers(0, base.size, size=(resamples, base.size))
    base_draws, cand_draws = base[draws], cand[draws]
    ratio = cand.mean() / base.mean()
    ratio_draws = cand_draws.mean(axis=1) / base_draws.mean(axis=1)
    return {
        "pairs": int(base.size),
        "meets_min_pairs": bool(base.size >= MIN_FORMAL_PAIRS),
        "baseline_mean": float(base.mean()),
        "candidate_mean": float(cand.mean()),
        "mean_difference": float((cand - base).mean()),
        "mean_difference_ci": _studentized_interval(
            cand - base, cand_draws - base_draws, confidence
        ),
        "relative_change": float(ratio - 1.0),
        # Each pair's first-order contribution to the ratio, shifted so the mean is the ratio.
        "relative_change_ci": _studentized_interval(
            (cand - ratio * base) / base.mean() + ratio - 1.0,
            (cand_draws - ratio_draws[:, None] * base_draws) / base_draws.mean(axis=1)[:, None]
            + ratio_draws[:, None]
            - 1.0,
            confidence,
        ),
        "method": "bootstrap-t over whole pairs",
        "confidence": confidence,
        "resamples": resamples,
        "seed": seed,
    }


def success_rate_ci(
    successes_per_run: Sequence[int],
    trials_per_run: Sequence[int],
    *,
    seed: int,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Percentile bootstrap of a pooled success rate, resampling whole runs.

    The percentile form keeps the interval inside [0, 1]. It is approximate with few runs
    and collapses to a point when every run has the same rate.
    """
    successes = np.asarray(successes_per_run, dtype=float)
    trials = np.asarray(trials_per_run, dtype=float)
    if successes.shape != trials.shape or successes.ndim != 1 or successes.size == 0:
        raise ValueError("successes and trials must be equal-length, non-empty sequences")
    if (trials <= 0).any() or (successes > trials).any() or (successes < 0).any():
        raise ValueError("each run needs at least one trial and 0 <= successes <= trials")

    draws = np.random.default_rng(seed).integers(0, trials.size, size=(resamples, trials.size))
    rates = successes[draws].sum(axis=1) / trials[draws].sum(axis=1)
    return {
        "runs": int(trials.size),
        "trials": int(trials.sum()),
        "successes": int(successes.sum()),
        "success_rate": float(successes.sum() / trials.sum()),
        "success_rate_ci": _percentile_interval(rates, confidence),
        "method": "percentile bootstrap over whole runs",
        "confidence": confidence,
        "resamples": resamples,
        "seed": seed,
    }


def _studentized_interval(
    values: np.ndarray, resampled: np.ndarray, confidence: float
) -> list[float]:
    """Bootstrap-t interval for the mean of ``values``; each row of ``resampled`` is one draw.

    A percentile interval is too narrow with about ten pairs. Studentizing each draw by
    its own standard error widens it roughly as a t interval would.
    """
    count = values.size
    estimate = values.mean()
    error = values.std(ddof=1) / np.sqrt(count)
    if error == 0.0:
        return [float(estimate), float(estimate)]
    resampled_errors = resampled.std(axis=1, ddof=1) / np.sqrt(count)
    # A draw that repeats one value has zero spread and carries no information about t.
    usable = resampled_errors > 0.0
    t_values = (resampled.mean(axis=1)[usable] - estimate) / resampled_errors[usable]
    tail = (1.0 - confidence) / 2.0
    t_low, t_high = np.quantile(t_values, [tail, 1.0 - tail])
    return [float(estimate - t_high * error), float(estimate - t_low * error)]


def _percentile_interval(estimates: np.ndarray, confidence: float) -> list[float]:
    tail = (1.0 - confidence) / 2.0
    low, high = np.quantile(estimates, [tail, 1.0 - tail])
    return [float(low), float(high)]
