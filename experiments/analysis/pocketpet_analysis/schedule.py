"""Trigger schedules for the bench replay rig: when to fire a wake trigger during a run.

A schedule is a workload definition. A run manifest names it in ``workload``, so both
runs of a matched pair replay the same triggers.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

SCHEDULE_SCHEMA = 1
PATTERNS = ("random", "periodic")
MS_PER_HOUR = 3_600_000
FILE_SUFFIX = ".schedule.json"


@dataclass(frozen=True)
class Schedule:
    """Trigger times in whole milliseconds from the start of a run.

    Triggers are at least ``min_gap_ms`` apart, so the tag can finish handling one before
    the next arrives.
    """

    schedule_id: str
    duration_ms: int
    min_gap_ms: int
    times_ms: tuple[int, ...]
    source: dict[str, Any]

    @property
    def rate_per_h(self) -> float:
        return len(self.times_ms) * MS_PER_HOUR / self.duration_ms

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": SCHEDULE_SCHEMA,
            "schedule_id": self.schedule_id,
            "duration_ms": self.duration_ms,
            "min_gap_ms": self.min_gap_ms,
            "source": self.source,
            "times_ms": list(self.times_ms),
        }


def generate(
    schedule_id: str,
    *,
    pattern: str,
    rate_per_h: float,
    duration_s: float,
    min_gap_ms: int,
    seed: int,
) -> Schedule:
    """Place exactly ``rate_per_h * duration`` triggers, at random or evenly spaced.

    The count is exact, so every schedule generated for one rate has that rate. The
    first trigger comes at least ``min_gap_ms`` after the start and the last one at least
    that long before the end.
    """
    if pattern not in PATTERNS:
        raise ValueError(f"pattern must be one of {PATTERNS}")
    duration_ms = _whole_ms(duration_s)
    exact_count = rate_per_h * duration_ms / MS_PER_HOUR
    count = round(exact_count)
    if rate_per_h < 0 or abs(exact_count - count) > 1e-9:
        raise ValueError(
            f"{rate_per_h:g} triggers/h over {duration_s:g} s is {exact_count:g} triggers; "
            "choose a rate and duration that give a whole number"
        )

    # Room left once every trigger has its minimum gap on both sides.
    slack_ms = duration_ms - (count + 1) * min_gap_ms
    if count and slack_ms < 0:
        raise ValueError(f"{count} triggers {min_gap_ms} ms apart do not fit in {duration_s:g} s")
    if pattern == "random":
        # Sorted offsets inside the slack, then one gap pushed in before each trigger.
        offsets = np.sort(np.random.default_rng(seed).integers(0, slack_ms + 1, size=count))
        times = offsets + (np.arange(count) + 1) * min_gap_ms
    else:
        # Equal gaps, counting the one before the first trigger and after the last.
        times = ((np.arange(count) + 1) * duration_ms) // (count + 1)

    source: dict[str, Any] = {"type": "generated", "pattern": pattern}
    if pattern == "random":
        source["seed"] = seed
    return _checked(Schedule(schedule_id, duration_ms, min_gap_ms, tuple(times.tolist()), source))


def sweep(
    prefix: str,
    rates_per_h: Sequence[float],
    *,
    pattern: str,
    duration_s: float,
    min_gap_ms: int,
    seed: int,
) -> list[Schedule]:
    """One schedule per rate, named ``<prefix>-<pattern>-<rate>ph`` plus the seed if random."""
    if len(set(rates_per_h)) != len(rates_per_h):
        raise ValueError("sweep rates must be distinct")
    suffix = f"-s{seed}" if pattern == "random" else ""
    return [
        generate(
            f"{prefix}-{pattern}-{rate:g}ph{suffix}",
            pattern=pattern,
            rate_per_h=rate,
            duration_s=duration_s,
            min_gap_ms=min_gap_ms,
            seed=seed,
        )
        for rate in rates_per_h
    ]


def from_recording(
    recording: Path, *, schedule_id: str, duration_s: float, min_gap_ms: int
) -> Schedule:
    """Build a schedule from recorded interrupt times.

    ``recording`` is a CSV with a ``time_ms`` column, in milliseconds from the start of
    the recording and in order. A trigger closer than ``min_gap_ms`` to the one kept
    before it is dropped, and the schedule's source says how many were.
    """
    with recording.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if "time_ms" not in (reader.fieldnames or ()):
            raise ValueError(f"{recording.name} has no time_ms column")
        recorded = [round(float(row["time_ms"])) for row in reader]
    if any(later < earlier for earlier, later in zip(recorded, recorded[1:], strict=False)):
        raise ValueError(f"{recording.name} is not in time order")

    kept: list[int] = []
    for time in recorded:
        if not kept or time - kept[-1] >= min_gap_ms:
            kept.append(time)
    with recording.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    source = {
        "type": "recording",
        # Only the file name, so a committed schedule never carries a local path.
        "file": recording.name,
        "sha256": digest,
        "recorded_triggers": len(recorded),
        "dropped_triggers": len(recorded) - len(kept),
    }
    return _checked(Schedule(schedule_id, _whole_ms(duration_s), min_gap_ms, tuple(kept), source))


def save(schedule: Schedule, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{schedule.schedule_id}{FILE_SUFFIX}"
    path.write_text(json.dumps(schedule.to_json(), indent=2) + "\n", encoding="utf-8")
    return path


def load(path: Path) -> Schedule:
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        if raw["schema"] != SCHEDULE_SCHEMA:
            raise ValueError(f"unsupported schedule schema {raw['schema']!r}")
        return _checked(
            Schedule(
                schedule_id=raw["schedule_id"],
                duration_ms=raw["duration_ms"],
                min_gap_ms=raw["min_gap_ms"],
                times_ms=tuple(raw["times_ms"]),
                source=dict(raw["source"]),
            )
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{path.name}: {error}") from error


def load_all(paths: Sequence[Path]) -> dict[str, Schedule]:
    """Load schedules keyed by ``schedule_id``, which is what a manifest's ``workload`` holds."""
    schedules: dict[str, Schedule] = {}
    for path in paths:
        schedule = load(path)
        if schedule.schedule_id in schedules:
            raise ValueError(f"two schedules are named {schedule.schedule_id!r}")
        schedules[schedule.schedule_id] = schedule
    return schedules


def _whole_ms(duration_s: float) -> int:
    duration_ms = round(duration_s * 1000)
    if duration_ms <= 0:
        raise ValueError("duration must be positive")
    return duration_ms


def _checked(schedule: Schedule) -> Schedule:
    """Reject a schedule the rig could not replay as written."""
    if not isinstance(schedule.schedule_id, str) or not schedule.schedule_id:
        raise ValueError("schedule_id must be a non-empty string")
    numbers = (schedule.duration_ms, schedule.min_gap_ms, *schedule.times_ms)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in numbers):
        raise ValueError("durations, gaps and trigger times must be whole milliseconds")
    if schedule.duration_ms <= 0 or schedule.min_gap_ms <= 0:
        raise ValueError("duration_ms and min_gap_ms must be positive")
    times = schedule.times_ms
    if any(b - a < schedule.min_gap_ms for a, b in zip(times, times[1:], strict=False)):
        raise ValueError(f"triggers must be in order and at least {schedule.min_gap_ms} ms apart")
    # The times are in order by now, so the ends bound the rest.
    if times and not (0 <= times[0] and times[-1] < schedule.duration_ms):
        raise ValueError("trigger times must lie inside the run")
    return schedule
