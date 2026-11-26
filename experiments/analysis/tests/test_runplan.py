import csv
import json

import numpy as np
import pytest

from pocketpet_analysis import cli
from pocketpet_analysis import schedule as schedules
from pocketpet_analysis.manifest import load_manifest
from pocketpet_analysis.runplan import load_definition, planned_runs, write_run_files
from pocketpet_analysis.synthetic import SWEEP_BREAK_EVEN_PER_H, sweep_run, write_capture

CONDITIONS = [
    {"condition": "wake-0ph", "workload": "sweep-periodic-0ph"},
    {"condition": "wake-6ph", "workload": "sweep-periodic-6ph"},
    {"condition": "wake-12ph", "workload": "sweep-periodic-12ph"},
]
MARKERS = {"state_channels": [0, 1], "states": {"0": "idle"}, "events": {"2": "button"}}


def write_definition(tmp_path, **changes):
    raw = {
        "rq": "RQ1",
        "pairs": 4,
        "seed": 11,
        "baseline": {"variant": "polling"},
        "candidate": {"variant": "interrupt"},
        "conditions": CONDITIONS,
        "metadata": {
            "board_rev": "nrf52840-dk",
            "board_id": "dk-01",
            "firmware_sha": "abc1234",
            "supply_v": 3.7,
            "phone_model": "none",
            "os_version": "none",
            "phase": "pilot",
        },
        "markers": MARKERS,
    } | changes
    path = tmp_path / "rq1.plan.json"
    path.write_text(json.dumps({k: v for k, v in raw.items() if v is not None}), encoding="utf-8")
    return path


def definition(tmp_path, **changes):
    return load_definition(write_definition(tmp_path, **changes))


def test_every_pair_of_every_condition_is_planned_once_with_adjacent_roles(tmp_path):
    runs = planned_runs(definition(tmp_path))

    assert [run.order for run in runs] == list(range(1, 25))
    assert len({run.run_id for run in runs}) == 24
    assert runs[0].run_id.startswith("rq1-wake-") and runs[0].run_id.endswith(runs[0].role)
    for first, second in zip(runs[::2], runs[1::2], strict=True):
        assert (first.condition, first.pair_id) == (second.condition, second.pair_id)
        assert {first.role, second.role} == {"baseline", "candidate"}
    planned = {(run.condition, run.pair_id) for run in runs}
    assert planned == {(c["condition"], f"p{pair:02d}") for c in CONDITIONS for pair in range(1, 5)}


def test_rounds_hold_each_condition_once_and_grouped_keeps_the_listed_order(tmp_path):
    names = [condition["condition"] for condition in CONDITIONS]

    rounds = [run.condition for run in planned_runs(definition(tmp_path))[::2]]
    for start in range(0, 12, 3):
        assert sorted(rounds[start : start + 3]) == sorted(names)
    # Four rounds in the listed order every time would mean nothing was shuffled.
    assert rounds != names * 4

    grouped = [run.condition for run in planned_runs(definition(tmp_path, order="grouped"))[::2]]
    assert grouped == [name for name in names for _ in range(4)]


def test_plan_is_reproducible_and_role_order_is_random(tmp_path):
    runs = planned_runs(definition(tmp_path, pairs=20))

    assert runs == planned_runs(definition(tmp_path, pairs=20))
    assert runs != planned_runs(definition(tmp_path, pairs=20, seed=12))
    baseline_first = sum(run.role == "baseline" for run in runs[::2])
    assert 15 <= baseline_first <= 45


def test_skeletons_carry_the_plan_and_become_valid_once_temperature_is_recorded(tmp_path):
    paths = write_run_files(definition(tmp_path), tmp_path / "runs")

    plan_path, *manifest_paths = paths
    with plan_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["order"] for row in rows] == [str(n) for n in range(1, 25)]
    assert [f"{row['run_id']}.json" for row in rows] == [path.name for path in manifest_paths]
    assert {row["variant"] for row in rows if row["role"] == "candidate"} == {"interrupt"}
    assert {row["duration_s"] for row in rows} == {""}

    first = manifest_paths[0]
    with pytest.raises(ValueError, match="ambient_temp_c must be a number"):
        load_manifest(first)
    raw = json.loads(first.read_text(encoding="utf-8"))
    raw["metadata"]["ambient_temp_c"] = 23.5
    first.write_text(json.dumps(raw), encoding="utf-8")

    manifest = load_manifest(first)
    assert manifest.capture == first.with_suffix(".csv")
    assert manifest.pairing == {
        "rq": "RQ1",
        "condition": rows[0]["condition"],
        "workload": rows[0]["workload"],
        "pair_id": rows[0]["pair_id"],
        "role": rows[0]["role"],
        "variant": rows[0]["variant"],
    }
    assert manifest.metadata["firmware_sha"] == "abc1234"
    assert manifest.metadata["board_id"] == "dk-01"
    assert manifest.markers.events == {2: "button"}


def test_each_role_can_name_its_own_firmware_commit(tmp_path):
    plan = definition(tmp_path, candidate={"variant": "interrupt", "firmware_sha": "def5678"})
    write_run_files(plan, tmp_path / "runs")

    shas = {}
    for path in (tmp_path / "runs").glob("*.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        shas.setdefault(raw["role"], set()).add(raw["metadata"]["firmware_sha"])
    assert shas == {"baseline": {"abc1234"}, "candidate": {"def5678"}}


def test_existing_files_are_never_replaced(tmp_path):
    plan = definition(tmp_path)
    out_dir = tmp_path / "runs"
    write_run_files(plan, out_dir)
    before = {path.name: path.read_bytes() for path in out_dir.iterdir()}

    with pytest.raises(ValueError, match="already has 25 of these files, starting with plan.csv"):
        write_run_files(plan, out_dir)

    # A plan that only partly overlaps must not write its other files either.
    (out_dir / "plan.csv").unlink()
    del before["plan.csv"]
    with pytest.raises(ValueError, match="already has 24 of these files"):
        write_run_files(plan, out_dir)
    assert {path.name: path.read_bytes() for path in out_dir.iterdir()} == before


def test_schedules_are_checked_and_give_each_run_its_duration(tmp_path):
    sweep = schedules.sweep(
        "sweep", [0.0, 6.0, 12.0], pattern="periodic", duration_s=1800.0, min_gap_ms=1000, seed=0
    )
    for schedule in sweep:
        schedules.save(schedule, tmp_path / "workloads")

    plan = definition(tmp_path, schedules=["workloads/*.schedule.json"])
    plan_path = write_run_files(plan, tmp_path / "runs")[0]
    with plan_path.open(encoding="utf-8", newline="") as handle:
        assert {row["duration_s"] for row in csv.DictReader(handle)} == {"1800.0"}

    renamed = [dict(CONDITIONS[0], workload="sweep-periodic-9ph"), *CONDITIONS[1:]]
    with pytest.raises(ValueError, match=r"no schedule file defines the workloads \['sweep-p"):
        definition(tmp_path, schedules=["workloads/*.schedule.json"], conditions=renamed)


def test_markers_can_come_from_a_file_next_to_the_definition(tmp_path):
    (tmp_path / "markers.json").write_text(json.dumps(MARKERS), encoding="utf-8")

    plan = definition(tmp_path, markers=None, markers_file="markers.json")
    assert plan.markers == MARKERS
    assert definition(tmp_path, markers=None).markers is None
    with pytest.raises(ValueError, match="markers or markers_file, not both"):
        definition(tmp_path, markers_file="markers.json")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"pairs": 0}, "pairs must be a positive whole number"),
        ({"pairs": 2.5}, "pairs must be a positive whole number"),
        ({"seed": -1}, "seed must be a non-negative whole number"),
        ({"order": "shuffled"}, "order must be one of"),
        ({"rq": "RQ 1"}, "rq must use only letters"),
        ({"conditions": []}, "at least one condition"),
        ({"conditions": [CONDITIONS[0], CONDITIONS[0]]}, "condition names must be distinct"),
        ({"conditions": [{"condition": "a/b", "workload": "w"}]}, "condition must use only"),
        ({"conditions": [{"condition": "a", "workload": ""}]}, "needs a workload name"),
        ({"candidate": {"variant": "polling"}}, "different variant names"),
        ({"baseline": {"variant": "polling", "firmware_sha": "XYZ"}}, "firmware_sha must be"),
        ({"markers": {"state_channels": [9]}}, "marker channels must be integers"),
    ],
)
def test_definition_errors_name_the_file_and_the_problem(tmp_path, changes, message):
    with pytest.raises(ValueError, match=f"rq1.plan.json: .*{message}"):
        definition(tmp_path, **changes)


def test_metadata_must_be_complete_fixed_and_large_enough_for_a_formal_plan(tmp_path):
    base = json.loads(write_definition(tmp_path).read_text(encoding="utf-8"))["metadata"]

    with pytest.raises(ValueError, match="measured per run; leave it out"):
        definition(tmp_path, metadata=base | {"ambient_temp_c": 23.0})
    with pytest.raises(ValueError, match=r"metadata is missing \['supply_v'\]"):
        definition(tmp_path, metadata={k: v for k, v in base.items() if k != "supply_v"})
    with pytest.raises(ValueError, match="formal-frozen plan needs at least 10 pairs"):
        definition(tmp_path, metadata=base | {"phase": "formal-frozen"})
    assert definition(tmp_path, pairs=10, metadata=base | {"phase": "formal-frozen"}).pairs == 10


def test_cli_prepare_writes_the_files_and_reports_a_second_attempt(tmp_path, capsys):
    path = write_definition(tmp_path)

    assert cli.main(["prepare", str(path), str(tmp_path / "runs")]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert len(printed) == 25 and printed[0].endswith("plan.csv")

    assert cli.main(["prepare", str(path), str(tmp_path / "runs")]) == 1
    assert "already has 25 of these files" in capsys.readouterr().err


def test_prepared_runs_go_through_summarize_and_breakeven(tmp_path, capsys):
    # 12/h over 600 s is two triggers, so each of these rates gives a whole count.
    rates = [0.0, 12.0, 24.0, 48.0]
    sweep = schedules.sweep(
        "sweep", rates, pattern="random", duration_s=600.0, min_gap_ms=2000, seed=3
    )
    for schedule in sweep:
        schedules.save(schedule, tmp_path / "workloads")
    conditions = [
        {"condition": f"wake-{schedule.rate_per_h:g}ph", "workload": schedule.schedule_id}
        for schedule in sweep
    ]
    path = write_definition(
        tmp_path, pairs=3, conditions=conditions, schedules=["workloads/*.schedule.json"]
    )
    runs = tmp_path / "runs"
    assert cli.main(["prepare", str(path), str(runs)]) == 0

    # Stand in for the bench: record a capture and the temperature for every planned run.
    by_id = {schedule.schedule_id: schedule for schedule in sweep}
    rng = np.random.default_rng(5)
    for manifest_path in sorted(runs.glob("*.json")):
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        samples = sweep_run(rng, by_id[raw["workload"]], interrupt=raw["role"] == "candidate")
        write_capture(runs / raw["capture"], *samples)
        raw["metadata"]["ambient_temp_c"] = 23.5
        # The synthetic interrupt run marks its wakes on D0.
        raw["markers"] = {"events": {"0": "wake"}}
        manifest_path.write_text(json.dumps(raw), encoding="utf-8")

    summaries = tmp_path / "summaries"
    assert cli.main(["summarize", str(runs / "*.json"), "--output-dir", str(summaries)]) == 0
    schedule_glob = str(tmp_path / "workloads" / "*.json")
    capsys.readouterr()
    assert cli.main(["breakeven", str(summaries / "*.json"), "--schedules", schedule_glob]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["rq"] == "RQ1" and result["pairs"] == 12
    assert result["baseline_variant"] == "polling"
    assert result["baseline_firmware_shas"] == ["abc1234"]
    assert [row["trigger_rate_per_h"] for row in result["rates"]] == rates
    low, high = result["break_even_ci"]
    assert low < SWEEP_BREAK_EVEN_PER_H < high
    assert result["warnings"] == []
