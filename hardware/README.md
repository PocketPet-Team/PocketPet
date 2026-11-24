# Hardware

> **Status: Planned / scaffolded.** No KiCad schematics, PCB layouts, Gerber/BOM packages, or 3D CAD enclosure files are committed yet.

## Planned Directory Layout

```text
hardware/
├── pcb/          # KiCad projects versioned by board revision (e.g., compact-revA/)
├── enclosure/    # 3D-printed keychain & fridge-magnet mechanical housing (STEP / STL)
└── bench-rig/    # Wiring diagrams for nRF52840 DK, TPS63900EVM, PPK2, and optocoupler triggers
```

## Target Compact-Tag Architecture & Co-Design Requirements

- **Compute & BLE Module:** `Raytac MDBT50Q-1MV2` (`nRF52840`)
- **External LF Clock (RQ2):** `Abracon ABS07-32.768KHZ-9-T` 32.768 kHz crystal with load capacitors so firmware can benchmark external XTAL vs. internal RC oscillator on identical hardware
- **Motion Sensing (RQ1):** `Bosch BMA400` (12-LGA) with dedicated interrupt line(s) routed to `nRF52840` wake-capable GPIO
- **Display Interface:** 2.54 mm header interconnect mating the `Adafruit 3502` 1.3" SHARP Memory LCD breakout
- **Haptics:** `TI DRV2605L` I2C haptic driver paired with `Vybronics VCLP1020B002L` ERM motor
- **Power Regulation & Battery:** `TI TPS63900` 3.3 V buck-boost regulator fed by an `Adafruit 1570` 3.7 V 100 mAh LiPo via JST-PH
- **Instrumentation & Isolation:**
  - Dedicated battery-input measurement pads upstream of the `TPS63900` regulator for Nordic PPK2 ammeter-mode profiling
  - Removable 2×5 1.27 mm SWD debug header (`Adafruit 4048` footprint) so debugger current is isolated during measurements
  - Breakout power LEDs disabled on bench sensor boards (`SEN-21208`) to avoid parasitic draw

Every PCB revision must carry a distinct `board_rev` identifier on silkscreen and in committed files so measurement datasets trace cleanly to exact hardware revisions.

See [../README.md](../README.md) and [../docs/architecture.md](../docs/architecture.md) for the overall system and bench setup.
