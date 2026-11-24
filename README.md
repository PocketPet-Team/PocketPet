# PocketPet

An embedded virtual pet in keychain and fridge-magnet form factor with companion mobile experiences and low-power hardware/firmware co-design research at UC Irvine (UCI UROP Research Experience Fellowship, 2026–2027).

> **Project Status: Early setup (pre-prototype).**
> The portable C pet state machine runs on a Mac with a scripted replay and unit tests. Hardware choices, research protocols, and timelines described below reflect working engineering plans subject to faculty-mentor review and pilot calibration.

## Overview & Engineering Targets

PocketPet aims to combine responsive physical interactions (button presses, motion wakeup, haptic alerts, and a persistent low-power display) with multi-week battery autonomy on a tiny LiPo cell:

- **Target Battery Budget:** A nominal 100 mAh LiPo cell over a 60-day target corresponds to roughly **1.67 mAh/day** (**69.4 µA average**). Prototype runtime projections will anchor on **measured usable cell capacity at cutoff**, checked against integrated charge over a defined 24-hour mixed-use workload and verified via a separate timed full-to-cutoff discharge.
- **Responsiveness Targets:**
  - **Button reaction:** Visible display response within **150 ms** for at least **95%** of presses.
  - **Nearby find alert:** Physical vibration within **2 s** for at least **95%** of requests on an established BLE link.
  - **Pilot-calibrated thresholds:** Pickup detection sensitivity, pet-state freshness bounds, and post-loss reconnection deadlines will be established in pilot runs and frozen prior to formal testing.

## Software Stack

This stack is the starting point for the first prototype.

| Component | Stack | Role |
| --- | --- | --- |
| [Tag firmware](firmware/README.md) | C, Nordic nRF Connect SDK (NCS), and its bundled Zephyr RTOS | Zephyr provides BLE, timers, GPIO interrupts, and power management. Keep the pet state machine portable C so it can be tested on a Mac and built into the nRF52840 firmware. Pin the NCS and toolchain versions when setting up the firmware build. |
| [iPhone test app](apps/README.md) | Swift, Core Bluetooth, and SwiftUI | Discover and connect to the tag, send Find requests, receive events, and export trial logs. Record the negotiated BLE connection interval on the tag for power comparisons. |
| [Experiment tooling](experiments/README.md) | Python and CSV | Replay timestamped workloads, integrate current traces exported from the Nordic PPK2, and compare charge use and response times across firmware configurations. |

Use event-driven updates so the tag can idle between interactions. Compute time-dependent pet state from elapsed time and schedule a timer when a state change must happen at a specific time. Prioritize button feedback and Find requests, batch routine BLE transfers within the state-freshness limit, and maintain the LCD's required VCOM inversion when retaining a resting image.

Evaluate power policies on the same board with matched workloads. Compare charge measured at the battery input while checking the button and Find response targets above. See the [measurement and validation plan](docs/architecture.md#engineering-targets--validation-plan).

## Research Questions (Battery-Life Co-Design)

| ID | Focus Area | Controlled Comparison & Metrics |
| --- | --- | --- |
| **RQ1** | Motion Sensing | Compare periodic BMA400 accelerometer polling against hardware motion-interrupt wakeup across desk, graded bag-carry, and deliberate-pickup traces; quantify missed pickups, unnecessary wakes/hour, and the break-even wake rate where unwanted wakes erase desk savings. |
| **RQ2** | Connected Operation | On the same nRF52840 board, pair an external 32.768 kHz crystal or a calibrated internal RC oscillator with two phone-accepted BLE connection intervals (holding peripheral latency and TX power fixed); test whether the clock source changes the charge saved by longer intervals. |
| **RQ3** | Advertising & Reconnection | After link loss, compare fixed-rate vs. fast-then-slow advertising starting from the same initial rate across matched separations and phone returns before and after the slow-rate switch; measure charge while apart, recovery time to link restoration, and timeouts. |
| **RQ4** | Display & Transfers | Evaluate retaining a resting display image between interactions and batching routine radio transfers, individually and together, while holding animations, haptics, and freshness constant and prioritizing button/find requests. |

## Target Hardware & Measurement Stack

| Subsystem | Bench / Bring-Up Component | Planned Compact Tag Component | Role |
| --- | --- | --- | --- |
| **Compute & BLE** | Nordic nRF52840 DK | Raytac MDBT50Q-1MV2 | Primary BLE SoC; DK also serves as debugger-isolated fallback |
| **LF Clock** | On-DK 32.768 kHz XTAL / RC | Abracon ABS07-32.768KHZ-9-T | External crystal vs. calibrated internal RC evaluation (RQ2) |
| **Accelerometer** | SparkFun SEN-21208 (BMA400) | Bosch BMA400 (12-LGA) | Motion sensing and programmable interrupt wakeup (RQ1) |
| **Display** | Adafruit 3502 SHARP Memory LCD (1.3") | Adafruit 3502 (via 2.54 mm headers) | Low-power reflective display with polarity inversion and resting-image retention |
| **Haptics** | Adafruit 2305 (DRV2605L) + ERM | TI DRV2605L + Vybronics VCLP1020B002L | Tactile vibration for nearby find requests and feedback |
| **Power & Cell** | TI TPS63900EVM + Adafruit 1570 (100 mAh LiPo) | TI TPS63900 (3.3 V) + 100 mAh LiPo | High-efficiency regulation; battery-side profiling upstream of regulator |
| **Bench Rig** | Nordic PPK2, STM32F103 + LTV-817, PCT2075, 0.1% resistors, LEDs | — | Upstream power integration, isolated workload replay, ambient temp, and video timing calibration |
| **Companion App** | iPhone test app (iOS) | iPhone / macOS companion | BLE connection-interval logging, separation/find trials, and state sync |

## Repository Structure

```text
PocketPet/
├── AGENTS.md                 # AI assistant rules, hardware/research invariants, and safety scope
├── CONTRIBUTING.md           # Team Git workflow, KiCad hygiene, and experiment logging standards
├── LICENSE                   # MIT License
├── README.md                 # Project overview, research targets, and repository index
├── .github/                  # Issue and pull request templates
├── docs/                     # System architecture and technical specifications
│   ├── README.md
│   └── architecture.md
├── firmware/                 # Portable pet state machine, host replay, and planned nRF52840 firmware
│   ├── core/                 # Portable C state machine
│   ├── host/                 # CMake replay and tests
│   └── README.md
├── hardware/                 # KiCad schematics/PCBs, 3D-printed enclosure CAD, bench wiring
│   └── README.md
├── apps/                     # iOS / macOS companion and BLE test harness applications
│   └── README.md
└── experiments/              # Workload traces, STM32 replay triggers, PPK2 analysis scripts
    └── README.md
```

- [Firmware module](firmware/README.md)
- [Hardware module](hardware/README.md)
- [Companion & test apps](apps/README.md)
- [Experiments & analysis](experiments/README.md)
- [Documentation index](docs/README.md) · [System architecture](docs/architecture.md)

## Team & Responsibilities

| Member | GitHub | Primary Focus |
| --- | --- | --- |
| **Yuchen Lin** | `@liny67-collab` | Clock and wake-pin hardware design, PPK2 rig calibration, usable cell capacity |
| **Yide Li** | `@Yide-Milo-Li` | Firmware power states, BLE stack, and reconnection policies |
| **He He** | `@hhe25387` | Repeatable pet workload and display/transfer scheduler |
| **Jiayu Yu** | — | iPhone test app, distance trials, and link-recovery testing |
| **Zhou Li** *(Faculty Mentor)* | — | Research design and methodological review (UC Irvine) |

## Contributing & License

- Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before opening pull requests or adding hardware/experiment assets.
- Use the [Issue Templates](.github/ISSUE_TEMPLATE/) and [Pull Request Template](.github/pull_request_template.md) for tracking tasks and changes.
- Licensed under the [MIT License](LICENSE).
