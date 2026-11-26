import copy
import json

import pytest

from pocketpet_analysis import cli
from pocketpet_analysis.power import mixed_day


def dump(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


@pytest.fixture
def profile(tmp_path):
    # Four one-second samples: quiet, transfer, transfer + button, transfer.
    raw = {
        "capture": "test.csv",
        "run_id": "profile",
        "sample_period_s": 1,
        "metadata": {
            "board_rev": "synthetic",
            "board_id": "sim",
            "firmware_sha": "0000000",
            "supply_v": 3.3,
            "phone_model": "none",
            "os_version": "none",
            "ambient_temp_c": 20,
            "phase": "pilot",
        },
        "markers": {"events": {"0": "transfer", "1": "button"}},
    }
    (tmp_path / "test.csv").write_text(
        "Timestamp(ms),Current(uA),D0-D7\n0,10,00000000\n1000,30,10000000\n"
        "2000,90,11000000\n3000,50,10000000\n4000,10,00000000\n"
    )
    manifest = tmp_path / "profile.json"
    dump(manifest, raw)
    return raw, cli.summarize(manifest)


def workload():
    return {
        "workload": "mixed-sim",
        "state_hours": {"run": 24},
        "event_segments": [
            {"state": "run", "events": ["transfer"], "count": 8},
            {"state": "run", "events": ["button", "transfer"], "count": 2},
        ],
    }


def test_mixed_day_cli_and_full_day_capture(tmp_path, profile, capsys):
    raw, summary = profile
    path = dump(tmp_path / "p.summary.json", summary)
    definition = dump(tmp_path / "workload.json", workload())
    # A separate, low-rate synthetic export with exactly one day's integrated charge.
    raw.update(
        run_id="whole-day", capture="day.csv", markers={}, workload="mixed-sim", sample_period_s=60
    )
    (tmp_path / "day.csv").write_text(
        "Timestamp(ms),Current(uA)\n" + "\n".join(f"{i * 60000},20" for i in range(1440))
    )
    day = tmp_path / "day.summary.json"
    assert cli.main(["summarize", dump(tmp_path / "day.json", raw), "-o", str(day)]) == 0
    assert (
        cli.main(
            ["mixed-day", path, definition, "--capacity-mah", "20", "--measured-day", str(day)]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    # Each transfer-only segment averages (20 + 40) / 2 uC above background.
    expected = 0.24 + (8 * 30 + 2 * 80) / 3.6e6
    assert report["modeled_daily_mah"] == pytest.approx(expected)
    assert report["within_modeled_budget"]
    assert report["measured_24h"]["charge_mah"] == pytest.approx(0.48)
    assert report["measured_24h"]["within_budget"] is False


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda w: w["state_hours"].update(run=23), "total 24"),
        (lambda w: w["event_segments"][-1].update(count=-1), "integer count"),
        (lambda w: w["event_segments"].append(w["event_segments"][0]), "duplicate"),
        (lambda w: w["event_segments"][-1].update(count=90000), "available time"),
    ],
)
def test_invalid_workload(profile, edit, message):
    _, summary = profile
    w = workload()
    edit(w)
    with pytest.raises(ValueError, match=message):
        mixed_day(summary, w, 100, None)


def test_budget_short_or_unmatched_day(profile):
    _, summary = profile
    day = copy.deepcopy(summary)
    day["workload"] = "mixed-sim"
    with pytest.raises(ValueError, match="continuous 24-hour"):
        mixed_day(summary, workload(), 90, day)
    # A misdeclared sample period can yield a full day of integrated samples in a short export.
    day["total"]["duration_s"] = 86400
    with pytest.raises(ValueError, match="continuous 24-hour"):
        mixed_day(summary, workload(), 90, day)
    day["metadata"]["board_id"] = "another"
    with pytest.raises(ValueError, match="match the workload"):
        mixed_day(summary, workload(), 90, day)


@pytest.mark.parametrize(
    ("reference", "passed"),
    [
        ({"reference_ua": 100}, True),
        ({"resistance_ohm": 33000}, True),
        ({"reference_ua": 90}, False),
    ],
)
def test_precision_load(tmp_path, profile, reference, passed):
    raw, _ = profile
    raw.update(markers={}, calibration=reference | {"tolerance_pct": 2})
    (tmp_path / "test.csv").write_text("Timestamp(ms),Current(uA)\n0,100\n1000,104\n")
    path = tmp_path / "cal.json"
    dump(path, raw)
    report = cli.summarize(path)["calibration"]
    assert report["measured_ua"] == 102 and report["within_tolerance"] is passed
    if passed:
        assert report["expected_ua"] == 100 and report["error_pct"] == 2
    (tmp_path / "test.csv").write_text("Timestamp(ms),Current(uA)\n0,100\n2000,104\n")
    with pytest.raises(ValueError, match="missing samples"):
        cli.summarize(path)
