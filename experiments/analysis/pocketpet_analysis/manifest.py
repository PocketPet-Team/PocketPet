"""Run manifest: the JSON sidecar that labels one capture and names its logic markers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pocketpet_analysis.ppk2 import CHANNEL_COUNT

PHASES = ("pilot", "formal-frozen")
ROLES = ("baseline", "candidate")
REQUIRED_METADATA = (
    "board_rev",
    "firmware_sha",
    "supply_v",
    "ambient_temp_c",
    "phone_model",
    "os_version",
    "phase",
)
# Labels that place a run in a comparison. A standalone capture, such as the 24-hour
# mixed-use run, leaves them out.
PAIRING_FIELDS = ("rq", "condition", "workload", "pair_id", "role", "variant")

_SHA_PATTERN = re.compile(r"[0-9a-f]{7,40}")


@dataclass(frozen=True)
class MarkerMap:
    """How PPK2 logic channels encode firmware state and events for one run.

    ``state_channels`` form a binary state code, least significant channel first. Each
    event channel is held high for as long as its event lasts.
    """

    state_channels: tuple[int, ...] = ()
    state_names: dict[int, str] = field(default_factory=dict)
    events: dict[int, str] = field(default_factory=dict)

    @property
    def used_mask(self) -> int:
        return sum(1 << channel for channel in (*self.state_channels, *self.events))

    def state_of(self, key: int) -> str:
        if not self.state_channels:
            return "run"
        code = sum(((key >> channel) & 1) << bit for bit, channel in enumerate(self.state_channels))
        # An undeclared code is kept under a visible name so its charge still counts.
        return self.state_names.get(code, f"unmapped_{code}")

    def events_of(self, key: int) -> tuple[str, ...]:
        return tuple(name for channel, name in sorted(self.events.items()) if (key >> channel) & 1)


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    capture: Path
    metadata: dict[str, Any]
    markers: MarkerMap
    pairing: dict[str, str]
    sample_period_s: float | None
    notes: str | None


def load_manifest(path: Path) -> RunManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        return _parse(raw, path.parent)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{path.name}: {error}") from error


def _parse(raw: dict[str, Any], base_dir: Path) -> RunManifest:
    run_id = raw["run_id"]
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id must be a non-empty string")

    pairing = {name: raw[name] for name in PAIRING_FIELDS if name in raw}
    if "role" in pairing and pairing["role"] not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")

    period = raw.get("sample_period_s")
    if period is not None and not (_is_number(period) and period > 0):
        raise ValueError("sample_period_s must be a positive number")

    return RunManifest(
        run_id=run_id,
        capture=base_dir / raw["capture"],
        metadata=parse_metadata(raw["metadata"]),
        markers=parse_markers(raw.get("markers", {})),
        pairing=pairing,
        sample_period_s=period,
        notes=raw.get("notes"),
    )


def parse_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Check a manifest's ``metadata`` block and return a copy of it."""
    missing = [name for name in REQUIRED_METADATA if name not in metadata]
    if missing:
        raise ValueError(f"metadata is missing {missing}")
    if metadata["phase"] not in PHASES:
        raise ValueError(f"metadata.phase must be one of {PHASES}")
    if not _SHA_PATTERN.fullmatch(str(metadata["firmware_sha"])):
        raise ValueError("metadata.firmware_sha must be 7 to 40 lowercase hex characters")
    for name in ("supply_v", "ambient_temp_c"):
        if not _is_number(metadata[name]):
            raise ValueError(f"metadata.{name} must be a number")
    for name in ("board_rev", "phone_model", "os_version"):
        if not isinstance(metadata[name], str) or not metadata[name]:
            raise ValueError(f"metadata.{name} must be a non-empty string")
    return dict(metadata)


def parse_markers(markers: dict[str, Any]) -> MarkerMap:
    """Check a manifest's ``markers`` block and return its channel map."""
    state_channels = tuple(markers.get("state_channels", ()))
    events = {int(channel): name for channel, name in markers.get("events", {}).items()}
    state_names = {int(code): name for code, name in markers.get("states", {}).items()}

    channels = [*state_channels, *events]
    if any(not isinstance(ch, int) or not 0 <= ch < CHANNEL_COUNT for ch in channels):
        raise ValueError(f"marker channels must be integers from 0 to {CHANNEL_COUNT - 1}")
    if len(set(channels)) != len(channels):
        raise ValueError("a logic channel can mark one state bit or one event, not both")
    if any(not 0 <= code < 2 ** len(state_channels) for code in state_names):
        raise ValueError("a state code does not fit in the declared state_channels")
    if len(set(events.values())) != len(events):
        raise ValueError("event names must be unique")
    return MarkerMap(state_channels, state_names, events)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)
