# Firmware

> **Status: Planned / scaffolded.** No nRF Connect SDK / Zephyr workspace, board overlays, or C source files are committed yet.

## Target Platforms

- **Bench bring-up & debugger-isolated fallback:** Nordic `nRF52840 DK`
- **Planned compact tag:** `Raytac MDBT50Q-1MV2` (nRF52840 BLE module)

## Planned Subsystems

| Module | Responsibility | Related RQ |
| --- | --- | --- |
| **Power & Clock Manager** | System-OFF/idle sleep states; LFCLK switching between external 32.768 kHz crystal and calibrated internal RC oscillator | RQ2 |
| **Motion Driver (`BMA400`)** | Configurable periodic accelerometer polling vs. hardware INT1/INT2 wakeup pin handling | RQ1 |
| **BLE Stack & Reconnection** | GATT services, phone-accepted connection-interval telemetry, fixed vs. fast-then-slow advertising schedules | RQ2, RQ3, RQ4 |
| **Display Scheduler (`SHARP Memory LCD`)** | SPI display driver, VCOM/polarity inversion maintenance, resting-image retention, and animation prioritization | RQ4 |
| **Haptics (`DRV2605L`)** | I2C haptic trigger for nearby find alerts and feedback patterns | RQ3, RQ4 |
| **Event Markers & Replay Hooks** | Deterministic workload execution and logic-pin toggles synchronized to Nordic PPK2 captures | All |

## Build & Flashing

Build instructions (`west build` / `west flash`), Devicetree overlays, and pinout mappings will be added here once the Zephyr / nRF Connect SDK project is initialized.

See [../README.md](../README.md) and [../docs/architecture.md](../docs/architecture.md) for system targets and measurement constraints.
