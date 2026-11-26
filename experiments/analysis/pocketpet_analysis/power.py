"""Precision-load checks and projections for a 24-hour mixed-use workload."""

from __future__ import annotations

import math

from pocketpet_analysis.attribution import UC_PER_MAH
from pocketpet_analysis.trace import number


def positive(value, name: str) -> float:
    value = number(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def check_load(config: dict, summary: dict) -> dict:
    if not isinstance(config, dict) or ("reference_ua" in config) == ("resistance_ohm" in config):
        raise ValueError("calibration needs either reference_ua or resistance_ohm")
    if "reference_ua" in config:
        expected = positive(config["reference_ua"], "reference_ua")
        reference = {"reference_ua": expected}
    else:
        ohms = positive(config["resistance_ohm"], "resistance_ohm")
        voltage = positive(summary["metadata"]["supply_v"], "supply_v")
        expected = voltage * 1e6 / ohms
        reference = {"resistance_ohm": ohms, "supply_v": voltage}
    tolerance = number(config["tolerance_pct"], "tolerance_pct")
    if tolerance < 0:
        raise ValueError("tolerance_pct cannot be negative")
    if summary["capture"]["gap_count"]:
        raise ValueError("precision-load capture contains missing samples")
    measured = summary["total"]["mean_current_ua"]
    error = measured - expected
    allowed = expected * tolerance / 100
    return {
        "reference": reference,
        "expected_ua": expected,
        "measured_ua": measured,
        "error_ua": error,
        "error_pct": 100 * error / expected,
        "tolerance_pct": tolerance,
        "within_tolerance": abs(error) <= allowed
        or math.isclose(abs(error), allowed, rel_tol=0, abs_tol=4 * math.ulp(expected)),
    }


def mixed_day(profile: dict, workload: dict, capacity_mah: float, measured: dict | None) -> dict:
    capacity = positive(capacity_mah, "measured capacity at cutoff")
    name = workload["workload"]
    if not isinstance(name, str) or not name.strip():
        raise ValueError("workload needs a name")
    if any(
        profile["capture"].get(k)
        for k in ("gap_count", "irregular_steps", "marker_undriven_samples", "marker_mixed_samples")
    ):
        raise ValueError(
            "mixed-day segment counts need uniform sampling and resolved marker levels"
        )
    hours = workload["state_hours"]
    if not isinstance(hours, dict) or not hours:
        raise ValueError("state_hours needs a state-to-hours mapping")
    hours = {state: number(value, "state hours") for state, value in hours.items()}
    if min(hours.values()) < 0 or not math.isclose(
        sum(hours.values()), 24, rel_tol=0, abs_tol=1e-8
    ):
        raise ValueError("state hours must be non-negative and total 24")
    background = {row["state"]: row["background_ua"] for row in profile["states"]}
    states = {s: number(background[s], f"{s} background") * h / 1000 for s, h in hours.items()}
    groups = {(row["state"], tuple(sorted(row["events"]))): row for row in profile["events"]}
    active_s = dict.fromkeys(hours, 0.0)
    seen = set()
    events = []
    if not isinstance(workload["event_segments"], list):
        raise ValueError("event_segments must be a list")
    for item in workload["event_segments"]:
        state, names, count = item["state"], item["events"], item["count"]
        if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
            raise ValueError("each segment needs a list of event names")
        key = state, tuple(sorted(names))
        if key in seen or len(set(names)) != len(names):
            raise ValueError("duplicate event group in workload")
        seen.add(key)
        if type(count) is not int or count < 0 or state not in hours:
            raise ValueError("each segment needs a budgeted state and non-negative integer count")
        row = groups[key]
        if not row.get("segments"):
            raise ValueError("summarize the profile capture again to obtain event segment counts")
        scale = count / row["segments"]
        increment = number(row["incremental_charge_uc"], "event increment") * scale / UC_PER_MAH
        active_s[state] += row["duration_s"] * scale
        events.append(
            {"state": state, "events": names, "count": count, "incremental_mah": increment}
        )
    if any(seconds > hours[state] * 3600 + 1e-6 for state, seconds in active_s.items()):
        raise ValueError("modeled event segments exceed the available time in their state")
    total = sum(states.values()) + sum(r["incremental_mah"] for r in events)
    result = {
        "workload": name,
        "profile_run_id": profile["run_id"],
        "metadata": profile["metadata"],
        "background_mah_by_state": states,
        "event_segments": events,
        "modeled_daily_mah": total,
        "measured_capacity_mah": capacity,
        "target_days": 60,
        "daily_budget_mah": capacity / 60,
        "modeled_margin_mah": capacity / 60 - total,
        "within_modeled_budget": total <= capacity / 60,
    }
    if measured is not None:
        if measured["workload"] != name or any(
            measured["metadata"].get(k) != profile["metadata"].get(k)
            for k in (
                "board_rev",
                "board_id",
                "firmware_sha",
                "supply_v",
                "phone_model",
                "os_version",
            )
        ):
            raise ValueError("24-hour capture must match the workload, board and configuration")
        capture = measured["capture"]
        if "elapsed_s" not in capture:
            raise ValueError("summarize the 24-hour capture again to verify its elapsed time")
        durations = (measured["total"]["duration_s"], capture["elapsed_s"])
        if (
            capture["gap_count"]
            or capture["irregular_steps"]
            or not all(math.isclose(s, 86400, rel_tol=0, abs_tol=1e-6) for s in durations)
        ):
            raise ValueError("validation needs one continuous 24-hour capture")
        charge = measured["total"]["charge_mah"]
        result["measured_24h"] = {
            "run_id": measured["run_id"],
            "charge_mah": charge,
            "measured_minus_modeled_mah": charge - total,
            "within_budget": charge <= capacity / 60,
        }
    return result
