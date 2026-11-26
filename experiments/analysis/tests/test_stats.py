import numpy as np
import pytest

from pocketpet_analysis.stats import paired_difference_ci, success_rate_ci


def test_constant_difference_gives_a_degenerate_interval():
    baseline = [100.0, 120.0, 90.0, 110.0]
    candidate = [value - 10.0 for value in baseline]

    result = paired_difference_ci(baseline, candidate, seed=1)

    assert result["mean_difference"] == pytest.approx(-10.0)
    assert result["mean_difference_ci"] == pytest.approx([-10.0, -10.0])
    assert result["pairs"] == 4
    assert result["meets_min_pairs"] is False


def test_pairing_removes_run_to_run_spread():
    rng = np.random.default_rng(7)
    # The spread between pairs is far larger than the effect, which only pairing removes.
    baseline = rng.normal(1000.0, 200.0, 12)
    candidate = baseline - 50.0 + rng.normal(0.0, 5.0, 12)

    result = paired_difference_ci(baseline, candidate, seed=3)

    low, high = result["mean_difference_ci"]
    assert low < result["mean_difference"] < high
    assert high - low < 20.0
    assert result["meets_min_pairs"] is True
    relative_low, relative_high = result["relative_change_ci"]
    assert relative_low < result["relative_change"] < relative_high < 0.0


def test_interval_coverage_is_close_to_nominal_at_ten_pairs():
    rng = np.random.default_rng(0)
    trials, covered_difference, covered_relative = 400, 0, 0
    for trial in range(trials):
        baseline = rng.normal(1000.0, 50.0, 10)
        candidate = baseline - 100.0 + rng.normal(0.0, 20.0, 10)
        result = paired_difference_ci(baseline, candidate, seed=trial, resamples=1000)
        low, high = result["mean_difference_ci"]
        covered_difference += low <= -100.0 <= high
        low, high = result["relative_change_ci"]
        covered_relative += low <= -0.1 <= high

    # A percentile interval covers about 0.91 here; the binomial error on 400 trials is 0.011.
    assert covered_difference / trials >= 0.925
    assert covered_relative / trials >= 0.925


def test_same_seed_reproduces_the_interval():
    baseline, candidate = [5.0, 7.0, 6.0, 9.0], [4.0, 7.5, 5.0, 8.0]

    first = paired_difference_ci(baseline, candidate, seed=11)
    second = paired_difference_ci(baseline, candidate, seed=11)

    assert first == second


def test_paired_inputs_are_validated():
    with pytest.raises(ValueError, match="equal-length"):
        paired_difference_ci([1.0, 2.0], [1.0], seed=0)
    with pytest.raises(ValueError, match="at least two pairs"):
        paired_difference_ci([1.0], [2.0], seed=0)


def test_success_rate_resamples_whole_runs():
    result = success_rate_ci([20, 20, 19, 10], [20, 20, 20, 20], seed=5)

    assert result["success_rate"] == pytest.approx(69 / 80)
    low, high = result["success_rate_ci"]
    # One bad run dominates the uncertainty, so the interval is much wider than a
    # per-trial binomial interval (about +/- 0.08) would be.
    assert low <= 0.75 and high >= 0.97
    assert result["runs"] == 4 and result["trials"] == 80


def test_success_rate_inputs_are_validated():
    with pytest.raises(ValueError, match="successes <= trials"):
        success_rate_ci([3], [2], seed=0)
    with pytest.raises(ValueError, match="non-empty"):
        success_rate_ci([], [], seed=0)
