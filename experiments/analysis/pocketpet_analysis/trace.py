"""Sparse marker transitions and charge at synchronized trial boundaries."""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections import defaultdict
from typing import Any

import numpy as np

from pocketpet_analysis.manifest import MarkerMap
from pocketpet_analysis.ppk2 import Chunk


def number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def records(section: dict, name: str) -> list[dict]:
    rows = section[name]
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{name} needs a non-empty list of records")
    return rows


class MarkerTrace:
    """Keep one entry per marker change, independent of sample and CSV chunk counts."""

    def __init__(self, markers: MarkerMap, observations: dict):
        self.markers = markers
        state_mask = sum(1 << ch for ch in markers.state_channels)
        self.mask = state_mask if "rq3" in observations else 0
        if "rq4" in observations:
            self.mask = markers.used_mask
        if "responses" in observations:
            channels = {name: ch for ch, name in markers.events.items()}
            for row in records(observations["responses"], "trials"):
                if row["kind"] == "find":
                    self.mask |= state_mask
                for point in (row["request_ms"], row["response_ms"]):
                    if isinstance(point, dict) and point.get("marker") in channels:
                        self.mask |= 1 << channels[point["marker"]]
        self.times: list[float] = []
        self.keys: list[int] = []
        self.charge_uc: list[float] = []
        self.end_ms = 0.0
        self.last_ms = 0.0
        self.total_uc = 0.0
        self.edges: dict[tuple[str, str], list[float]] = defaultdict(list)
        trials = records(observations["rq3"], "trials") if "rq3" in observations else []
        self.boundaries = sorted(
            {number(t[field], field) for t in trials for field in ("depart_ms", "return_ms")}
        )
        self.apart_charge_at: dict[float, float] = {}

    def observe(self, chunk: Chunk, key: np.ndarray, starts: np.ndarray, period_ms: float) -> None:
        times = chunk.time_ms
        if self.times and not math.isclose(times[0], self.end_ms, rel_tol=0, abs_tol=1e-6):
            raise ValueError("trial analysis needs a continuous, uniformly sampled capture")
        if not np.allclose(np.diff(times), period_ms, rtol=1e-6, atol=1e-6):
            raise ValueError("trial analysis needs a continuous, uniformly sampled capture")
        if chunk.high is not None and np.any((chunk.mixed | chunk.undriven) & self.mask):
            raise ValueError(
                "trial analysis needs resolved levels on the channels used by the trial"
            )

        prefix = np.concatenate(([0.0], np.cumsum(chunk.current_ua))) * (period_ms / 1000)
        self.last_ms = float(times[-1])
        self.end_ms = self.last_ms + period_ms
        for i in np.flatnonzero(starts):
            stamp, new = float(times[i]), int(key[i]) & self.mask
            if self.keys:
                old = self.keys[-1]
                if new == old:
                    continue
                for ch, name in self.markers.events.items():
                    if (old ^ new) & (1 << ch):
                        edge = "rise" if new & (1 << ch) else "fall"
                        self.edges[name, edge].append(stamp)
            self.times.append(stamp)
            self.keys.append(new)
            self.charge_uc.append(self.total_uc + float(prefix[i]))

        # Clip the boundary sample when a phone timestamp falls between two PPK2 ticks.
        lo = bisect_left(self.boundaries, times[0])
        hi = bisect_right(self.boundaries, self.end_ms)
        for stamp in self.boundaries[lo:hi]:
            i = min(int(np.searchsorted(times, stamp, side="right")) - 1, len(times) - 1)
            partial = chunk.current_ua[i] * (stamp - times[i]) / 1000
            self.apart_charge_at[stamp] = self.total_uc + float(prefix[i] + partial)
        self.total_uc += float(prefix[-1])

    def timestamp(self, value: Any, *, markers_allowed: bool = True) -> float:
        """Resolve an aligned timestamp or an explicitly identified, one-based edge."""
        if markers_allowed and isinstance(value, dict):
            name, edge, n = value["marker"], value["edge"], value["index"]
            if not isinstance(name, str) or edge not in ("rise", "fall") or type(n) is not int:
                raise ValueError("a marker reference needs a name, rise/fall and integer index")
            edges = self.edges.get((name, edge), [])
            if not 1 <= n <= len(edges):
                raise ValueError(f"no {name} {edge} edge at index {n}")
            return edges[n - 1]
        stamp = number(value, "timestamp")
        if not self.times[0] <= stamp < self.end_ms:
            raise ValueError(f"timestamp {stamp} is outside the capture")
        return stamp

    def state_at(self, stamp: float) -> str:
        return self.markers.state_of(self.keys[bisect_right(self.times, stamp) - 1])
