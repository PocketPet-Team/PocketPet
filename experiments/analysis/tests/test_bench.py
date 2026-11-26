import json
from pathlib import Path

import pytest

from pocketpet_analysis import cli
from pocketpet_analysis.stats import paired_difference_ci


def save(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def bench(tmp_path):
    markers = Path(__file__).resolve().parents[3] / "firmware/app/ppk2-markers.json"
    rows = ["Timestamp(ms),Current(uA),D0-D7"]
    for t in range(4001):
        state = 3
        if 100 <= t < 200 or 1050 <= t < 2000:
            state = 1
        if 200 <= t < 300:
            state = 2
        transfer = 350 <= t < 370 or 380 <= t < 390
        haptic = 355 <= t < 360
        button = 500 <= t < 650
        ua = {1: 20, 2: 5, 3: 10}[state] + transfer * 100 + haptic * 200 + button * 30
        mask = state | (button << 2) | (haptic << 3) | (transfer << 4)
        levels = f"{mask:08b}"[::-1]
        rows.append(f"{t},{ua},{levels}")
    (tmp_path / "trace.csv").write_text("\n".join(rows), encoding="utf-8")
    manifest = {
        "capture": "trace.csv",
        "run_id": "sim",
        "sample_period_s": 0.001,
        "markers": json.loads(markers.read_text()),
        "metadata": {
            "board_rev": "synthetic",
            "firmware_sha": "abcdef0",
            "phase": "pilot",
            "phone_model": "sim",
            "os_version": "sim",
            "supply_v": 3.7,
            "ambient_temp_c": 20,
        },
        "observations": {
            "rq3": {
                "timeout_ms": 100,
                "trials": [
                    {"depart_ms": 90.5, "return_ms": 250.5},
                    {"depart_ms": 1040, "return_ms": 1250},
                ],
            },
            "rq4": {
                "freshness_limit_ms": 50,
                "updates": [
                    {"due_ms": 320, "received_ms": 371, "transfer_index": 1},
                    {"due_ms": 321, "received_ms": 371, "transfer_index": 1},
                    {"due_ms": 400, "received_ms": None},
                ],
            },
            "responses": {
                "source": "firmware-proxy",
                "trials": [
                    {
                        "kind": "button",
                        "request_ms": {"marker": "button", "index": 1, "edge": "rise"},
                        "response_ms": {"marker": "button", "index": 1, "edge": "fall"},
                    },
                    {
                        "kind": "find",
                        "request_ms": 345,
                        "response_ms": {"marker": "haptic", "index": 1, "edge": "rise"},
                    },
                    {"kind": "find", "request_ms": 400, "response_ms": None},
                ],
            },
        },
    }
    return tmp_path, manifest


@pytest.mark.parametrize("chunk", [1, 355, 5000])
def test_charge_windows_onsets_and_chunk_boundaries(bench, chunk):
    root, raw = bench
    s = cli.summarize(save(root / "run.json", raw), chunk_rows=chunk)
    first, second = s["rq3"]["trials"]
    assert first["apart_charge_uc"] == pytest.approx((9.5 * 10 + 100 * 20 + 50.5 * 5) / 1000)
    assert first["state_at_return"] == "adv_slow"
    assert first["recovery_ms"] == 49.5 and second["recovery_ms"] is None
    assert s["rq3"]["timeouts"] == 1 and s["rq3"]["mean_recovery_ms"] == 49.5
    rq4 = s["rq4"]
    assert rq4["transfer_count"] == 2
    assert [p["overlap"] for p in rq4["pulses"]] == [True, False]
    assert [p["incremental_charge_uc"] for p in rq4["pulses"]] == pytest.approx([3, 1])
    assert rq4["mean_isolated_incremental_uc"] == pytest.approx(1)
    assert rq4["max_delivered_age_ms"] == 51 and rq4["freshness_failures"] == 2
    assert rq4["undelivered"] == 1 and rq4["max_observed_hold_ms"] == 30
    assert s["responses"]["by_kind"]["button"]["latencies_ms"] == [150]
    assert s["responses"]["by_kind"]["find"]["latencies_ms"] == [10, None]


def test_cli_compare_and_response_criteria(bench, capsys):
    root, raw = bench
    raw.update(rq="RQ3", workload="bench", condition="after-switch")
    outputs = []
    for i in range(2):
        for role in ("baseline", "candidate"):
            name = f"{role}-{i}"
            raw.update(role=role, variant=role, run_id=name, pair_id=str(i))
            file = root / f"{name}.summary.json"
            assert cli.main(["summarize", str(save(root / "run.json", raw)), "-o", str(file)]) == 0
            outputs.append(str(file))
    for metric in (
        "rq3.apart_charge_uc",
        "rq3.timeouts",
        "rq4.transfer_count",
        "rq4.mean_isolated_incremental_uc",
        "rq4.max_delivered_age_ms",
    ):
        assert cli.main(["compare", *outputs, "--metric", metric]) == 0
        [report] = json.loads(capsys.readouterr().out)
        assert report["mean_difference_ci"] == [0, 0] and report["pairs"] == 2
    assert cli.main(["response-criteria", *outputs]) == 0
    reports = json.loads(capsys.readouterr().out)
    assert len(reports) == 4
    find = next(r for r in reports if r["kind"] == "find")
    assert find["runs"] == 2 and find["trials"] == 4 and find["timeouts"] == 2
    assert find["success_rate_ci"] == [0.5, 0.5] and find["physical_target_met"] is None
    assert cli.main(["response-criteria", outputs[0], outputs[0]]) == 1
    assert "duplicate run" in capsys.readouterr().err


def test_physical_response_thresholds(bench, capsys):
    root, raw = bench
    raw["observations"] = {
        "responses": {
            "source": "physical",
            "trials": [
                {"kind": "find", "request_ms": 320, "response_ms": 2320},
                {"kind": "find", "request_ms": 340, "response_ms": 2340.1},
                *[
                    {"kind": "button", "request_ms": t * 160, "response_ms": t * 160 + 150}
                    for t in range(19)
                ],
                {"kind": "button", "request_ms": 3200, "response_ms": None},
            ],
        }
    }
    out = root / "summary.json"
    assert cli.main(["summarize", str(save(root / "r.json", raw)), "-o", str(out)]) == 0
    assert cli.main(["response-criteria", str(out)]) == 0
    find, button = json.loads(capsys.readouterr().out)
    assert find["successes"] == 1 and find["physical_target_met"] is False
    assert button["success_rate"] == 0.95 and button["physical_target_met"] is True


@pytest.mark.parametrize(
    ("section", "change", "message"),
    [
        (
            "rq3",
            {
                "timeout_ms": 5000,
                "trials": [{"depart_ms": 1040, "return_ms": 1999}],
            },
            None,
        ),
        ("rq3", {"trials": [{"depart_ms": 91, "return_ms": 310}]}, "before the recorded"),
        ("rq3", {"trials": [{"depart_ms": 0, "return_ms": 60}]}, "observed loss"),
        (
            "responses",
            {"trials": [{"kind": "find", "request_ms": 120, "response_ms": None}]},
            "established link",
        ),
        (
            "responses",
            {"trials": [{"kind": "button", "request_ms": 3999, "response_ms": None}]},
            "ends before",
        ),
        ("responses", {"source": "physical"}, "finite number"),
        ("rq4", {"updates": [{"due_ms": 4000, "received_ms": None}]}, "ends before"),
        (
            "rq4",
            {"updates": [{"due_ms": 400, "received_ms": 410, "transfer_index": 1}]},
            "transfer start",
        ),
    ],
)
def test_observation_bounds(bench, section, change, message):
    root, raw = bench
    block = raw["observations"][section] | change
    raw["observations"] = {section: block}
    path = save(root / "invalid.json", raw)
    if message is None:
        assert cli.summarize(path)["rq3"]["trials"][0]["recovery_ms"] == 1
    else:
        with pytest.raises(ValueError, match=message):
            cli.summarize(path)


def test_truncated_capture_and_ambiguous_markers(bench):
    root, raw = bench
    path = save(root / "run.json", raw)
    capture = root / "trace.csv"
    rows = capture.read_text().splitlines()
    capture.write_text("\n".join(rows[:1301]))
    with pytest.raises(ValueError, match="reconnection timeout"):
        cli.summarize(path)
    capture.write_text("\n".join(rows[:19] + rows[20:]))
    with pytest.raises(ValueError, match="continuous"):
        cli.summarize(path)
    rows[120] = rows[120][:-8] + "X0000000"
    capture.write_text("\n".join(rows))
    with pytest.raises(ValueError, match="resolved levels"):
        cli.summarize(path)


def test_all_zero_baseline_metric_keeps_absolute_ci():
    result = paired_difference_ci([0, 0], [1, 1], seed=0)
    assert result["relative_change"] is None and result["relative_change_ci"] is None
    assert result["mean_difference_ci"] == [1, 1]


def test_matched_policy_changes_are_visible_in_the_report(bench):
    root, raw = bench
    raw.update(rq="RQ3", condition="mixed-returns", workload="bench")
    rows = (root / "trace.csv").read_text().splitlines()
    # Model a candidate that advertises at lower current, reconnects during the
    # second deadline, and coalesces the second notification into the first.
    for i in range(1, len(rows)):
        stamp, ua, bits = rows[i].split(",")
        t = int(stamp)
        if 1300 <= t < 2000:
            ua, bits = "10", "11" + bits[2:]
        elif bits.startswith("10"):
            ua = str(int(ua) - 5)
        if 380 <= t < 390:
            ua, bits = "10", "11000000"
        rows[i] = ",".join([stamp, ua, bits])
    (root / "batched.csv").write_text("\n".join(rows))
    summaries = []
    for p in ("p1", "p2"):
        for role, capture in (("baseline", "trace.csv"), ("candidate", "batched.csv")):
            raw.update(pair_id=p, role=role, variant=role, run_id=f"{p}-{role}", capture=capture)
            summaries.append(cli.summarize(save(root / "run.json", raw)))
    for metric, expected in [
        ("rq3.apart_charge_uc", -1.5),
        ("rq3.timeouts", -1),
        ("rq4.transfer_count", -1),
        ("rq4.window_incremental_charge_uc", -1),
    ]:
        [report] = cli.compare_runs(summaries, metric=metric, seed=0)
        assert report["mean_difference"] == pytest.approx(expected)


def test_reconnection_ignores_uncertain_unrelated_event_and_checks_controls(bench):
    root, raw = bench
    raw["observations"] = {"rq3": raw["observations"]["rq3"]}
    # The PPK2 saw a partial button pulse. Both state bits remain resolved.
    cap = root / raw["capture"]
    rows = cap.read_text().splitlines()
    rows[10] = rows[10][:-6] + "X00000"
    cap.write_text("\n".join(rows))
    raw.update(
        rq="RQ3",
        condition="return",
        workload="matched",
        role="baseline",
        pair_id="p1",
        variant="fixed",
    )
    raw["metadata"]["tx_power_dbm"] = 0
    baseline = cli.summarize(save(root / "r.json", raw))
    candidate = baseline | {
        "role": "candidate",
        "metadata": baseline["metadata"] | {"tx_power_dbm": 4},
    }
    with pytest.raises(ValueError, match="not matched on .*tx_power_dbm"):
        cli.compare_runs([baseline, candidate], metric="rq3.apart_charge_uc", seed=0)
