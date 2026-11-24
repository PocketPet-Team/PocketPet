# Companion & Test Applications

> **Status: Planned / scaffolded.** No Xcode / Swift project or source files are committed yet.

## Scope

Companion experiences and experimental BLE instrumentation for **iPhone (iOS)** (with future **macOS** companion support).

## Planned Features & Test Harness Capabilities

- **BLE Connection Telemetry (RQ2):** Discover and connect to PocketPet tags, negotiate/observe phone-accepted BLE connection intervals, and log active parameters alongside timestamps.
- **Separation & Reconnection Trials (RQ3):** Support locked-phone separation trials and automated logging of link-loss time, phone return time, link-restoration latency, and attempt timeouts.
- **Nearby Find Trials (RQ3 / RQ4):** Trigger foreground find requests at controlled distances (1 m, 5 m, 10 m) across line-of-sight and in-bag conditions while logging app state and time since link loss.
- **State Freshness & Routine Sync (RQ4):** Schedule deterministic routine state transfers and verify that PocketPet honors state-freshness bounds while prioritizing user-triggered button and find events.

Build requirements, bundle configuration, and test procedures will be documented here once the Xcode project is added.

See [../README.md](../README.md) and [../docs/architecture.md](../docs/architecture.md) for overall experiment requirements.
