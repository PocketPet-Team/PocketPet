"""Generate synthetic PPK2 exports and manifests for exercising the pipeline.

The currents below are arbitrary round numbers, not estimates of PocketPet hardware.
Every generated manifest is labelled ``board_rev: synthetic`` so its summaries cannot be
mistaken for measurements.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from pocketpet_analysis.schedule import Schedule

STATE_CHANNELS = [0, 1]
STATES = {"0": "sleep", "1": "advertising", "2": "connected"}
EVENTS = {"2": "button", "3": "find"}
BACKGROUND_UA = {"sleep": 8.0, "advertising": 40.0, "connected": 60.0}
CANDIDATE_ADVERTISING_UA = 25.0
EVENT_UA = {"button": 4000.0, "find": 30000.0}
NOISE_UA = 2.0
SYNTHETIC_NOTE = "Synthetic data for testing the analysis pipeline. Not a measurement."

# Wake-policy sweep model: polling draws a steady current whatever the triggers do, while
# the interrupt policy idles lower and pays a fixed burst for each trigger.
POLLING_UA = 20.0
INTERRUPT_IDLE_UA = 8.0
WAKE_UA = 3000.0
WAKE_S = 1.0
RUN_OFFSET_UA = 0.3
SWEEP_BREAK_EVEN_PER_H = (POLLING_UA - INTERRUPT_IDLE_UA) * 3600.0 / (WAKE_UA * WAKE_S)
SWEEP_METADATA = {
    "board_rev": "synthetic",
    "firmware_sha": "0000000",
    "supply_v": 3.7,
    "ambient_temp_c": 25.0,
    "phone_model": "none",
    "os_version": "none",
    "phase": "pilot",
}


def synthetic_run(
    rng: np.random.Generator, *, candidate: bool, duration_s: float, sample_rate_hz: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return timestamps (ms), currents (uA) and the packed logic byte for one run.

    The run advertises, connects, then sleeps. A button press and a find request happen
    while connected, and a second button press lands inside the find window.
    """
    count = round(duration_s * sample_rate_hz)
    fraction = np.arange(count) / count
    time_ms = np.arange(count) * (1000.0 / sample_rate_hz)

    state_code = np.where(fraction < 0.25, 1, np.where(fraction < 0.85, 2, 0))
    advertising_ua = CANDIDATE_ADVERTISING_UA if candidate else BACKGROUND_UA["advertising"]
    current = np.select(
        [state_code == 1, state_code == 2],
        [advertising_ua, BACKGROUND_UA["connected"]],
        default=BACKGROUND_UA["sleep"],
    )

    button = ((fraction >= 0.40) & (fraction < 0.41)) | ((fraction >= 0.62) & (fraction < 0.63))
    find = (fraction >= 0.60) & (fraction < 0.66)
    current = current + button * EVENT_UA["button"] + find * EVENT_UA["find"]
    current = current + rng.normal(0.0, NOISE_UA, count)

    # The state code already sits on channels 0 and 1; events take channels 2 and 3.
    bits = state_code | button.astype(int) << 2 | find.astype(int) << 3
    return time_ms, current, bits.astype(np.uint8)


def write_capture(path: Path, time_ms: np.ndarray, current: np.ndarray, bits: np.ndarray) -> None:
    """Write samples in the Power Profiler layout: timestamp, current, packed D0-D7."""
    rows = ["Timestamp(ms),Current(uA),D0-D7"]
    for t, i, b in zip(time_ms.tolist(), current.tolist(), bits.tolist(), strict=True):
        levels = "".join("1" if (b >> channel) & 1 else "0" for channel in range(8))
        rows.append(f"{t:.10g},{i:.3f},{levels}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_synthetic_pairs(
    out_dir: Path,
    *,
    pairs: int,
    seed: int,
    duration_s: float = 20.0,
    sample_rate_hz: int = 1000,
) -> list[Path]:
    """Write ``pairs`` baseline-candidate captures with manifests; return the manifest paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    manifests = []
    for pair in range(1, pairs + 1):
        for role in ("baseline", "candidate"):
            run_id = f"synthetic-p{pair:02d}-{role}"
            samples = synthetic_run(
                rng,
                candidate=role == "candidate",
                duration_s=duration_s,
                sample_rate_hz=sample_rate_hz,
            )
            write_capture(out_dir / f"{run_id}.csv", *samples)
            manifest = {
                "run_id": run_id,
                "capture": f"{run_id}.csv",
                "notes": SYNTHETIC_NOTE,
                "rq": "synthetic",
                "condition": "synthetic-demo",
                "workload": "synthetic-demo",
                "pair_id": f"p{pair:02d}",
                "role": role,
                "variant": "slower-advertising" if role == "candidate" else "reference",
                "metadata": {
                    "board_rev": "synthetic",
                    "firmware_sha": "0000000",
                    "supply_v": 3.7,
                    "ambient_temp_c": 25.0,
                    "phone_model": "none",
                    "os_version": "none",
                    "phase": "pilot",
                },
                "markers": {
                    "state_channels": STATE_CHANNELS,
                    "states": STATES,
                    "events": EVENTS,
                },
            }
            manifest_path = out_dir / f"{run_id}.json"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            manifests.append(manifest_path)
    return manifests


def write_synthetic_sweep(
    out_dir: Path,
    schedules: list[Schedule],
    *,
    pairs: int,
    seed: int,
    sample_rate_hz: int = 20,
) -> list[Path]:
    """Write ``pairs`` polling-interrupt pairs per schedule; return the manifest paths.

    Each run gets its own small current offset, so pairs differ the way repeated runs do.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    manifests = []
    for schedule in schedules:
        count = round(schedule.duration_ms / 1000 * sample_rate_hz)
        time_ms = np.arange(count) * (1000.0 / sample_rate_hz)
        starts = np.asarray(schedule.times_ms, dtype=float)[:, None]
        awake = ((time_ms >= starts) & (time_ms < starts + WAKE_S * 1000.0)).any(axis=0)
        for pair in range(1, pairs + 1):
            for role in ("baseline", "candidate"):
                interrupt = role == "candidate"
                current = np.full(count, INTERRUPT_IDLE_UA if interrupt else POLLING_UA)
                current = current + rng.normal(0.0, RUN_OFFSET_UA)
                current = current + rng.normal(0.0, NOISE_UA, count)
                # Only the interrupt policy wakes on a trigger, and marks it on D0.
                bits = (awake & interrupt).astype(np.uint8)
                run_id = f"{schedule.schedule_id}-p{pair:02d}-{role}"
                write_capture(out_dir / f"{run_id}.csv", time_ms, current + bits * WAKE_UA, bits)
                manifest = {
                    "run_id": run_id,
                    "capture": f"{run_id}.csv",
                    "notes": SYNTHETIC_NOTE,
                    "rq": "synthetic",
                    "condition": schedule.schedule_id,
                    "workload": schedule.schedule_id,
                    "pair_id": f"p{pair:02d}",
                    "role": role,
                    "variant": "interrupt" if interrupt else "polling",
                    "metadata": SWEEP_METADATA,
                    "markers": {"events": {"0": "wake"}},
                }
                manifest_path = out_dir / f"{run_id}.json"
                manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                manifests.append(manifest_path)
    return manifests
