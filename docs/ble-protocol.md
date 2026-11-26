# BLE protocol

> **Status: Provisional.** This describes the Zephyr application in [`firmware/app/`](../firmware/app/). It builds but has not been tested against a phone, and the UUIDs and value formats may change before the iPhone test app depends on them.

## Advertising

The tag advertises connectable, undirected legacy advertising with the complete name `PocketPet`. The scan response carries the 128-bit service UUID.

The advertising interval follows the policy in [`firmware/core/adv_policy.h`](../firmware/core/adv_policy.h): a fast interval after boot or link loss, then a slow interval once the fast period ends. Advertising stops when a central connects. Only one connection is allowed.

## PocketPet service

All UUIDs share one random base and differ in the first 32 bits.

| Item | UUID | Properties | Value |
| --- | --- | --- | --- |
| Service | `d0f80001-b8bf-4fa6-a92b-fad4ab69a07d` | | |
| State | `d0f80002-b8bf-4fa6-a92b-fad4ab69a07d` | Read, Notify | 2 bytes: format version (`0x01`), mood (0 to 100) |
| Find | `d0f80003-b8bf-4fa6-a92b-fad4ab69a07d` | Write, Write Without Response | 1 byte: `0x01` |

A read of State returns the mood as of the last event the tag processed. Mood decays with time, so the value can be older than the read.

A notification on State is a routine update. One becomes due every routine sync period and is sent once a central has enabled notifications. Updates that become due while no central is subscribed collapse into one.

The tag can hold a routine update for a configured time so that later updates share its notification. The hold is zero by default, which sends each update when it is due. With a hold, the central sees mood changes up to that much later, and a Find write makes the tag send a held update early. The policy is in [`firmware/core/sync_policy.h`](../firmware/core/sync_policy.h).

Writing `0x01` to Find starts the Find indication if the link is up. Any other length or value is rejected with an ATT error: Invalid Attribute Value Length for a length other than 1, Value Not Allowed for another byte, and Invalid Offset for a non-zero offset.

## RQ2 connection parameters

RQ2 builds expose a read-only characteristic at `d0f80004-b8bf-4fa6-a92b-fad4ab69a07d`. It returns 16 bytes for the current connection. Multi-byte integers are little-endian.

| Offset | Type | Field |
| --- | --- | --- |
| 0 | u8 | Format version, currently 1 |
| 1 | i8 | Configured controller TX power in dBm |
| 2 | u16 | Requested interval in 1.25 ms units |
| 4 | u32 | Active connection interval in µs from the stack |
| 8 | u16 | Active peripheral latency in connection events |
| 10 | u16 | Active supervision timeout in 10 ms units |
| 12 | u32 | Number of parameter-update callbacks since boot, modulo 2³² |

Read the characteristic on the same uninterrupted link immediately before and after a charge window. Check that the active parameters meet the trial definition and that the counter stays constant. The read itself uses the radio, so keep it outside the integration window. The characteristic works independently of UART logging. A reconnect starts a new trial.

## Security

No characteristic requires pairing or encryption yet. Any central in range can read the mood and trigger Find.
