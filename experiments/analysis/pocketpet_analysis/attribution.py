"""Integrate a capture and attribute its charge to operating states and events.

Every sample belongs to exactly one (state, active events) group, read from the logic
markers. A state's background current is its mean current while no event is active. An
event group is charged only for what it draws above that background, so overlapping
events are reported as their own group and no charge is counted twice.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np

from pocketpet_analysis.manifest import MarkerMap
from pocketpet_analysis.ppk2 import Chunk

UC_PER_MAH = 3.6e6
# A timestamp step longer than this many sample periods means the export dropped samples.
GAP_FACTOR = 1.5
_KEY_COUNT = 256


def attribute_charge(
    chunks: Iterable[Chunk], markers: MarkerMap, sample_period_s: float | None = None
) -> dict[str, Any]:
    """Return totals, per-state background, and per-event incremental charge.

    Each sample is charged for one sample period, which matches how the Power Profiler
    averages when it records below 100 kHz. Dropped samples therefore add no charge.
    The period comes from the median timestamp step unless ``sample_period_s`` is given.
    """
    used_mask = markers.used_mask
    current_sum = np.zeros(_KEY_COUNT)
    sample_count = np.zeros(_KEY_COUNT, dtype=np.int64)
    event_starts = dict.fromkeys(markers.events, 0)
    period_ms = None if sample_period_s is None else sample_period_s * 1000.0
    previous_time: float | None = None
    previous_key = 0
    gap_count, gap_ms, mixed_samples, undriven_samples = 0, 0.0, 0, 0

    for chunk in chunks:
        if used_mask and chunk.high is None:
            raise ValueError("the manifest declares markers but the capture has no logic columns")

        times = chunk.time_ms
        if previous_time is not None:
            times = np.concatenate(([previous_time], times))
        steps = np.diff(times)
        if period_ms is None:
            if steps.size == 0:
                raise ValueError("cannot infer the sample period; set sample_period_s")
            period_ms = float(np.median(steps))
        if steps.size and steps.min() <= 0:
            raise ValueError("timestamps are not strictly increasing")
        gaps = steps[steps > GAP_FACTOR * period_ms]
        gap_count += gaps.size
        gap_ms += float((gaps - period_ms).sum())

        if used_mask:
            key = chunk.high & used_mask
            mixed_samples += int(np.count_nonzero(chunk.mixed & used_mask))
            undriven_samples += int(np.count_nonzero(chunk.undriven & used_mask))
        else:
            key = np.zeros(chunk.current_ua.size, dtype=np.uint8)
        current_sum += np.bincount(key, weights=chunk.current_ua, minlength=_KEY_COUNT)
        sample_count += np.bincount(key, minlength=_KEY_COUNT)

        # Count low-to-high transitions, including one that straddles two chunks.
        with_previous = np.concatenate(([previous_key], key))
        for channel in event_starts:
            level = (with_previous >> channel) & 1
            event_starts[channel] += int(np.count_nonzero(level[1:] > level[:-1]))

        previous_time = float(chunk.time_ms[-1])
        previous_key = int(key[-1])

    if previous_time is None:
        raise ValueError("the capture has no samples")

    period_s = period_ms / 1000.0
    result = _attribute(current_sum * period_s, sample_count * period_s, markers)
    result["capture"] = {
        "samples": int(sample_count.sum()),
        "sample_period_s": period_s,
        "gap_count": int(gap_count),
        "gap_s": gap_ms / 1000.0,
        "marker_mixed_samples": mixed_samples,
        "marker_undriven_samples": undriven_samples,
    }
    result["event_counts"] = {markers.events[ch]: n for ch, n in sorted(event_starts.items())}
    return result


def _attribute(charge_uc: np.ndarray, duration_s: np.ndarray, markers: MarkerMap) -> dict[str, Any]:
    """Split per-key charge into state background and event increments."""
    groups: dict[str, dict[tuple[str, ...], list[float]]] = {}
    for key in np.flatnonzero(duration_s):
        by_events = groups.setdefault(markers.state_of(int(key)), {})
        totals = by_events.setdefault(markers.events_of(int(key)), [0.0, 0.0])
        totals[0] += float(charge_uc[key])
        totals[1] += float(duration_s[key])

    states, events, warnings = [], [], []
    attributed_uc = 0.0
    for state, by_events in sorted(groups.items()):
        quiet_charge, quiet_duration = by_events.get((), (0.0, 0.0))
        state_duration = sum(duration for _, duration in by_events.values())
        if quiet_duration:
            background_ua = quiet_charge / quiet_duration
            background_uc = background_ua * state_duration
            attributed_uc += background_uc
        else:
            background_ua = background_uc = None
            warnings.append(
                f"state {state!r} has no event-free samples, so its background current and "
                "event increments are undefined"
            )
        states.append(
            {
                "state": state,
                "duration_s": state_duration,
                "background_ua": background_ua,
                "background_charge_uc": background_uc,
            }
        )
        for active, (charge, duration) in sorted(by_events.items()):
            if not active:
                continue
            incremental = None if background_ua is None else charge - background_ua * duration
            attributed_uc += incremental or 0.0
            events.append(
                {
                    "state": state,
                    "events": list(active),
                    "duration_s": duration,
                    "incremental_charge_uc": incremental,
                }
            )

    total_uc = float(charge_uc.sum())
    total_s = float(duration_s.sum())
    return {
        "total": {
            "duration_s": total_s,
            "charge_uc": total_uc,
            "charge_mah": total_uc / UC_PER_MAH,
            "mean_current_ua": total_uc / total_s,
        },
        "states": states,
        "events": events,
        # Zero up to rounding unless a state above has an undefined background.
        "unattributed_charge_uc": total_uc - attributed_uc,
        "warnings": warnings,
    }
