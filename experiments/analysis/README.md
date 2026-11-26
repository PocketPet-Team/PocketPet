# PocketPet analysis

Python tools that turn a Nordic PPK2 capture into a compact charge summary and compare matched baseline and candidate runs.

> **Status:** The pipeline is tested against synthetic captures only. No PPK2 capture from PocketPet hardware has been processed yet, and the logic-marker pin assignment is still to be decided with the firmware and bench rig.

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

1. Plan the order. `uv run pocketpet-analysis plan --pairs 10 --seed <n>` prints which role runs first in each pair. Record the seed.
2. Capture with the PPK2 and export CSV from the Power Profiler with timestamp, current, and one of the digital options selected. Put the export under `experiments/data/raw/`, which Git ignores.
3. Write a manifest next to the capture (format below).
4. Run `summarize` and commit the summary JSON under `experiments/data/`.
5. Run `compare` on the summaries of one research question.

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
