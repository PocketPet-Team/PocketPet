# PocketPet analysis

Python tools that turn a Nordic PPK2 capture into a compact charge summary, compare matched baseline and candidate runs, and generate the trigger schedules for the RQ1 wake-rate sweep.

> **Status:** The pipeline has been tested on synthetic captures. The DK has a provisional marker layout. Wiring, timing accuracy and device currents still need bench verification.

## Setup and checks

Install [uv](https://docs.astral.sh/uv/), then run from `experiments/analysis/`:

```sh
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

`uv sync` needs Python 3.11 or newer and installs NumPy, pytest and Ruff at the versions in `uv.lock`.

## Try it on synthetic data

```sh
uv run pocketpet-analysis synth demo --pairs 10 --seed 1
uv run pocketpet-analysis summarize "demo/*.json" --output-dir demo/summaries
uv run pocketpet-analysis compare "demo/summaries/*.json" --seed 1
```

`synth` writes 20 captures in the Power Profiler CSV layout, each with a manifest. Their currents are arbitrary round numbers and every manifest says `board_rev: synthetic`. The candidate runs advertise at 25 µA where the baseline uses 40 µA, for 5 s per run, so `compare` should report a mean difference near −75 µC. Delete `demo/` afterwards; it is not project data.

## Workflow for a real run

1. Write an experiment definition and run `prepare` (see below). It fixes the run order and writes a manifest skeleton for every run.
2. Capture the runs in the order `plan.csv` lists them. Export CSV from the Power Profiler with timestamp, current, and one of the digital options selected, and save each export under the name its manifest expects.
3. Fill in `ambient_temp_c` in each manifest as you go.
4. Run `summarize` and commit the summary JSON under `experiments/data/`.
5. Run `compare` on the summaries of one research question.

For reconnection, transfer freshness, button and Find timing, precision loads and the mixed-use day, see the [bench analysis guide](../../docs/bench-analysis.md). It describes the optional manifest sections, the physical observations each metric needs and the commands to reproduce the analysis.

For a single pair or a quick trial, `uv run pocketpet-analysis plan --pairs 10 --seed <n>` prints which role runs first in each pair, and the manifests can be written by hand (format below).

## Prepare an experiment

An experiment definition states, before any capture, what a set of matched pairs compares:

```json
{
  "rq": "RQ1",
  "pairs": 10,
  "seed": 20261126,
  "order": "rounds",
  "baseline": {"variant": "polling"},
  "candidate": {"variant": "interrupt"},
  "conditions": [
    {"condition": "wake-0ph", "workload": "wake-sweep-random-0ph-s1"},
    {"condition": "wake-12ph", "workload": "wake-sweep-random-12ph-s1"}
  ],
  "metadata": {
    "board_rev": "nrf52840-dk",
    "board_id": "dk-01",
    "firmware_sha": "<commit of the flashed firmware>",
    "supply_v": 3.7,
    "phone_model": "none",
    "os_version": "none",
    "phase": "pilot"
  },
  "markers_file": "ppk2-markers.json",
  "schedules": ["workloads/*.schedule.json"]
}
```

The values above only show the shape of the file. Then:

```sh
uv run pocketpet-analysis prepare rq1-pilot.plan.json ../data/raw/rq1-pilot
```

`prepare` writes `plan.csv` and one `<run_id>.json` manifest per run into the output directory, which is also where the captures go. `experiments/data/raw/` is ignored by Git, so commit the definition somewhere else. It refuses to replace a file that already exists, because a manifest may hold values recorded during its run.

- `plan.csv` lists the runs in the order to capture them. The two runs of a pair are adjacent and their order is random. With `"order": "rounds"` (the default) each round holds one pair of every condition in a random order, so slow drift in the battery or the room spreads evenly over the conditions. `"order": "grouped"` runs all pairs of a condition together, in the order the definition lists the conditions.
- The same definition always gives the same plan. Change `seed` to get another.
- Each manifest has every field filled in except `metadata.ambient_temp_c`, which is `null`. `summarize` rejects the manifest until the temperature is recorded.
- A role can carry its own `firmware_sha` when baseline and candidate are different commits. Otherwise both use the one in `metadata`.
- `markers` holds the marker block inline, and `markers_file` reads it from a JSON file. Paths in a definition are relative to the definition file.
- `schedules` is optional. When given, every `workload` must be the `schedule_id` of one of those files, and `plan.csv` shows each run's length in `duration_s`.
- A definition whose `phase` is `formal-frozen` needs at least 10 pairs.

## Run manifest

```json
{
  "run_id": "rq3-sep10-p01-baseline",
  "capture": "rq3-sep10-p01-baseline.csv",
  "rq": "RQ3",
  "condition": "separation-10min",
  "workload": "rq3-separation-10min",
  "pair_id": "p01",
  "role": "baseline",
  "variant": "fixed-advertising",
  "metadata": {
    "board_rev": "nrf52840-dk",
    "firmware_sha": "<commit of the flashed firmware>",
    "supply_v": 3.7,
    "ambient_temp_c": 23.5,
    "phone_model": "<model>",
    "os_version": "<version>",
    "phase": "pilot"
  },
  "markers": {
    "state_channels": [0, 1],
    "states": {"0": "sleep", "1": "advertising", "2": "connected"},
    "events": {"2": "button", "3": "find"}
  }
}
```

The values above only show the shape of the file. `capture` is relative to the manifest. Every `metadata` field is required; `phase` is `pilot` or `formal-frozen`, and a bench run with no phone writes `none` for the two phone fields. An optional `board_id` names the physical board. The six fields from `rq` to `variant` are needed by `compare` and can be left out for a standalone capture such as the 24-hour mixed-use run. Optional `sample_period_s` overrides the period inferred from the timestamps, and optional `notes` is copied into the summary.

### Logic markers

The firmware drives PPK2 logic inputs so the analysis can tell what the tag was doing:

- `state_channels` lists the channels that carry a binary state code, least significant first. `states` names each code. With channels `[0, 1]`, code 2 means D1 high and D0 low.
- `events` maps a channel to an event name. The firmware holds the channel high for as long as the event lasts.

Which GPIO drives which PPK2 channel is not fixed yet, so each manifest states its own mapping. A manifest with no `markers` block treats the capture as one state called `run`.

## What `summarize` computes

Each sample is charged for one sample period. The Power Profiler stores the average current of each period when it records below 100 kHz, so this sum is the charge. Samples the export left out add nothing, and the summary reports them as `gap_count` and `gap_s`.

Every sample belongs to one group: its state plus the set of events active at that moment. For each state, `background_ua` is the mean current of the samples with no event active, and `background_charge_uc` applies that current to the whole time in the state. An event group gets only its charge above that background, as `incremental_charge_uc`. Two overlapping events form a third group (`["button", "find"]`), so the overlap is counted once. Background plus increments add up to the total; `unattributed_charge_uc` holds the remainder and is zero unless a state never had a quiet sample.

A logic channel that changed inside one averaged sample is exported as `X`. It counts as high, and `marker_mixed_samples` says how often that happened. A channel exported as `-` counts as low and is tallied in `marker_undriven_samples`.

Charge is in microcoulombs (µA·s). `charge_mah` divides by 3.6 × 10⁶.

## What `compare` computes

`compare` groups summaries by `rq` and `condition`, pairs them by `pair_id`, and refuses a pair whose two runs differ in `board_rev`, `board_id`, `supply_v`, `phone_model`, `os_version` or `workload`. It reports the mean within-pair difference (candidate minus baseline) of `--metric`, which defaults to `total.charge_uc`, and the relative change, each with a 95% bootstrap-t interval that resamples whole pairs.

The output carries `board_revs` and both sets of firmware SHAs. `phase` is `formal-frozen` only when every run is, and `meets_min_pairs` is true from 10 pairs up.

The interval is studentized because the percentile bootstrap is too narrow at this sample size. In a simulation with normal differences and 10 pairs (4000 trials), the percentile interval covered the true mean 90.7% of the time and the bootstrap-t interval 95.0%. With lognormal differences both fell short, at 81% and 92%, so check the within-pair differences for strong skew before quoting an interval.

## Wake-rate sweep and break-even (RQ1)

RQ1 asks at what rate of unwanted wakes the interrupt-driven wake policy stops saving charge over periodic polling. The bench answers it with a sweep: each matched pair runs the polling baseline and the interrupt candidate against the same trigger schedule, and the sweep repeats that at several trigger rates.

### Trigger schedules

A schedule lists when the replay rig fires a wake trigger, in whole milliseconds from the start of a run:

```json
{
  "schema": 1,
  "schedule_id": "wake-sweep-random-3ph-s1",
  "duration_ms": 3600000,
  "min_gap_ms": 5000,
  "source": {"type": "generated", "pattern": "random", "seed": 1},
  "times_ms": [91250, 402117, 610554]
}
```

`sweep` writes one schedule per rate:

```sh
uv run pocketpet-analysis sweep workloads --rates 0 6 12 24 48 --duration-s 3600 --min-gap-ms 5000 --seed 1
```

The numbers in that command are examples. The rates, the run length, and the gap are pilot parameters that have not been chosen. Each schedule holds exactly `rate × duration` triggers, so a rate that does not give a whole number is refused. `--pattern random` (the default) places them at random and `--pattern periodic` spaces them evenly. Either way no trigger falls within `--min-gap-ms` of another, of the start, or of the end. Set the gap to at least the time the tag needs to finish handling one wake. Include rate 0: it measures the saving the other rates are compared against.

`import-schedule` turns recorded interrupt times into a schedule, so a desk or bag-carry recording can be replayed on the bench:

```sh
uv run pocketpet-analysis import-schedule bag-walk.csv --schedule-id bag-walk --duration-s 1800 --min-gap-ms 5000 -o workloads/bag-walk.schedule.json
```

The recording is a CSV with a `time_ms` column, in order, counted from the start of the recording. A trigger closer than the gap to the one kept before it is dropped, and `source.dropped_triggers` records how many were. How the tag will log these timestamps is not designed yet, so this input format is provisional.

A run that replays a schedule names it in the manifest's `workload` field, using the `schedule_id`.

### Try it on synthetic data

```sh
uv run pocketpet-analysis sweep demo/schedules --rates 0 6 12 24 48 --duration-s 1800 --min-gap-ms 5000 --seed 1
uv run pocketpet-analysis synth demo/runs --schedules "demo/schedules/*.json" --pairs 10 --seed 1
uv run pocketpet-analysis summarize "demo/runs/*.json" --output-dir demo/summaries
uv run pocketpet-analysis breakeven "demo/summaries/*.json" --schedules "demo/schedules/*.json" --seed 1
```

The synthetic polling run draws 20 µA whatever the triggers do. The synthetic interrupt run idles at 8 µA and adds 3000 µA for 1 s per trigger. These are arbitrary round numbers, chosen so the two policies meet at 14.4 triggers per hour. `breakeven` should report a rate near that, a saving near 12 µA, and about 3000 µC per trigger. Delete `demo/` afterwards.

### What `breakeven` computes

For every pair it takes the difference in mean current, candidate minus baseline, and the trigger rate of the schedule the pair replayed. It fits a straight line through the differences against the rate and reports:

- `saving_at_zero_ua`, the candidate's saving with no triggers (the line's intercept, sign reversed);
- `charge_per_trigger_uc`, what one trigger costs the candidate (the slope over one hour);
- `break_even_rate_per_h`, the rate where the line crosses zero;
- `rates`, the measured mean difference at each rate with its own interval, next to the fitted value.

Each figure has a 95% bootstrap-t interval. Whole pairs are resampled, and only among pairs measured at the same rate, so every resample keeps the sweep's design.

`breakeven` warns when:

- the break-even rate lies outside the measured rates, so it is an extrapolation;
- the fitted line misses a rate's own interval, which suggests the cost per trigger is not constant (wakes that overlap at high rates would do this);
- the slope's interval reaches zero. The break-even rate then has no bounded interval and `break_even_ci` is `null`;
- the saving with no triggers is not distinguishable from zero;
- a run's length differs from its schedule's by more than 1%.

The trigger rate comes from the schedule, not from the capture. Nothing checks yet that the tag woke once per trigger, because the firmware has no wake marker.

The interval was chosen by simulation, as for `compare`. With five rates, ten pairs per rate, and normal noise, it covered the true break-even rate in 94.3% and 94.9% of 2000 trials at two noise levels. With lognormal noise it covered 92.7%. With three pairs per rate it covered 97.7% at low noise and 93.4% at high noise, and in the high-noise case 3.5% of trials had no bounded interval. A percentile interval covered 85% to 94% in the same designs.

## Other commands

`response` scores timing trials against the response targets. It reads a CSV with `run_id` and `latency_ms` columns, treats a blank latency as a timeout, and counts timeouts as failures:

```sh
uv run pocketpet-analysis response trials.csv --threshold-ms 150
```

Its interval is a percentile bootstrap over whole runs, which is approximate with few runs.

`budget` converts a cell capacity and runtime target into an average current, and compares a summary against it:

```sh
uv run pocketpet-analysis budget --capacity-mah 100 --days 60 --summary run.summary.json
```

Pass the measured usable capacity once it exists. `covers_24h` is false for a shorter capture, whose `projected_daily_mah` is only an extrapolation.

## Limits

- The reader handled about 0.5 million rows per second on the development laptop, so a 24-hour capture at 1 kHz takes roughly three minutes. A 24-hour export at 100 kHz is too large to process this way.
- The Power Profiler records currents below 0.2 µA as zero.
- Logic channels other than those named in the manifest are ignored.

The export format was checked against [`exportChartAction.ts`](https://github.com/NordicSemiconductor/pc-nrfconnect-ppk/blob/aff05f489d52dfa062bb03184224ec45aa9ac5aa/src/actions/exportChartAction.ts) in Power Profiler 4.4.1.
