# Firmware

> **Status:** The portable pet state machine, the advertising policy, and their host replays are available. The nRF Connect SDK / Zephyr application is planned.

## Run on macOS

From the repository root, use a C11 compiler such as Apple Clang from the Xcode Command Line Tools and CMake 3.20 or newer.

```sh
cmake -S firmware/host -B build/pet-host
cmake --build build/pet-host
ctest --test-dir build/pet-host --output-on-failure
./build/pet-host/pet_replay
./build/pet-host/adv_replay
```

CI runs the same build and tests on Linux and macOS with strict warnings, AddressSanitizer, and UndefinedBehaviorSanitizer.

The replay connects at time zero and advances the simulated clock by 30 minutes. A button press then brings mood to 98 and returns a display refresh. A routine sync becomes pending, a connected Find returns a haptic action, and the final event flushes the pending state update.

### Portable state machine

- [`core/pet_state.h`](core/pet_state.h) defines the events, actions, and timestamp contract. [`core/pet_state.c`](core/pet_state.c) implements the state machine in C11 using only the standard library.
- Mood starts at 100, drops by one for each elapsed five-minute period, and gains four after a button press. These are prototype rules. Mood stays in the range 0–100. Each event accounts for elapsed time in one calculation and preserves any partial period.
- Repeated routine sync requests coalesce into one pending update. A connected caller can flush that update after handling button and Find events. Pending updates survive link loss. A Find event produces a haptic action only on an established link.
- The caller supplies monotonic millisecond timestamps and dispatches returned actions. The replay validates action selection and order with a simulated clock. Physical display, radio, and haptic timing require device tests.

### Advertising policy

- [`core/adv_policy.h`](core/adv_policy.h) decides the advertising rate while the tag has no link (RQ3). [`core/adv_policy.c`](core/adv_policy.c) implements it in C11 using only the standard library.
- A policy advertises at a fast interval after link loss and moves to a slow interval once a configured time has passed. Setting the slow interval equal to the fast one gives the fixed-rate baseline, so the two policies of a matched pair start at the same rate.
- Intervals are in Bluetooth units of 0.625 ms and must lie between 20 ms and 10.24 s. The intervals and the switch time are parameters. Their pilot values are not chosen yet.
- The caller reports link loss, the switch timer, and connection with monotonic millisecond timestamps. Each step returns whether to restart advertising at a new interval and whether to arm or cancel the switch timer. A timer that fires early or after reconnection does nothing.
- `adv_replay` prints, for each separation, how many advertising events the fixed and fast-then-slow policies schedule and the longest wait for the next event when the phone returns. Run it without arguments for an example, or pass your own values:

  ```sh
  ./build/pet-host/adv_replay FAST_MS SLOW_MS FAST_DURATION_S SEPARATION_S...
  ```

  The counts ignore the random 0 to 10 ms delay a controller adds to each event, so they are upper bounds. They count radio events only. Charge per event and reconnection time must be measured on the device.

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
