# Bench analysis

Run the commands below from `experiments/analysis/`. Start with a [run manifest](../experiments/analysis/README.md#run-manifest) and add the sections needed for the run. All numbers in the examples are illustrative. The tests use synthetic CSV exports. Board measurements and frozen pilot limits are pending.

## Synchronize a trial

Use the timestamp column of the PPK2 export as the clock for each run, in milliseconds. Align phone, rig and video timestamps to that clock before entering them. Keep the original observations, synchronization reference and trial order with the raw capture. Copy the [marker map](../firmware/app/ppk2-markers.json) for the flashed firmware into the manifest. Start recording before the first relevant edge and continue past the last outcome or deadline.

The optional `observations` object accepts `rq3`, `rq4` and `responses` independently. For these sections, export continuous, uniformly sampled data with resolved levels on the lines the trial needs. An averaged transition marked `X`, an undriven line or a dropped sample makes edge timing ambiguous. RQ3 needs the state lines. RQ4 needs all mapped lines to identify concurrent events. Ordinary charge summaries still report capture-quality counts.

### RQ3 separation and return

```json
{"observations": {"rq3": {"timeout_ms": 5000, "trials": [
  {"depart_ms": 1000, "return_ms": 17000}
]}}}
```

Record when the locked phone leaves and returns to range. The tag may keep its link until supervision expires. The charge window starts at physical departure and ends at return, including the appropriate fraction of each boundary sample. The tag must have an established link at departure and lose it before return. Recovery ends at the first observed transition back to `connected`. A recovery at the deadline counts as on time. A timeout requires observation through that deadline.

Keep before-switch and after-switch returns in separate named conditions. Match the initial advertising interval, clock, TX power, physical board, phone, lock state, feedback and separation schedule for both policies. Freeze `timeout_ms` during the pilot. The per-trial output includes the state at return. The run reports total charge apart, timeout count and mean latency among successful recoveries. A run with no recovery has a null mean latency. Report timeouts alongside any latency comparison.

Record these controls under `metadata` with `board_id`, `initial_adv_interval_units`, `lfclk`, `tx_power_dbm`, `phone_locked`, `command_sequence` and `feedback_settings`. The paired comparison checks supplied control values for equality.

```sh
uv run pocketpet-analysis summarize "raw/*.run.json" --output-dir summaries
uv run pocketpet-analysis compare "summaries/*.summary.json" --metric rq3.apart_charge_uc
uv run pocketpet-analysis compare "summaries/*.summary.json" --metric rq3.timeouts
uv run pocketpet-analysis compare "summaries/*.summary.json" --metric rq3.mean_recovery_ms
```

Use the manifest filenames from your own run plan. Compare at least ten randomized matched pairs per formal condition. Each confidence interval resamples whole pairs. An unavailable metric is reported as an error identifying the run. For a zero baseline mean the absolute difference remains defined and the relative change is null.

### RQ4 transfers and state freshness

```json
{"observations": {"rq4": {"freshness_limit_ms": 500, "updates": [
  {"due_ms": 1100, "transfer_index": 1, "received_ms": 1430},
  {"due_ms": 1300, "transfer_index": 1, "received_ms": 1430},
  {"due_ms": 1900, "received_ms": null}
]}}}
```

Record each scheduled routine update once. Match it to the first phone receipt containing its state or a newer state that supersedes it. Several due updates can share one receipt. When the associated pulse is identifiable, enter its one-based `transfer_index`. This measures the hold from due time to stack submission. The freshness check uses the full delay from due time to phone receipt. An undelivered update counts as a failure once its deadline has been observed. `max_delivered_age_ms` covers delivered updates and `max_observed_hold_ms` covers updates with a pulse index. Both are null when their population is empty.

For pulse analysis alone use `"rq4": {}`. Each high pulse reports start, end, charge above the background of each state traversed, and whether another event was active. The sum over pulse windows includes concurrent activity. The isolated mean uses only pulses with no other marked event. Two submissions sharing one high pulse are indistinguishable. A disconnect or failed submission can also end the pulse. Use the phone record to verify delivery.

Use the same update schedule, freshness limit, feedback settings and animation behavior for immediate and batched runs. Use separate conditions for the display policy held fixed in each pair. Repeat the measurement for retention alone and for retention with batching. Example comparison metrics are `rq4.transfer_count`, `rq4.window_incremental_charge_uc`, `rq4.mean_isolated_incremental_uc`, `rq4.max_observed_hold_ms` and `rq4.freshness_failures`.

### Button and nearby Find

```json
{"observations": {"responses": {"source": "physical", "trials": [
  {"kind": "button", "request_ms": 400, "response_ms": 550},
  {"kind": "find", "request_ms": 1200, "response_ms": null}
]}}}
```

For a button trial record physical contact and the first changed LCD frame. For a nearby Find trial record the phone request and calibrated motor onset. The tag must be connected at request time. Use each trial's distance and placement to label its condition. Enter every attempted trial. Use null for an observed timeout and retain the actual onset for a late response.

The DK can exercise the same pipeline with `"source": "firmware-proxy"`. Either timestamp can then reference a capture edge, for example `{"marker":"button","edge":"fall","index":1}`. Indices start at one for each marker and direction. A button rise and fall bracket firmware handling. A Find request timestamp and a haptic rise bracket the command and indication. Pair edges to the recorded stimulus explicitly so a missing response cannot shift all later pairs. Merged pulses cannot establish multiple responses. Only physical-source trials produce a physical target verdict.

```sh
uv run pocketpet-analysis response-criteria "summaries/*.summary.json" --seed 1
```

The thresholds are inclusive at 150 ms for button and 2000 ms for Find. The observed target is at least 95% on time, with late responses and timeouts in the denominator. The report gives the rate and a 95% confidence interval from resampling whole runs within each condition, role, firmware and evidence source. With one run the interval collapses to the observed rate.

## Check a precision load

Capture a steady known load and omit logic markers. Add one of the following blocks to its manifest.

```json
{"calibration": {"resistance_ohm": 47000, "tolerance_pct": 2}}
```

```json
{"calibration": {"reference_ua": 100, "tolerance_pct": 2}}
```

For a resistor, record its known resistance and the voltage measured across the load in `metadata.supply_v`. Set the allowed error before testing. Run `summarize` once per load. The `calibration` section gives expected and measured mean current, signed error in µA and percent, and a tolerance verdict. Keep the session's load summaries with its captures. The check applies no correction to later samples.

## Model a mixed-use day

Summarize a representative profile with all the states and event groups needed by the workload. Enter each state's total hours, including time spent handling events. The hours must sum to 24. Supply the cell's measured usable capacity at cutoff.

```json
{
  "workload": "example-day",
  "state_hours": {"connected": 18, "adv_slow": 6},
  "event_segments": [
    {"state": "connected", "events": ["transfer"], "count": 24},
    {"state": "connected", "events": ["haptic", "transfer"], "count": 2}
  ]
}
```

A segment is an uninterrupted span with the same state and active event set. A transfer that overlaps a haptic halfway through can contribute to several segments. Count each such span once. Omitted groups have zero segments in this workload. The model charges the event-free background for all 24 hours, then adds each group's measured mean incremental charge per segment times its daily count. Re-run `summarize` on older profiles to populate segment counts.

```sh
uv run pocketpet-analysis mixed-day profile.summary.json day.json --capacity-mah 80
uv run pocketpet-analysis mixed-day profile.summary.json day.json --capacity-mah 80 --measured-day day.summary.json
```

The second form checks integrated charge from a separate continuous 24-hour capture with the same workload name, board and firmware. It reports measured charge alongside the model and the capacity/60 allowance. Runtime still requires a timed full-to-cutoff discharge. An unfinished discharge establishes elapsed time only.

Run the executable synthetic examples and their failure cases with pytest.

```sh
uv run pytest -q tests/test_bench.py tests/test_power.py
```
