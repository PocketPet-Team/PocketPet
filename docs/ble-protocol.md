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

A notification on State is a routine update. The tag queues one every routine sync period and sends it once a central has enabled notifications. Updates that queue up while no central is subscribed collapse into one.

Writing `0x01` to Find starts the Find indication if the link is up. Any other length or value is rejected with an ATT error: Invalid Attribute Value Length for a length other than 1, Value Not Allowed for another byte, and Invalid Offset for a non-zero offset.

## Security

No characteristic requires pairing or encryption yet. Any central in range can read the mood and trigger Find.
