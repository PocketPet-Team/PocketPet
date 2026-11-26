import copy
import json

import pytest

from pocketpet_analysis import cli
from pocketpet_analysis.compare import compare_runs
from pocketpet_analysis.manifest import load_manifest
from pocketpet_analysis.synthetic import (
    BACKGROUND_UA,
    CANDIDATE_ADVERTISING_UA,
    EVENT_UA,
    write_synthetic_pairs,
)


@pytest.fixture(scope="module")
def summaries(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("synthetic")
    manifests = write_synthetic_pairs(out_dir, pairs=10, seed=4, duration_s=4.0)
    return [cli.summarize(manifest) for manifest in manifests]


def test_summary_recovers_the_synthetic_model(summaries):
    summary = summaries[0]

    assert summary["metadata"]["board_rev"] == "synthetic"
    assert "Not a measurement" in summary["notes"]
    assert summary["capture"]["file"] == "synthetic-p01-baseline.csv"
    assert len(summary["capture"]["sha256"]) == 64

    backgrounds = {row["state"]: row["background_ua"] for row in summary["states"]}
    assert backgrounds == pytest.approx(BACKGROUND_UA, abs=0.5)
    assert summary["event_counts"] == {"button": 2, "find": 1}
    both = next(row for row in summary["events"] if row["events"] == ["button", "find"])
    # 1% of the 4 s run has both events active.
    assert both["incremental_charge_uc"] == pytest.approx(sum(EVENT_UA.values()) * 0.04, rel=0.01)


def test_compare_finds_the_advertising_saving(summaries):
    [comparison] = compare_runs(summaries, seed=0)

    # The candidate advertises at a lower current for the first quarter of each run.
    saving_uc = (BACKGROUND_UA["advertising"] - CANDIDATE_ADVERTISING_UA) * 1.0
    low, high = comparison["mean_difference_ci"]
    assert low < -saving_uc < high
    assert comparison["pairs"] == 10 and comparison["meets_min_pairs"]
    assert comparison["phase"] == "pilot"
    assert comparison["baseline_variant"] == "reference"
    assert comparison["candidate_variant"] == "slower-advertising"
    assert comparison["board_revs"] == ["synthetic"]
    assert comparison["warnings"] == []


def test_compare_rejects_unmatched_and_incomplete_pairs(summaries):
    unmatched = copy.deepcopy(summaries)
    unmatched[1]["metadata"]["supply_v"] = 3.3
    with pytest.raises(ValueError, match="not matched on .*supply_v"):
        compare_runs(unmatched, seed=0)

    with pytest.raises(ValueError, match="needs a baseline and a candidate"):
        compare_runs(summaries[:-1], seed=0)

    with pytest.raises(ValueError, match="two baseline runs"):
        compare_runs([*summaries, summaries[0]], seed=0)

    unlabelled = copy.deepcopy(summaries[0])
    del unlabelled["pair_id"]
    with pytest.raises(ValueError, match="missing pairing fields"):
        compare_runs([unlabelled], seed=0)


def test_compare_reports_formal_phase_only_when_every_run_is_frozen(summaries):
    frozen = copy.deepcopy(summaries)
    for summary in frozen:
        summary["metadata"]["phase"] = "formal-frozen"
    assert compare_runs(frozen, seed=0)[0]["phase"] == "formal-frozen"

    frozen[3]["metadata"]["phase"] = "pilot"
    assert compare_runs(frozen, seed=0)[0]["phase"] == "pilot"


def test_manifest_validation(tmp_path):
    manifests = write_synthetic_pairs(tmp_path, pairs=1, seed=0, duration_s=0.1)
    valid = json.loads(manifests[0].read_text(encoding="utf-8"))

    def load(change):
        raw = copy.deepcopy(valid)
        change(raw)
        path = tmp_path / "edited.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return load_manifest(path)

    with pytest.raises(ValueError, match="phase"):
        load(lambda raw: raw["metadata"].update(phase="formal"))
    with pytest.raises(ValueError, match="firmware_sha"):
        load(lambda raw: raw["metadata"].update(firmware_sha="unknown"))
    with pytest.raises(ValueError, match="missing"):
        load(lambda raw: raw["metadata"].pop("ambient_temp_c"))
    with pytest.raises(ValueError, match="one state bit or one event"):
        load(lambda raw: raw["markers"].update(events={"1": "button"}))
    with pytest.raises(ValueError, match="does not fit"):
        load(lambda raw: raw["markers"]["states"].update({"4": "extra"}))
    with pytest.raises(ValueError, match="role"):
        load(lambda raw: raw.update(role="control"))


def test_response_rate_counts_timeouts_as_failures(tmp_path):
    trials = tmp_path / "trials.csv"
    trials.write_text("run_id,latency_ms\nr1,90\nr1,151\nr1,\nr2,150\nr2,20\n", encoding="utf-8")

    result = cli.response_rate(trials, threshold_ms=150.0, target=0.95, seed=0, resamples=200)

    assert result["trials"] == 5 and result["runs"] == 2
    assert result["successes"] == 3
    assert result["timeouts"] == 1
    assert result["meets_target"] is False


def test_plan_is_reproducible_and_complete():
    plan = cli.randomized_plan(pairs=10, seed=9)

    assert plan == cli.randomized_plan(pairs=10, seed=9)
    assert len(plan) == 20
    for pair in range(10):
        first, second = plan[2 * pair], plan[2 * pair + 1]
        assert first[0] == second[0] and (first[1], second[1]) == (1, 2)
        assert {first[2], second[2]} == {"baseline", "candidate"}
    assert {row[2] for row in plan if row[1] == 1} == {"baseline", "candidate"}


def test_budget_matches_the_nominal_reference():
    result = cli.budget(100.0, 60.0, None)
    assert result["daily_budget_mah"] == pytest.approx(1.667, abs=1e-3)
    assert result["budget_current_ua"] == pytest.approx(69.4, abs=0.05)

    summary = {"run_id": "r", "total": {"mean_current_ua": 34.72, "duration_s": 3600.0}}
    projected = cli.budget(100.0, 60.0, summary)
    assert projected["covers_24h"] is False
    assert projected["budget_fraction"] == pytest.approx(0.5, abs=1e-3)


def test_main_reports_errors_without_a_traceback(tmp_path, capsys):
    assert cli.main(["summarize", str(tmp_path / "missing.json")]) == 1
    assert "error:" in capsys.readouterr().err

    assert cli.main(["budget", "--capacity-mah", "100"]) == 0
    assert json.loads(capsys.readouterr().out)["target_days"] == 60.0


def test_main_summarizes_and_compares_through_wildcards(tmp_path, capsys):
    write_synthetic_pairs(tmp_path, pairs=2, seed=0, duration_s=0.5)
    summaries = tmp_path / "summaries"

    assert cli.main(["summarize", str(tmp_path / "*.json")]) == 1
    assert "--output-dir" in capsys.readouterr().err
    assert cli.main(["summarize", str(tmp_path / "*.json"), "--output-dir", str(summaries)]) == 0
    assert len(list(summaries.glob("*.summary.json"))) == 4

    assert cli.main(["compare", str(summaries / "*.json"), "--resamples", "200"]) == 0
    [comparison] = json.loads(capsys.readouterr().out)
    assert comparison["pairs"] == 2 and comparison["meets_min_pairs"] is False
