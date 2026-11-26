import json

import pytest

from pocketpet_analysis import schedule as schedules
from pocketpet_analysis.schedule import Schedule


def generate(**overrides):
    options = {
        "pattern": "random",
        "rate_per_h": 12.0,
        "duration_s": 3600.0,
        "min_gap_ms": 5000,
        "seed": 1,
    }
    return schedules.generate("test", **(options | overrides))


@pytest.mark.parametrize("pattern", schedules.PATTERNS)
@pytest.mark.parametrize("rate", [0.0, 1.0, 12.0, 120.0])
def test_generated_schedule_has_the_exact_rate_and_keeps_its_gaps(pattern, rate):
    schedule = generate(pattern=pattern, rate_per_h=rate)

    assert len(schedule.times_ms) == rate
    assert schedule.rate_per_h == rate
    # The start and end count as neighbours, so no trigger sits at either edge.
    edges = [0, *schedule.times_ms, schedule.duration_ms]
    assert all(later - earlier >= 5000 for earlier, later in zip(edges, edges[1:], strict=False))


def test_random_schedule_is_reproducible_and_depends_on_the_seed():
    assert generate(seed=3) == generate(seed=3)
    assert generate(seed=3).times_ms != generate(seed=4).times_ms


def test_periodic_schedule_is_evenly_spaced():
    schedule = generate(pattern="periodic", rate_per_h=3.0)

    assert schedule.times_ms == (900_000, 1_800_000, 2_700_000)
    assert "seed" not in schedule.source


def test_a_schedule_as_dense_as_the_gap_allows_is_still_generated():
    # 719 triggers and 720 gaps of 5 s fill the hour exactly.
    schedule = generate(rate_per_h=719.0)

    assert schedule.times_ms == tuple(range(5000, 3_600_000, 5000))


def test_generate_rejects_rates_it_cannot_honour():
    with pytest.raises(ValueError, match="2.5 triggers"):
        generate(rate_per_h=5.0, duration_s=1800.0)
    with pytest.raises(ValueError, match="do not fit"):
        generate(rate_per_h=720.0)
    with pytest.raises(ValueError, match="whole number"):
        generate(rate_per_h=-1.0)
    with pytest.raises(ValueError, match="pattern"):
        generate(pattern="bursty")


def test_sweep_names_each_schedule_by_pattern_rate_and_seed():
    sweep = schedules.sweep(
        "rq1", [0.0, 6.0, 12.5], pattern="random", duration_s=7200.0, min_gap_ms=2000, seed=9
    )

    assert [s.schedule_id for s in sweep] == [
        "rq1-random-0ph-s9",
        "rq1-random-6ph-s9",
        "rq1-random-12.5ph-s9",
    ]
    assert [len(s.times_ms) for s in sweep] == [0, 12, 25]
    with pytest.raises(ValueError, match="distinct"):
        schedules.sweep(
            "rq1", [6.0, 6.0], pattern="periodic", duration_s=3600.0, min_gap_ms=2000, seed=0
        )


def test_schedule_survives_a_save_and_load(tmp_path):
    schedule = generate()

    path = schedules.save(schedule, tmp_path / "workloads")

    assert path.name == "test.schedule.json"
    assert schedules.load(path) == schedule
    assert schedules.load_all([path]) == {"test": schedule}
    with pytest.raises(ValueError, match="two schedules are named 'test'"):
        schedules.load_all([path, path])


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema": 2}, "unsupported schedule schema"),
        ({"times_ms": [1000, 500]}, "in order"),
        ({"times_ms": [1000, 1500]}, "at least 1000 ms apart"),
        ({"times_ms": [1000, 60_000]}, "inside the run"),
        ({"times_ms": [1000.5]}, "whole milliseconds"),
        ({"duration_ms": 0}, "must be positive"),
        ({"schedule_id": ""}, "non-empty string"),
    ],
)
def test_load_rejects_a_schedule_the_rig_could_not_replay(tmp_path, change, message):
    raw = Schedule("ok", 60_000, 1000, (1000, 3000), {"type": "generated"}).to_json() | change
    path = tmp_path / "bad.schedule.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match=f"bad.schedule.json: .*{message}"):
        schedules.load(path)


def test_recording_becomes_a_schedule_and_close_triggers_are_dropped(tmp_path):
    recording = tmp_path / "bag-walk.csv"
    # A CRLF export with a byte-order mark and an extra column, as a spreadsheet writes it.
    recording.write_bytes(
        "\ufefftime_ms,axis\r\n1000.4,x\r\n1300,y\r\n2999,x\r\n3000,z\r\n9000,x\r\n".encode()
    )

    schedule = schedules.from_recording(
        recording, schedule_id="bag-walk", duration_s=10.0, min_gap_ms=2000
    )

    # 1300 and 2999 fall within 2 s of the trigger kept at 1000; 3000 does not.
    assert schedule.times_ms == (1000, 3000, 9000)
    assert schedule.rate_per_h == pytest.approx(3 * 360.0)
    assert schedule.source["file"] == "bag-walk.csv"
    assert schedule.source["recorded_triggers"] == 5
    assert schedule.source["dropped_triggers"] == 2
    assert len(schedule.source["sha256"]) == 64


def test_recording_must_be_ordered_labelled_and_inside_its_duration(tmp_path):
    def build(text):
        path = tmp_path / "recording.csv"
        path.write_text(text, encoding="utf-8")
        return schedules.from_recording(path, schedule_id="r", duration_s=10.0, min_gap_ms=100)

    with pytest.raises(ValueError, match="no time_ms column"):
        build("timestamp\n1000\n")
    with pytest.raises(ValueError, match="not in time order"):
        build("time_ms\n2000\n1000\n")
    with pytest.raises(ValueError, match="inside the run"):
        build("time_ms\n1000\n10000\n")
    assert build("time_ms\n").times_ms == ()
