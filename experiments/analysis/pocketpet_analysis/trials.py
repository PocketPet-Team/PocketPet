"""Trial outcomes from PPK2 markers and external observations on the capture clock."""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from typing import Any

from pocketpet_analysis.stats import success_rate_ci
from pocketpet_analysis.trace import MarkerTrace, number, records

THRESHOLD_MS = {"button": 150, "find": 2000}
TARGET_RATE = 0.95


def _deadline(section: dict, field: str) -> float:
    limit = number(section[field], field)
    if limit <= 0:
        raise ValueError(f"{field} must be positive")
    return limit


def reconnect(trace: MarkerTrace, section: dict) -> dict:
    timeout = _deadline(section, "timeout_ms")
    if "connected" not in trace.markers.state_names.values() or any(
        trace.markers.state_of(key).startswith("unmapped_") for key in set(trace.keys)
    ):
        raise ValueError("reconnection trials need decoded link states including connected")
    linked = [trace.markers.state_of(key) == "connected" for key in trace.keys]
    lost, restored = [], []
    for i in range(1, len(linked)):
        if linked[i] != linked[i - 1]:
            (restored if linked[i] else lost).append(trace.times[i])

    rows = []
    finished = float("-inf")
    for trial in records(section, "trials"):
        depart = trace.timestamp(trial["depart_ms"], markers_allowed=False)
        back = trace.timestamp(trial["return_ms"], markers_allowed=False)
        if not finished < depart < back:
            raise ValueError("separation trials must be ordered and disjoint")
        loss = bisect_left(lost, depart)
        if (
            loss == len(lost)
            or lost[loss] >= back
            or (lost[loss] != depart and trace.state_at(depart) != "connected")
        ):
            raise ValueError("separation needs an established link and observed loss before return")
        i = bisect_left(restored, lost[loss])
        recovery = restored[i] if i < len(restored) else None
        if recovery is not None and recovery < back:
            raise ValueError("link restored before the recorded phone return")
        deadline = back + timeout
        success = recovery is not None and recovery <= deadline
        if not success and trace.last_ms < deadline:
            raise ValueError("capture ends before the reconnection timeout")
        finished = recovery if success else deadline
        rows.append(
            {
                "depart_ms": depart,
                "return_ms": back,
                "state_at_return": trace.state_at(back),
                "apart_ms": back - depart,
                "apart_charge_uc": trace.apart_charge_at[back] - trace.apart_charge_at[depart],
                "recovery_ms": recovery - back if success else None,
            }
        )
    latencies = [r["recovery_ms"] for r in rows if r["recovery_ms"] is not None]
    return {
        "timeout_ms": timeout,
        "trials": rows,
        "timeouts": len(rows) - len(latencies),
        "apart_charge_uc": sum(r["apart_charge_uc"] for r in rows),
        "mean_recovery_ms": sum(latencies) / len(latencies) if latencies else None,
    }


def _transfer_windows(trace: MarkerTrace, summary: dict) -> list[dict]:
    if "transfer" not in trace.markers.events.values():
        raise ValueError("RQ4 needs the transfer marker")
    background = {r["state"]: r["background_ua"] for r in summary["states"]}
    windows = []
    active = None
    for i, key in enumerate(trace.keys):
        events = trace.markers.events_of(key)
        if "transfer" not in events:
            active = None
            continue
        if i == 0 or i + 1 == len(trace.keys):
            raise ValueError("capture starts or ends inside a transfer pulse")
        if active is None:
            active = {"start_ms": trace.times[i], "overlap": False, "incremental_charge_uc": 0.0}
            windows.append(active)
        state = trace.markers.state_of(key)
        if background[state] is None:
            raise ValueError(f"transfer in {state!r} has no event-free background")
        dt = (trace.times[i + 1] - trace.times[i]) / 1000
        charge = trace.charge_uc[i + 1] - trace.charge_uc[i]
        active["incremental_charge_uc"] += charge - dt * background[state]
        active["end_ms"] = trace.times[i + 1]
        active["overlap"] |= len(events) > 1
    return windows


def transfers(trace: MarkerTrace, section: dict, summary: dict) -> dict:
    windows = _transfer_windows(trace, summary)
    clean = [p["incremental_charge_uc"] for p in windows if not p["overlap"]]
    result = {
        "transfer_count": len(windows),
        "pulses": windows,
        "window_incremental_charge_uc": sum(w["incremental_charge_uc"] for w in windows),
        "mean_isolated_incremental_uc": sum(clean) / len(clean) if clean else None,
    }
    if "updates" not in section and "freshness_limit_ms" not in section:
        return result
    limit = _deadline(section, "freshness_limit_ms")
    ages = []
    holds = []
    missing = 0
    for update in records(section, "updates"):
        due = trace.timestamp(update["due_ms"], markers_allowed=False)
        received = update["received_ms"]
        if "transfer_index" in update:
            index = update["transfer_index"]
            if type(index) is not int or not 1 <= index <= len(windows):
                raise ValueError("transfer_index must identify an observed transfer pulse")
            queued = windows[index - 1]["start_ms"]
            if queued < due or (received is not None and queued > number(received, "received_ms")):
                raise ValueError("transfer start must follow the due time and precede receipt")
            holds.append(queued - due)
        if received is None:
            if trace.last_ms < due + limit:
                raise ValueError("capture ends before the update freshness deadline")
            missing += 1
            continue
        age = trace.timestamp(received, markers_allowed=False) - due
        if age < 0:
            raise ValueError("update received before it was due")
        ages.append(age)
    stale = missing + sum(age > limit for age in ages)
    return result | {
        "freshness_limit_ms": limit,
        "updates": len(ages) + missing,
        "undelivered": missing,
        "updates_with_transfer_index": len(holds),
        "max_observed_hold_ms": max(holds, default=None),
        "max_delivered_age_ms": max(ages, default=None),
        "freshness_failures": stale,
        "meets_freshness": stale == 0,
    }


def responses(trace: MarkerTrace, section: dict) -> dict:
    source = section["source"]
    if source not in ("physical", "firmware-proxy"):
        raise ValueError("response source must be physical or firmware-proxy")
    grouped: dict[str, list] = defaultdict(list)
    requests, outcomes = set(), set()
    for row in records(section, "trials"):
        kind = row["kind"]
        if kind not in THRESHOLD_MS:
            raise ValueError("response kind must be button or find")
        request = trace.timestamp(row["request_ms"], markers_allowed=source != "physical")
        if (kind, request) in requests:
            raise ValueError("duplicate response trial request")
        requests.add((kind, request))
        if kind == "find" and trace.state_at(request) != "connected":
            raise ValueError("a nearby Find request needs an established link at request time")
        latency = None
        if row["response_ms"] is not None:
            onset = trace.timestamp(row["response_ms"], markers_allowed=source != "physical")
            if onset < request or (kind, onset) in outcomes:
                raise ValueError("response precedes its request or was already used")
            outcomes.add((kind, onset))
            latency = onset - request
        elif trace.last_ms < request + THRESHOLD_MS[kind]:
            raise ValueError("capture ends before the response deadline")
        grouped[kind].append(latency)
    return {
        "source": source,
        "by_kind": {
            kind: {
                "threshold_ms": THRESHOLD_MS[kind],
                "latencies_ms": values,
                "trials": len(values),
                "successes": sum(v is not None and v <= THRESHOLD_MS[kind] for v in values),
                "timeouts": values.count(None),
            }
            for kind, values in grouped.items()
        },
    }


def response_criteria(summaries: list[dict], seed: int, resamples: int) -> list[dict]:
    groups: dict[tuple, list] = defaultdict(list)
    seen = set()
    for summary in summaries:
        if summary["run_id"] in seen:
            raise ValueError(f"duplicate run {summary['run_id']!r}")
        seen.add(summary["run_id"])
        labels = {k: summary.get(k) for k in ("rq", "condition", "workload", "role", "variant")}
        labels.update({k: summary["metadata"][k] for k in ("phase", "board_rev", "firmware_sha")})
        block = summary["responses"]
        for kind, counts in block["by_kind"].items():
            group = labels | {"source": block["source"], "kind": kind}
            groups[tuple(group.items())].append(counts)
    results: list[dict[str, Any]] = []
    for key, rows in groups.items():
        labels = dict(key)
        rate = success_rate_ci(
            [r["successes"] for r in rows],
            [r["trials"] for r in rows],
            seed=seed,
            resamples=resamples,
        )
        observed = rate["success_rate"] >= TARGET_RATE
        results.append(
            labels
            | rate
            | {
                "timeouts": sum(r["timeouts"] for r in rows),
                "threshold_ms": THRESHOLD_MS[labels["kind"]],
                "target_rate": TARGET_RATE,
                "observed_rate_meets_target": observed,
                "physical_target_met": observed if labels["source"] == "physical" else None,
            }
        )
    return results
