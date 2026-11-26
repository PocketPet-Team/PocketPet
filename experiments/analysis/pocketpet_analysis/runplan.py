"""Turn an experiment definition into a randomized run order and manifest skeletons.

The definition fixes, before any capture, what a set of matched pairs will compare and
the seed that orders them. Each planned run gets a manifest with everything known in
advance filled in, so only what is measured during the run is left to add.
"""

from __future__ import annotations

import csv
import glob
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from pocketpet_analysis import schedule as schedules
from pocketpet_analysis.manifest import ROLES, parse_markers, parse_metadata
from pocketpet_analysis.schedule import Schedule
from pocketpet_analysis.stats import MIN_FORMAL_PAIRS

ORDERS = ("rounds", "grouped")
PLAN_FILE = "plan.csv"
PLAN_COLUMNS = (
    "order",
    "run_id",
    "condition",
    "pair_id",
    "role",
    "variant",
    "workload",
    "duration_s",
)
# Measured during the run, so the skeleton leaves it empty and the manifest stays
# invalid until someone records it.
MEASURED_METADATA = "ambient_temp_c"
# Names end up in run ids and file names.
_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class Definition:
    rq: str
    pairs: int
    seed: int
    order: str
    variants: dict[str, str]
    firmware_shas: dict[str, str]
    conditions: tuple[tuple[str, str], ...]
    metadata: dict[str, Any]
    markers: dict[str, Any] | None
    schedules: dict[str, Schedule] | None


@dataclass(frozen=True)
class PlannedRun:
    order: int
    run_id: str
    condition: str
    workload: str
    pair_id: str
    role: str


def load_definition(path: Path) -> Definition:
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        return _parse(raw, path.parent)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{path.name}: {error}") from error


def planned_runs(definition: Definition) -> list[PlannedRun]:
    """Order the runs: the two runs of a pair stay adjacent, in a random role order.

    With ``rounds``, each round holds one pair of every condition in a random order, so
    slow drift in the battery or the room spreads evenly over the conditions. With
    ``grouped``, all pairs of a condition run together in the order the definition lists
    them, for setups where changing condition is costly.
    """
    rng = np.random.default_rng(definition.seed)
    pair_numbers = range(1, definition.pairs + 1)
    if definition.order == "rounds":
        blocks = [
            (definition.conditions[index], pair)
            for pair in pair_numbers
            for index in rng.permutation(len(definition.conditions))
        ]
    else:
        blocks = [(condition, pair) for condition in definition.conditions for pair in pair_numbers]

    runs: list[PlannedRun] = []
    for (condition, workload), pair in blocks:
        pair_id = f"p{pair:02d}"
        for role in rng.permutation(ROLES).tolist():
            run_id = f"{definition.rq}-{condition}-{pair_id}-{role}".lower()
            runs.append(PlannedRun(len(runs) + 1, run_id, condition, workload, pair_id, role))
    return runs


def write_run_files(definition: Definition, out_dir: Path) -> list[Path]:
    """Write ``plan.csv`` and one manifest skeleton per run; return the paths written.

    Refuses to replace an existing file, because a manifest may already hold values
    recorded during its run.
    """
    runs = planned_runs(definition)
    plan_path = out_dir / PLAN_FILE
    manifest_paths = [out_dir / f"{run.run_id}.json" for run in runs]
    existing = [path.name for path in (plan_path, *manifest_paths) if path.exists()]
    if existing:
        raise ValueError(
            f"{out_dir} already has {len(existing)} of these files, starting with {existing[0]}"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    with plan_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(PLAN_COLUMNS)
        for run in runs:
            duration_s: float | str = ""
            if definition.schedules is not None:
                duration_s = definition.schedules[run.workload].duration_ms / 1000
            writer.writerow(
                [
                    run.order,
                    run.run_id,
                    run.condition,
                    run.pair_id,
                    run.role,
                    definition.variants[run.role],
                    run.workload,
                    duration_s,
                ]
            )
    for run, path in zip(runs, manifest_paths, strict=True):
        path.write_text(json.dumps(_manifest(definition, run), indent=2) + "\n", encoding="utf-8")
    return [plan_path, *manifest_paths]


def _manifest(definition: Definition, run: PlannedRun) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "run_id": run.run_id,
        "capture": f"{run.run_id}.csv",
        "rq": definition.rq,
        "condition": run.condition,
        "workload": run.workload,
        "pair_id": run.pair_id,
        "role": run.role,
        "variant": definition.variants[run.role],
        "metadata": {
            **definition.metadata,
            "firmware_sha": definition.firmware_shas[run.role],
            MEASURED_METADATA: None,
        },
    }
    if definition.markers is not None:
        manifest["markers"] = definition.markers
    return manifest


def _parse(raw: dict[str, Any], base_dir: Path) -> Definition:
    rq = _name(raw["rq"], "rq")
    pairs, seed = raw["pairs"], raw["seed"]
    if not _is_int(pairs) or pairs < 1:
        raise ValueError("pairs must be a positive whole number")
    if not _is_int(seed) or seed < 0:
        raise ValueError("seed must be a non-negative whole number")
    order = raw.get("order", ORDERS[0])
    if order not in ORDERS:
        raise ValueError(f"order must be one of {ORDERS}")

    metadata = dict(raw["metadata"])
    if MEASURED_METADATA in metadata:
        raise ValueError(f"metadata.{MEASURED_METADATA} is measured per run; leave it out")
    variants, firmware_shas = {}, {}
    for role in ROLES:
        variants[role] = _name(raw[role]["variant"], f"{role}.variant")
        # A role names its own commit only when the two roles are different builds.
        firmware_shas[role] = raw[role].get("firmware_sha", metadata.get("firmware_sha"))
        parse_metadata({**metadata, "firmware_sha": firmware_shas[role], MEASURED_METADATA: 0.0})
    metadata.pop("firmware_sha", None)
    if len(set(variants.values())) != len(ROLES):
        raise ValueError("baseline and candidate need different variant names")
    if metadata["phase"] == "formal-frozen" and pairs < MIN_FORMAL_PAIRS:
        raise ValueError(f"a formal-frozen plan needs at least {MIN_FORMAL_PAIRS} pairs")

    conditions = tuple(
        (_name(entry["condition"], "condition"), entry["workload"]) for entry in raw["conditions"]
    )
    if not conditions:
        raise ValueError("conditions must list at least one condition")
    if len({condition for condition, _ in conditions}) != len(conditions):
        raise ValueError("condition names must be distinct")
    if any(not isinstance(workload, str) or not workload for _, workload in conditions):
        raise ValueError("each condition needs a workload name")

    return Definition(
        rq=rq,
        pairs=pairs,
        seed=seed,
        order=order,
        variants=variants,
        firmware_shas=firmware_shas,
        conditions=conditions,
        metadata=metadata,
        markers=_markers(raw, base_dir),
        schedules=_schedules(raw, base_dir, conditions),
    )


def _markers(raw: dict[str, Any], base_dir: Path) -> dict[str, Any] | None:
    if "markers" in raw and "markers_file" in raw:
        raise ValueError("give markers or markers_file, not both")
    markers = raw.get("markers")
    if "markers_file" in raw:
        markers = json.loads((base_dir / raw["markers_file"]).read_text(encoding="utf-8"))
    if markers is not None:
        parse_markers(markers)
    return markers


def _schedules(
    raw: dict[str, Any], base_dir: Path, conditions: tuple[tuple[str, str], ...]
) -> dict[str, Schedule] | None:
    """Load the schedules the definition points at and check every workload is one of them."""
    if "schedules" not in raw:
        return None
    paths = [
        Path(match)
        for pattern in raw["schedules"]
        for match in sorted(glob.glob(str(base_dir / pattern)))
    ]
    loaded = schedules.load_all(paths)
    missing = sorted({workload for _, workload in conditions} - set(loaded))
    if missing:
        raise ValueError(f"no schedule file defines the workloads {missing}")
    return loaded


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _NAME_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must use only letters, digits, '.', '_' and '-'")
    return value


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
