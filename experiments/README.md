# Experiments & Power Analysis

> **Status: Planned / scaffolded.** No replay controller firmware, workload logs, or analysis scripts are committed yet.

## Planned Directory Layout

```text
experiments/
├── replay-controller/   # STM32F103 firmware driving LTV-817 optocouplers and LED video markers
├── workloads/           # Trace definitions (desk, graded bag-carry, pickup, active-use, 24h mixed-use)
├── analysis/            # Python scripts for PPK2 charge integration, event attribution, and 95% CIs
└── data/                # Compact processed CSV/JSON summaries (data/raw/ is gitignored)
```

## Measurement & Validation Protocol

1. **Calibration:** Verify Nordic PPK2 accuracy against 0.1% precision load resistors (100 kΩ, 47 kΩ, 1 kΩ, 100 Ω) before formal runs. Record ambient temperature (`PCT2075`) and supply voltage for every session.
2. **Isolation:** Measure battery-side current upstream of the `TPS63900` regulator with the SWD/DK debugger physically disconnected and the measurement rig powered separately.
3. **Physical vs. Bench Capture (RQ1):** Capture real battery-powered desk, graded bag-carry, and labeled-pickup traces to log missed pickups, unnecessary wakes/hour, and interrupt timestamps; replay recorded wake schedules and wake-rate sweeps on the bench with the `BMA400` active.
4. **Video Timing Verification:** Film physical button contact alongside the first changed LCD frame (≤ 150 ms target), and film find commands using an LED indicator calibrated against physical ERM motor onset (≤ 2 s target).
5. **Paired Statistics & Runtime Validation:**
   - Freeze pilot-tuned thresholds prior to formal comparisons.
   - Run ≥ 10 randomized matched baseline–candidate pairs per representative condition and report 95% confidence intervals via whole-run / within-pair resampling.
   - Attribute charge without double-counting overlapping wakes and interactions.
   - Check modeled daily charge against a continuous 24-hour mixed-use run, and separately run a timed full-to-cutoff discharge on the compact tag.

## Required Metadata per Run

Every committed summary table or dataset should record:
- `board_rev` (e.g., `nrf52840-dk`, `compact-revA`)
- `firmware_sha` (exact Git commit)
- `supply_v` and `ambient_temp_c`
- `phone_model` and `os_version`
- `phase` (`pilot` or `formal-frozen`)

See [../AGENTS.md](../AGENTS.md) and [../docs/architecture.md](../docs/architecture.md) for methodological invariants.
