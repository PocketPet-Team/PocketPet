"""Command-line entry point: ``pocketpet-analysis <command>``."""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from pocketpet_analysis import __version__, trials
from pocketpet_analysis import schedule as schedules
from pocketpet_analysis.attribution import attribute_charge
from pocketpet_analysis.breakeven import break_even
from pocketpet_analysis.compare import compare_runs
from pocketpet_analysis.manifest import load_manifest
from pocketpet_analysis.power import check_load, mixed_day, positive
from pocketpet_analysis.ppk2 import DEFAULT_CHUNK_ROWS, read_capture
from pocketpet_analysis.runplan import load_definition, write_run_files
from pocketpet_analysis.stats import DEFAULT_RESAMPLES, success_rate_ci
from pocketpet_analysis.synthetic import write_synthetic_pairs, write_synthetic_sweep
from pocketpet_analysis.trace import MarkerTrace, number

SUMMARY_SCHEMA = 1
HOURS_PER_DAY = 24.0


def summarize(manifest_path: Path, chunk_rows: int = DEFAULT_CHUNK_ROWS) -> dict[str, Any]:
    """Build the compact summary for one run: labels, totals, and attributed charge."""
    manifest = load_manifest(manifest_path)
    trace = MarkerTrace(manifest.markers, manifest.observations) if manifest.observations else None
    result = attribute_charge(
        read_capture(manifest.capture, chunk_rows),
        manifest.markers,
        manifest.sample_period_s,
        trace=trace,
    )
    # Only the file name is kept so a committed summary never carries a local path.
    capture = {"file": manifest.capture.name, "sha256": _sha256(manifest.capture)}
    summary = {
        "schema": SUMMARY_SCHEMA,
        "analysis_version": __version__,
        "run_id": manifest.run_id,
        **manifest.pairing,
        "metadata": manifest.metadata,
        **result,
        "capture": capture | result["capture"],
    }
    if manifest.notes:
        summary["notes"] = manifest.notes
    if manifest.calibration is not None:
        summary["calibration"] = check_load(manifest.calibration, summary)
    if trace is not None:
        obs = manifest.observations
        if "rq3" in obs:
            summary["rq3"] = trials.reconnect(trace, obs["rq3"])
        if "rq4" in obs:
            summary["rq4"] = trials.transfers(trace, obs["rq4"], summary)
        if "responses" in obs:
            summary["responses"] = trials.responses(trace, obs["responses"])
    return summary


def response_rate(
    trials_csv: Path, threshold_ms: float, target: float, seed: int, resamples: int
) -> dict[str, Any]:
    """Score response trials against a latency threshold; a blank latency is a timeout."""
    positive(threshold_ms, "threshold_ms")
    if not 0 <= number(target, "target") <= 1:
        raise ValueError("target must be a rate between zero and one")
    successes: dict[str, int] = {}
    trials: dict[str, int] = {}
    timeouts = 0
    with trials_csv.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("run_id") or row.get("latency_ms") is None:
                raise ValueError("each response row needs a run_id and a latency_ms field")
            run_id, latency = row["run_id"], row["latency_ms"].strip()
            trials[run_id] = trials.get(run_id, 0) + 1
            timeouts += not latency
            on_time = False
            if latency:
                elapsed = number(float(latency), "latency_ms")
                if elapsed < 0:
                    raise ValueError("latency_ms cannot be negative")
                on_time = elapsed <= threshold_ms
            successes[run_id] = successes.get(run_id, 0) + on_time
    if not trials:
        raise ValueError(f"{trials_csv.name} has no trials")

    runs = sorted(trials)
    result = success_rate_ci(
        [successes[run] for run in runs],
        [trials[run] for run in runs],
        seed=seed,
        resamples=resamples,
    )
    return {
        "threshold_ms": threshold_ms,
        "target_rate": target,
        "timeouts": timeouts,
        **result,
        "meets_target": result["success_rate"] >= target,
    }


def randomized_plan(pairs: int, seed: int) -> list[tuple[str, int, str]]:
    """Return (pair_id, order, role) rows with the run order inside each pair randomized."""
    rng = np.random.default_rng(seed)
    rows = []
    for pair in range(1, pairs + 1):
        roles = ["baseline", "candidate"]
        rng.shuffle(roles)
        rows += [(f"p{pair:02d}", order, role) for order, role in enumerate(roles, start=1)]
    return rows


def budget(capacity_mah: float, days: float, summary: dict[str, Any] | None) -> dict[str, Any]:
    """Compare a run's mean current with the average current the cell capacity allows."""
    budget_ua = (
        positive(capacity_mah, "capacity_mah") * 1000 / (positive(days, "days") * HOURS_PER_DAY)
    )
    result: dict[str, Any] = {
        "capacity_mah": capacity_mah,
        "target_days": days,
        "daily_budget_mah": capacity_mah / days,
        "budget_current_ua": budget_ua,
    }
    if summary is not None:
        mean_ua = summary["total"]["mean_current_ua"]
        duration_h = summary["total"]["duration_s"] / 3600.0
        result |= {
            "run_id": summary["run_id"],
            "run_duration_h": duration_h,
            # Shorter runs only project a daily figure; they do not validate the budget.
            "covers_24h": duration_h >= HOURS_PER_DAY,
            "mean_current_ua": mean_ua,
            "projected_daily_mah": mean_ua * HOURS_PER_DAY / 1000.0,
            "budget_fraction": mean_ua / budget_ua,
        }
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def _expand(paths: Sequence[Path]) -> list[Path]:
    """Expand wildcards ourselves, because PowerShell and cmd pass them through unexpanded."""
    expanded: list[Path] = []
    for path in paths:
        matches = sorted(glob.glob(str(path))) if glob.has_magic(str(path)) else []
        expanded += [Path(match) for match in matches] or [path]
    return expanded


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _emit(result: Any, output: Path | None) -> None:
    text = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if output is None:
        sys.stdout.write(text)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pocketpet-analysis", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("-o", "--output", type=Path, help="write here instead of stdout")
        return command

    def add_bootstrap_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("--seed", type=int, default=0)
        command.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)

    command = add("summarize", "integrate captures and attribute their charge")
    command.add_argument("manifests", type=Path, nargs="+")
    command.add_argument(
        "--output-dir", type=Path, help="write one <run_id>.summary.json per manifest here"
    )

    command = add("compare", "paired baseline-candidate comparison with 95%% bootstrap CIs")
    command.add_argument("summaries", type=Path, nargs="+")
    command.add_argument("--metric", default="total.charge_uc")
    add_bootstrap_options(command)

    command = add("response", "share of trials that responded within a latency threshold")
    command.add_argument("trials", type=Path, help="CSV with run_id and latency_ms columns")
    command.add_argument("--threshold-ms", type=float, required=True)
    command.add_argument("--target", type=float, default=0.95)
    add_bootstrap_options(command)

    command = add("plan", "randomized run order for matched pairs, as CSV")
    command.add_argument("--pairs", type=int, default=10)
    command.add_argument("--seed", type=int, required=True)

    command = add("response-criteria", "score button and nearby Find trials by run and condition")
    command.add_argument("summaries", type=Path, nargs="+")
    add_bootstrap_options(command)

    command = add("mixed-day", "project a 24-hour workload from a profiled run")
    command.add_argument("profile", type=Path, help="run summary with state and event attribution")
    command.add_argument("workload", type=Path, help="JSON with state hours and event segments")
    command.add_argument(
        "--capacity-mah", type=float, required=True, help="usable capacity at cutoff"
    )
    command.add_argument("--measured-day", type=Path, help="continuous 24-hour workload summary")

    command = add("prepare", "write the run order and manifest skeletons for an experiment")
    command.add_argument("definition", type=Path, help="experiment definition (JSON)")
    command.add_argument("out_dir", type=Path, help="where the captures will be stored")

    command = add("budget", "average-current budget for a cell capacity and runtime target")
    command.add_argument("--capacity-mah", type=float, required=True)
    command.add_argument("--days", type=float, default=60.0)
    command.add_argument("--summary", type=Path)

    command = add("synth", "write synthetic paired captures for trying the pipeline")
    command.add_argument("out_dir", type=Path)
    command.add_argument("--pairs", type=int, default=10)
    command.add_argument("--seed", type=int, default=0)
    command.add_argument(
        "--schedules",
        type=Path,
        nargs="+",
        help="write a wake-policy sweep over these trigger schedules instead",
    )

    command = add("sweep", "write one trigger schedule per wake rate")
    command.add_argument("out_dir", type=Path)
    command.add_argument("--rates", type=float, nargs="+", required=True, help="triggers per hour")
    command.add_argument("--duration-s", type=float, required=True)
    command.add_argument(
        "--min-gap-ms", type=int, required=True, help="shortest time between two triggers"
    )
    command.add_argument("--pattern", choices=schedules.PATTERNS, default="random")
    command.add_argument("--seed", type=int, default=0)
    command.add_argument("--prefix", default="wake-sweep", help="start of each schedule_id")

    command = add("import-schedule", "turn recorded interrupt times into a trigger schedule")
    command.add_argument("recording", type=Path, help="CSV with a time_ms column")
    command.add_argument("--schedule-id", required=True)
    command.add_argument("--duration-s", type=float, required=True, help="recording length")
    command.add_argument("--min-gap-ms", type=int, required=True)

    command = add("breakeven", "trigger rate at which a wake policy's saving is used up")
    command.add_argument("summaries", type=Path, nargs="+")
    command.add_argument("--schedules", type=Path, nargs="+", required=True)
    add_bootstrap_options(command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "summarize":
            manifests = _expand(args.manifests)
            if args.output_dir is None and len(manifests) > 1:
                raise ValueError("several manifests need --output-dir")
            for manifest in manifests:
                summary = summarize(manifest)
                output = args.output
                if args.output_dir is not None:
                    output = args.output_dir / f"{summary['run_id']}.summary.json"
                _emit(summary, output)
        elif args.command == "compare":
            summaries = [_read_json(path) for path in _expand(args.summaries)]
            result = compare_runs(
                summaries, metric=args.metric, seed=args.seed, resamples=args.resamples
            )
            _emit(result, args.output)
        elif args.command == "response":
            result = response_rate(
                args.trials, args.threshold_ms, args.target, args.seed, args.resamples
            )
            _emit(result, args.output)
        elif args.command == "response-criteria":
            summaries = [_read_json(path) for path in _expand(args.summaries)]
            _emit(trials.response_criteria(summaries, args.seed, args.resamples), args.output)
        elif args.command == "mixed-day":
            measured = _read_json(args.measured_day) if args.measured_day else None
            _emit(
                mixed_day(
                    _read_json(args.profile), _read_json(args.workload), args.capacity_mah, measured
                ),
                args.output,
            )
        elif args.command == "plan":
            lines = ["pair_id,order,role"]
            lines += [",".join(map(str, row)) for row in randomized_plan(args.pairs, args.seed)]
            text = "\n".join(lines) + "\n"
            if args.output:
                args.output.write_text(text, encoding="utf-8")
            else:
                sys.stdout.write(text)
        elif args.command == "prepare":
            for path in write_run_files(load_definition(args.definition), args.out_dir):
                print(path)
        elif args.command == "budget":
            summary = _read_json(args.summary) if args.summary else None
            _emit(budget(args.capacity_mah, args.days, summary), args.output)
        elif args.command == "synth":
            if args.schedules:
                loaded = list(schedules.load_all(_expand(args.schedules)).values())
                manifests = write_synthetic_sweep(
                    args.out_dir, loaded, pairs=args.pairs, seed=args.seed
                )
            else:
                manifests = write_synthetic_pairs(args.out_dir, pairs=args.pairs, seed=args.seed)
            for manifest in manifests:
                print(manifest)
        elif args.command == "sweep":
            generated = schedules.sweep(
                args.prefix,
                args.rates,
                pattern=args.pattern,
                duration_s=args.duration_s,
                min_gap_ms=args.min_gap_ms,
                seed=args.seed,
            )
            for schedule in generated:
                print(schedules.save(schedule, args.out_dir))
        elif args.command == "import-schedule":
            schedule = schedules.from_recording(
                args.recording,
                schedule_id=args.schedule_id,
                duration_s=args.duration_s,
                min_gap_ms=args.min_gap_ms,
            )
            _emit(schedule.to_json(), args.output)
        elif args.command == "breakeven":
            result = break_even(
                [_read_json(path) for path in _expand(args.summaries)],
                schedules.load_all(_expand(args.schedules)),
                seed=args.seed,
                resamples=args.resamples,
            )
            _emit(result, args.output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
