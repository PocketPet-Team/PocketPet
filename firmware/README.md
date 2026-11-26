# Firmware

> **Status:** The portable pet state machine, the advertising policy, and their host replays are available. A first Zephyr application for the nRF52840 DK builds but has not run on hardware yet.

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

## Zephyr application

[`app/`](app/) runs both portable cores on the nRF52840 DK with nRF Connect SDK v3.4.2.

- The DK's Button 1 is the pet button. LED1 toggles on each display refresh and LED2 lights for 500 ms on a Find request. They stand in for the SHARP display and the DRV2605L until those drivers exist.
- The tag advertises as `PocketPet` and follows the advertising policy: fast after boot or link loss, slow after the configured time. Advertising restarts after the stack releases the old connection.
- A routine state update is queued every 300 s and sent as a notification once a peer subscribes. An update queued while nobody is subscribed waits for the next subscription.
- The log reports the running LF clock source after Bluetooth starts, and the connection interval, latency, and supervision timeout on connection and on every parameter update.
- The GATT service is described in [`docs/ble-protocol.md`](../docs/ble-protocol.md). No characteristic requires pairing yet, so any nearby central can read the mood and trigger Find.

All inputs (button interrupt, Bluetooth callbacks, timers) go through one queue and are applied to the state machines from a single work item, so the cores see events in order and never run concurrently.

The advertising intervals, the switch time, the routine sync period, and the Find indication length are Kconfig options in [`app/Kconfig`](app/Kconfig). Their defaults make the application run; they are not pilot values.

### Build

Install the SDK and toolchain with [nRF Util](https://www.nordicsemi.com/Products/Development-tools/nRF-Util):

```sh
nrfutil install sdk-manager
nrfutil sdk-manager install v3.4.2
```

Then open the toolchain environment and build from the SDK directory (`C:\ncs\v3.4.2` on Windows, `~/ncs/v3.4.2` on Linux, `/opt/nordic/ncs/v3.4.2` on macOS):

```sh
nrfutil sdk-manager toolchain launch --ncs-version v3.4.2 --shell
west build -b nrf52840dk/nrf52840 -d <build-dir> <repo>/firmware/app
```

Zephyr does not support spaces in source or build paths. If the clone path contains one, build through a link without spaces (a directory junction on Windows, a symlink elsewhere).

For the RQ2 comparison, build a second image that runs the LF clock from the calibrated RC oscillator:

```sh
west build -b nrf52840dk/nrf52840 -d <rc-build-dir> <repo>/firmware/app -- -DEXTRA_CONF_FILE=clock-rc.conf
```

With NCS v3.4.2 this image sets `CONFIG_CLOCK_CONTROL_NRF_K32SRC_RC=y` and calibrates every 4000 ms (`CONFIG_MPSL_CALIBRATION_PERIOD`). The default image uses the 32.768 kHz crystal. Check `zephyr/.config` in the build directory to confirm which one a build used.

Both images build without warnings. The default image uses 135,564 B of flash and 25,896 B of RAM.

### Flash

`west flash -d <build-dir>` is the standard command for the DK, but it has not been run against a board yet. It needs SEGGER J-Link installed. Logging over the DK's UART is on for bring-up and adds current draw, so disable `CONFIG_LOG` before power measurements.

See [../README.md](../README.md) and [../docs/architecture.md](../docs/architecture.md) for system targets and measurement constraints.
