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
    if resamples < 1 or not np.isfinite(base).all() or not np.isfinite(cand).all():
        raise ValueError("paired comparisons need finite values and a positive resample count")

    draws = np.random.default_rng(seed).integers(0, base.size, size=(resamples, base.size))
    base_draws, cand_draws = base[draws], cand[draws]
    # Zero baseline timeouts or zero transfers are valid for the absolute comparison.
    ratio = cand.mean() / base.mean() if base.mean() != 0 else None
    draw_means = base_draws.mean(axis=1)
    relative_ci = None
    if ratio is not None and np.all(draw_means != 0):
        ratio_draws = cand_draws.mean(axis=1) / draw_means
        relative_ci = _studentized_interval(
            (cand - ratio * base) / base.mean() + ratio - 1.0,
            (cand_draws - ratio_draws[:, None] * base_draws) / draw_means[:, None]
            + ratio_draws[:, None]
            - 1.0,
            confidence,
        )
    return {
        "pairs": int(base.size),
        "meets_min_pairs": bool(base.size >= MIN_FORMAL_PAIRS),
        "baseline_mean": float(base.mean()),
        "candidate_mean": float(cand.mean()),
        "mean_difference": float((cand - base).mean()),
        "mean_difference_ci": _studentized_interval(
            cand - base, cand_draws - base_draws, confidence
        ),
        "relative_change": float(ratio - 1) if ratio is not None else None,
        "relative_change_ci": relative_ci,
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
    if resamples < 1:
        raise ValueError("resamples must be positive")
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


def line_crossing_ci(
    x: Sequence[float],
    y: Sequence[float],
    *,
    seed: int,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Fit ``y = intercept + slope * x`` and estimate where the line crosses zero.

    Each ``y`` comes from one matched pair measured at design point ``x``. Resampling
    keeps the design: pairs are redrawn only among those that share an ``x``. All three
    intervals are bootstrap-t. ``crossing`` is None unless the fitted slope is positive,
    and ``crossing_ci`` is None unless the slope's interval lies above zero, because a
    line that may be flat has no bounded crossing.
    """
    points = np.asarray(x, dtype=float)
    values = np.asarray(y, dtype=float)
    if points.shape != values.shape or points.ndim != 1:
        raise ValueError("x and y must be equal-length sequences")
    levels = np.unique(points)
    groups = [np.flatnonzero(points == level) for level in levels]
    if len(groups) < 2:
        raise ValueError("a line needs at least two distinct x values")
    if min(group.size for group in groups) < 2:
        raise ValueError("each x value needs at least two pairs")

    # Both coefficients are weighted sums of y, so their variances follow from the
    # spread of y inside each group and no common noise level has to be assumed.
    centered = points - points.mean()
    slope_weights = centered / (centered**2).sum()
    intercept_weights = 1.0 / points.size - points.mean() * slope_weights

    def fit(rows: np.ndarray) -> tuple[np.ndarray, ...]:
        variance = np.empty(rows.shape)
        for group in groups:
            variance[..., group] = rows[..., group].var(axis=-1, ddof=1, keepdims=True)
        intercept, slope = rows @ intercept_weights, rows @ slope_weights
        intercept_var = variance @ intercept_weights**2
        slope_var = variance @ slope_weights**2
        covariance = variance @ (intercept_weights * slope_weights)
        with np.errstate(divide="ignore", invalid="ignore"):
            crossing = -intercept / slope
            # First-order (delta method) standard error of the ratio.
            crossing_var = intercept_var + crossing**2 * slope_var + 2 * crossing * covariance
            crossing_error = np.sqrt(np.maximum(crossing_var, 0.0)) / np.abs(slope)
        return (
            intercept,
            np.sqrt(intercept_var),
            slope,
            np.sqrt(slope_var),
            crossing,
            crossing_error,
        )

    rng = np.random.default_rng(seed)
    draws = np.empty((resamples, points.size), dtype=np.intp)
    for group in groups:
        draws[:, group] = rng.choice(group, size=(resamples, group.size))
    estimate = [float(value) for value in fit(values)]
    drawn = fit(values[draws])

    slope_ci = _t_interval(estimate[2], estimate[3], drawn[2], drawn[3], confidence)
    rising = drawn[2] > 0.0
    crossing = estimate[4] if estimate[2] > 0.0 else None
    crossing_ci = None
    if crossing is not None and slope_ci[0] > 0.0:
        crossing_ci = _t_interval(
            crossing, estimate[5], drawn[4][rising], drawn[5][rising], confidence
        )
    return {
        "points": int(points.size),
        "levels": [float(level) for level in levels],
        "intercept": estimate[0],
        "intercept_ci": _t_interval(estimate[0], estimate[1], drawn[0], drawn[1], confidence),
        "slope": estimate[2],
        "slope_ci": slope_ci,
        "crossing": crossing,
        "crossing_ci": crossing_ci,
        "nonpositive_slope_draws": float(1.0 - rising.mean()),
        "method": "bootstrap-t over whole pairs, resampled within each x",
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
    return _t_interval(
        values.mean(),
        values.std(ddof=1) / np.sqrt(count),
        resampled.mean(axis=1),
        resampled.std(axis=1, ddof=1) / np.sqrt(count),
        confidence,
    )


def _t_interval(
    estimate: float,
    error: float,
    drawn_estimates: np.ndarray,
    drawn_errors: np.ndarray,
    confidence: float,
) -> list[float]:
    """Bootstrap-t interval from an estimate, its standard error, and the same for each draw."""
    if error == 0.0:
        return [float(estimate), float(estimate)]
    # A draw that repeats one value has zero spread and carries no information about t.
    usable = drawn_errors > 0.0
    if not usable.any():
        raise ValueError("no resampled estimate has nonzero spread; increase --resamples")
    t_values = (drawn_estimates[usable] - estimate) / drawn_errors[usable]
    tail = (1.0 - confidence) / 2.0
    t_low, t_high = np.quantile(t_values, [tail, 1.0 - tail])
    return [float(estimate - t_high * error), float(estimate - t_low * error)]


def _percentile_interval(estimates: np.ndarray, confidence: float) -> list[float]:
    tail = (1.0 - confidence) / 2.0
    low, high = np.quantile(estimates, [tail, 1.0 - tail])
    return [float(low), float(high)]
