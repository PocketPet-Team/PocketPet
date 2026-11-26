# Documentation Index

Technical documentation and specifications for PocketPet.

## Available Documents

- [System & Measurement Architecture](architecture.md) — Hardware/firmware block diagram, RQ1–RQ4 experimental controls, and power validation methodology.
- [Pet state machine on macOS](../firmware/README.md#run-on-macos) — Build, run, and test the portable firmware core on a Mac.

- [BLE protocol](ble-protocol.md) — Provisional GATT service, characteristics, and advertising behavior of the Zephyr application.
- [PPK2 logic markers](ppk2-markers.md) — Provisional state and event lines the firmware drives for charge attribution, with the bench wiring on the DK.

## Planned Specifications

The following documents will be added as bring-up and design decisions stabilize:

- `hardware-pinout.md` — `nRF52840 DK` and `compact-revA` GPIO, SPI, I2C, wake-pin, and final PPK2 logic-marker pin mappings.
- `bench-protocol.md` — Step-by-step wiring, calibration load checks, video timing alignment, and PPK2 export procedures.

## Related Repository Files

- [Project README](../README.md)
- [AI Assistant Guide](../AGENTS.md)
- [Firmware Module](../firmware/README.md) · [Hardware Module](../hardware/README.md) · [Apps Module](../apps/README.md) · [Experiments Module](../experiments/README.md)
