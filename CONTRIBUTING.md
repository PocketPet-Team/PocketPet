# Contributing to PocketPet

Thanks for contributing to PocketPet. Because this repository spans embedded firmware, custom PCB hardware, iOS/macOS companion apps, and power-profiling experiments, please follow the conventions below so teammates can reproduce builds and measurements cleanly.

## Branching & Commits

- Create a focused branch off `main` for new work:
  - `feat/<area>-<topic>` — new features or modules (e.g., `feat/fw-bma400-wake`, `feat/ios-find-harness`)
  - `fix/<area>-<topic>` — bug fixes
  - `hw/<rev>-<topic>` — schematic, PCB layout, or enclosure CAD updates (e.g., `hw/revA-ppk2-pads`)
  - `exp/<rq>-<topic>` — workload definitions, replay scripts, or analysis updates (e.g., `exp/rq2-clock-sweep`)
  - `docs/<topic>` — documentation updates
- Keep commits small, single-purpose, and written in clear imperative English (e.g., `fw: add BMA400 motion interrupt driver`).

## Pull Requests

1. Use the [Pull Request Template](.github/pull_request_template.md) and reference any related issues created from the [Issue Templates](.github/ISSUE_TEMPLATE/).
2. Update the relevant module documentation (`firmware/`, `hardware/`, `apps/`, `experiments/`, or [docs/README.md](docs/README.md)) whenever pinouts, BLE characteristics, build steps, or experiment schemas change.
3. Verify builds, unit tests, and link checks locally before requesting review.
4. Keep personal emails, student IDs, internal administrative IDs, private links, and credentials out of commits and PR descriptions.

## Hardware & KiCad Hygiene

- Keep board revisions isolated under versioned directories (see [hardware/README.md](hardware/README.md)), such as `hardware/pcb/compact-revA/`.
- Commit clean KiCad source files (`.kicad_pro`, `.kicad_sch`, `.kicad_pcb`), exported BOM/CPL files, and 3D STEP/STL enclosure models.
- Never commit KiCad auto-backups, lock files, or temporary caches (`.gitignore` blocks `*.bak`, `*-backups/`, `*.lck`, `*.kicad_prl`, and `fp-info-cache`).

## Experiment & Measurement Hygiene

- Commit workload traces, STM32 replay code, and analysis scripts alongside compact processed summaries (see [experiments/README.md](experiments/README.md)).
- Keep large raw PPK2 trace captures out of Git (`experiments/data/raw/` and `*.ppk2` are gitignored).
- Every recorded dataset or experiment summary must include metadata:
  - `board_rev` (e.g., `nrf52840-dk` or `compact-revA`)
  - Firmware commit SHA
  - Supply voltage and ambient temperature (`PCT2075` log)
  - Companion phone model and OS version
  - Status (`pilot` vs. `frozen-formal`)

See [AGENTS.md](AGENTS.md) for the project's full engineering and measurement invariants.
