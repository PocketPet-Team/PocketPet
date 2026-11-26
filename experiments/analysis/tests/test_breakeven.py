import json

import numpy as np
import pytest

from pocketpet_analysis import cli
from pocketpet_analysis import schedule as schedules
from pocketpet_analysis.breakeven import break_even
from pocketpet_analysis.stats import line_crossing_ci
from pocketpet_analysis.synthetic import (
    INTERRUPT_IDLE_UA,
    POLLING_UA,
    SWEEP_BREAK_EVEN_PER_H,
    WAKE_S,
    WAKE_UA,
)

DURATION_S = 3600.0
# The candidate saves 12 uA at rest and each trigger costs 3000 uC, so they meet at 14.4/h.
SAVING_UA = 12.0
TRIGGER_UC = 3000.0
BREAK_EVEN_PER_H = SAVING_UA * 3600.0 / TRIGGER_UC


def make_schedules(rates, duration_s=DURATION_S):
    sweep = schedules.sweep(
        "t", rates, pattern="periodic", duration_s=duration_s, min_gap_ms=1000, seed=0
    )
    return {schedule.schedule_id: schedule for schedule in sweep}


def make_summaries(by_id, pairs, *, noise_ua=0.5, seed=0, cost_uc=TRIGGER_UC):
    """Summaries shaped like ``summarize`` output, with the model's mean currents plus noise."""
    rng = np.random.default_rng(seed)
    summaries = []
    for schedule in by_id.values():
        for pair in range(pairs):
            means = {
                "baseline": 20.0,
                "candidate": 20.0 - SAVING_UA + schedule.rate_per_h * cost_uc / 3600.0,
            }
            for role, mean_ua in means.items():
                summaries.append(
                    {
                        "run_id": f"{schedule.schedule_id}-p{pair}-{role}",
                        "rq": "RQ1",
                        "condition": schedule.schedule_id,
                        "workload": schedule.schedule_id,
                        "pair_id": f"p{pair}",
                        "role": role,
                        "variant": "interrupt" if role == "candidate" else "polling",
                        "metadata": {
                            "board_rev": "test",
                            "firmware_sha": "abc1234",
                            "phase": "pilot",
                        },
                        "total": {
                            "duration_s": schedule.duration_ms / 1000.0,
                            "mean_current_ua": mean_ua + rng.normal(0.0, noise_ua),
                        },
                    }
                )
    return summaries


def test_break_even_recovers_the_rate_the_saving_and_the_cost_per_trigger():
    by_id = make_schedules([0.0, 6.0, 12.0, 24.0, 48.0])

    result = break_even(make_summaries(by_id, pairs=10), by_id, seed=1)

    assert result["pairs"] == 50 and result["meets_min_pairs"]
    assert result["baseline_variant"] == "polling"
    assert result["candidate_variant"] == "interrupt"
    for name, truth in (
        ("break_even", BREAK_EVEN_PER_H),
        ("saving_at_zero", SAVING_UA),
        ("charge_per_trigger", TRIGGER_UC),
    ):
        low, high = result[f"{name}_ci"]
        assert low < truth < high
    assert result["break_even_rate_per_h"] == pytest.approx(BREAK_EVEN_PER_H, rel=0.05)
    assert [row["trigger_rate_per_h"] for row in result["rates"]] == [0.0, 6.0, 12.0, 24.0, 48.0]
    assert result["rates"][0]["mean_difference_ua"] == pytest.approx(-SAVING_UA, abs=0.5)
    assert result["warnings"] == []


def test_break_even_outside_the_measured_rates_is_flagged_as_extrapolated():
    by_id = make_schedules([0.0, 2.0, 4.0])

    result = break_even(make_summaries(by_id, pairs=10, noise_ua=0.05), by_id, seed=1)

    assert result["break_even_rate_per_h"] == pytest.approx(BREAK_EVEN_PER_H, rel=0.05)
    assert any("extrapolated" in warning for warning in result["warnings"])
    # Every measured rate is still below break-even, so the candidate is ahead at all of them.
    assert result["rates"][-1]["mean_difference_ua"] < 0.0


def test_no_break_even_is_reported_when_triggers_cost_nothing():
    by_id = make_schedules([0.0, 12.0, 24.0])

    result = break_even(make_summaries(by_id, pairs=10, cost_uc=0.0), by_id, seed=1)

    # The fitted slope is noise around zero, so its interval must reach zero or below.
    assert result["break_even_ci"] is None
    assert result["charge_per_trigger_ci"][0] <= 0.0
    assert any(
        "no break-even rate" in warning or "no bounded interval" in warning
        for warning in result["warnings"]
    )


def test_a_cost_that_grows_with_the_rate_is_flagged_as_off_the_line():
    by_id = make_schedules([0.0, 12.0, 24.0, 48.0])
    summaries = make_summaries(by_id, pairs=10, noise_ua=0.05)
    for summary in summaries:
        if summary["role"] == "candidate":
            rate = by_id[summary["workload"]].rate_per_h
            summary["total"]["mean_current_ua"] += 0.01 * rate**2

    result = break_even(summaries, by_id, seed=1)

    assert any("check that the cost per trigger is constant" in w for w in result["warnings"])


def test_a_run_that_does_not_cover_its_schedule_is_flagged():
    by_id = make_schedules([0.0, 12.0])
    summaries = make_summaries(by_id, pairs=3)
    summaries[0]["total"]["duration_s"] = DURATION_S / 2

    result = break_even(summaries, by_id, seed=1)

    assert any("ran 1800.0 s against a 3600.0 s schedule" in w for w in result["warnings"])


def test_break_even_needs_known_schedules_one_question_and_enough_pairs():
    by_id = make_schedules([0.0, 12.0])
    summaries = make_summaries(by_id, pairs=3)

    with pytest.raises(ValueError, match="not among the schedules given"):
        break_even(summaries, make_schedules([0.0]), seed=1)
    with pytest.raises(ValueError, match="one research question"):
        break_even([s | {"rq": s["workload"]} for s in summaries], by_id, seed=1)
    with pytest.raises(ValueError, match="at least two distinct x values"):
        break_even(make_summaries(make_schedules([12.0]), pairs=3), by_id, seed=1)
    with pytest.raises(ValueError, match="at least two pairs"):
        break_even(make_summaries(by_id, pairs=1), by_id, seed=1)


def test_line_crossing_has_no_point_estimate_when_the_line_falls():
    result = line_crossing_ci([0, 0, 0, 10, 10, 10], [5.0, 5.2, 4.9, 1.0, 1.1, 0.8], seed=0)

    assert result["slope"] < 0.0
    assert result["crossing"] is None and result["crossing_ci"] is None
    assert result["nonpositive_slope_draws"] == 1.0


def test_line_crossing_interval_is_a_point_for_noise_free_data():
    result = line_crossing_ci([0, 0, 10, 10], [-4.0, -4.0, 6.0, 6.0], seed=0)

    assert result["crossing"] == pytest.approx(4.0)
    assert result["crossing_ci"] == pytest.approx([4.0, 4.0])
    assert result["slope_ci"] == pytest.approx([1.0, 1.0])


def test_line_crossing_interval_covers_the_truth_at_about_the_nominal_rate():
    # Five rates with ten pairs each: the smallest design that counts as formal.
    rates = np.repeat([0.0, 6.0, 12.0, 24.0, 48.0], 10)
    rng = np.random.default_rng(11)
    trials, covered = 300, 0
    for trial in range(trials):
        differences = -SAVING_UA + rates * TRIGGER_UC / 3600.0 + rng.normal(0.0, 4.0, rates.size)
        low, high = line_crossing_ci(rates, differences, seed=trial, resamples=1000)["crossing_ci"]
        covered += low <= BREAK_EVEN_PER_H <= high

    # 95% nominal; three standard errors of a 300-trial estimate is about 4 points.
    assert 0.91 <= covered / trials <= 0.99


def test_cli_runs_a_synthetic_sweep_from_schedules_to_break_even(tmp_path, capsys):
    # 12/h over 600 s is two triggers, so each of these rates gives a whole count.
    rates = ["0", "12", "24", "48"]
    sweep_args = ["--rates", *rates, "--duration-s", "600", "--min-gap-ms", "2000", "--seed", "2"]
    assert cli.main(["sweep", str(tmp_path / "schedules"), *sweep_args]) == 0
    schedule_glob = str(tmp_path / "schedules" / "*.json")
    synth = ["synth", str(tmp_path / "runs"), "--schedules", schedule_glob, "--pairs", "3"]
    assert cli.main(synth) == 0
    runs, summaries = str(tmp_path / "runs" / "*.json"), tmp_path / "summaries"
    assert cli.main(["summarize", runs, "--output-dir", str(summaries)]) == 0
    capsys.readouterr()
    assert cli.main(["breakeven", str(summaries / "*.json"), "--schedules", schedule_glob]) == 0
    result = json.loads(capsys.readouterr().out)

    assert SWEEP_BREAK_EVEN_PER_H == (POLLING_UA - INTERRUPT_IDLE_UA) * 3600.0 / (WAKE_UA * WAKE_S)
    low, high = result["break_even_ci"]
    assert low < SWEEP_BREAK_EVEN_PER_H < high
    assert result["break_even_rate_per_h"] == pytest.approx(SWEEP_BREAK_EVEN_PER_H, rel=0.1)
    assert result["charge_per_trigger_uc"] == pytest.approx(WAKE_UA * WAKE_S, rel=0.1)
    assert result["pairs"] == 12 and not result["meets_min_pairs"]
    assert result["board_revs"] == ["synthetic"]
