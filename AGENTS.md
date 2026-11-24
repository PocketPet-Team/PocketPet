# AGENTS.md — PocketPet Repository Guide

Instructions for AI coding and documentation assistants working inside the public `PocketPet` repository.

## 1. Repository Status & Truthfulness Rules

- **Current state:** The portable C pet state machine builds and runs through the host CMake project in `firmware/host/`. The nRF Connect SDK / Zephyr application, KiCad design, Swift/Xcode project, and PPK2 data collection are planned.
- **Never fabricate implementation details:** Do not invent file paths, pin numbers, GPIO assignments, build/flash commands, test outputs, measured currents, power savings, statistical significance, or completed prototype milestones.
- **Separate plans from measurements:** Clearly label target budgets, planned hardware revisions, and pilot parameters as *planned* or *pending* until actual code, hardware schematics, or committed experiment outputs verify them.

## 2. Repository Map

| Path | Ownership & Purpose |
| --- | --- |
| [`firmware/README.md`](firmware/README.md) | nRF52840 / Raytac MDBT50Q-1MV2 embedded firmware (power states, BMA400, BLE, SHARP Memory LCD, DRV2605L, PPK2 GPIO markers) |
| [`hardware/README.md`](hardware/README.md) | KiCad schematics/PCBs versioned by board revision, 3D enclosure CAD, and bench test rig wiring |
| [`apps/README.md`](apps/README.md) | iOS companion / experimental test app (and future macOS app) for BLE logging and find/reconnection trials |
| [`experiments/README.md`](experiments/README.md) | STM32F103 isolated replay triggers, workload traces, PPK2 charge integration & bootstrap analysis scripts, compact processed summaries |
| [`docs/README.md`](docs/README.md) & [`docs/architecture.md`](docs/architecture.md) | System block diagram, methodological commitments, and planned protocol/pinout specifications |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Branching, PR checklist, KiCad file hygiene, and experiment metadata rules |

## 3. Engineering & Research-Method Invariants

Preserve these methodological commitments when implementing firmware, companion app instrumentation, bench replay tools, or analysis scripts unless the team explicitly updates the protocol:

1. **Power Budget Basis:**
   - Nominal reference: 100 mAh cell over 60 days = ~1.67 mAh/day (~69.4 µA average).
   - Prototype budget must use **measured usable cell capacity at cutoff** divided by 60 days, compared against integrated charge over a defined 24-hour mixed-use workload and checked with a separate timed full-to-cutoff discharge.
2. **Matched-Pair Experimental Controls:**
   - Every baseline–candidate comparison must run on the same physical board, supply voltage, phone/OS, command sequence, and feedback settings.
   - **RQ1 (Motion Sensing):** Record physical desk, graded bag-carry, and labeled-pickup captures on battery power to collect missed pickups, unnecessary wakes/hour, and interrupt timestamps. On the bench, keep the BMA400 powered in active sensing mode and replay recorded wake schedules and wake-rate sweeps via isolated triggers to measure the break-even wake rate.
   - **RQ2 (Clock & BLE Connection Interval):** On the same nRF52840 board, verify the active LFCLK (external 32.768 kHz crystal vs. calibrated internal RC at a supported calibration interval), log the phone-accepted connection interval, hold peripheral latency and TX power fixed, and compare long-interval charge savings within and across clocks.
   - **RQ3 (Advertising & Reconnection):** Start fixed and fast-then-slow advertising at the same initial rate; lock the phone during matched separations; test returns before and after the rate switch; measure charge while apart, time to link restoration, and timeouts.
   - **RQ4 (Display & Transfers):** Test resting-image retention and batched routine transfers individually and together while holding animations, haptics, and state freshness equivalent and prioritizing button and find requests.
3. **Response Criteria & Pilot Freeze:**
   - Targets: visible reaction ≤ 150 ms for ≥ 95% of button presses; vibration ≤ 2 s for ≥ 95% of nearby find requests on an established link. Count timeouts as failures.
   - Set pickup detection, state freshness, and reconnection thresholds during pilot runs and freeze them before formal comparisons.
4. **Power Measurement & Statistical Rigor:**
   - Profile with Nordic PPK2 upstream of the `TPS63900` regulator at the battery input with the SWD/DK debugger isolated so peripherals, driver, radio, and regulator losses are all captured.
   - Verify the PPK2 against known precision loads, log supply voltage and ambient temperature (`PCT2075`), and mark firmware events.
   - Attribute each interval to one operating state and add only incremental wake/interaction charge above that state's background draw so overlapping events are never double-counted.
   - Run at least 10 randomized matched baseline–candidate pairs per representative condition, report 95% confidence intervals (by resampling whole runs / pairs), and label all outputs by `board_rev` and firmware commit SHA. An unfinished discharge establishes only elapsed runtime.

## 4. Public Repository & Privacy Rules

- **Keep internal/personal records out of Git:** Never commit personal email addresses, phone numbers, student IDs, grant/application IDs, private cloud links, API keys/tokens, or budget figures.
- **Keep raw high-volume captures out of Git:** Do not commit `.ppk2` dumps or large raw capture files (`experiments/data/raw/` is gitignored). Commit reproducible scripts, trace definitions, and compact processed summaries.
- **Language:** Write all code, comments, documentation, commit messages, and PRs in English unless instructed otherwise.

## 5. Editing & Verification Workflow

- Inspect existing files in the target directory before adding new modules or changing interfaces.
- When adding a build system, schematic revision, or experiment pipeline, update the corresponding module `README.md` (and `docs/`) with exact, verified build/test instructions.
- Run local sanity checks (build/tests when present, markdown link integrity, `.gitignore` cleanliness) before pushing changes.
