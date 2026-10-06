# Appendix A — PBS to BPv7 Mapping Specification
**Document ID:** PBS-BPv7-MAPPING-APPENDIX  
**Status:** Reference Draft  
**Applies To:** PBS-EDGE-ADAPTER-MV  
**References:** PBS-ENV-01 v1.3, PBS-DTN-MAP-01 v1.3, PBS-DTN-MAP-02 v1.4, IETF RFC 9171 (Bundle Protocol Version 7)

---

## A.1 Purpose

This appendix defines how the PBS Edge Adapter encapsulates one PBS-ENV-01 v1.3 envelope in one BPv7 bundle. `pbs_edge_adapter_worked_example.py` (`pbs_to_bpv7_bundle_mv`) implements Sections A.3 to A.8 and A.10. Section A.9 defines the inbound direction, which the worked example does not implement.

PBS specifications are in [PBS-PROTOCOL-OPEN](https://github.com/Pale-Blue-Systems/PBS-PROTOCOL-OPEN/tree/main/PBS-RFC-LIB). Both PBS mapping documents apply. PBS-DTN-MAP-01 (v1.3) defines the envelope-to-bundle mapping at a gateway boundary. PBS-DTN-MAP-02 (v1.4) defines endpoint mapping, lifetime and freshness, priority and QoS, service intent and security rules for BPv7 carriage.

---

## A.2 Mapping Principles

1. **One envelope, one bundle.** Each envelope maps to exactly one bundle (PBS-DTN-MAP-01 Section 5.1; PBS-DTN-MAP-02 Section 2).
2. **Opaque envelope.** The complete envelope, 44-byte header and payload, is the payload block content, unmodified (PBS-DTN-MAP-01 Sections 6.2 and 6.4).
3. **Configured addressing.** The destination EID, source node ID and report-to EID come from the Authority Context map (Section A.5).
4. **Bounded lifetime.** The bundle lifetime does not extend past the envelope's TTL (PBS-DTN-MAP-02 Section 4).
5. **Determinism.** Identical envelope bytes, Authority Context entry, configured default lifetime, sequence number and clock reading produce identical bundle bytes.

---

## A.3 PBS Envelope Fields

The adapter accepts a PBS-ENV-01 v1.3 envelope: a fixed 44-byte big-endian header followed by `Size` payload bytes. The table lists every header field and the adapter's use of it.

| Offset | Field | Type | Adapter use |
|--------|-------|------|-------------|
| 0x00 | Magic | u8, `0x10` | Validated |
| 0x01 | Priority | u8; 0 CRITICAL, 1 HIGH, 2 NORMAL, 3 LOW, 4 BULK | Validated; 5–255 rejected. Not mapped to a bundle field. |
| 0x02 | Flags | u8; `0x01` = ACK requested | Not used |
| 0x03 | Reserved | u8, `0x00` | Not used |
| 0x04 | Sequence | u16 | Not used |
| 0x06 | Reserved | u16, `0x0000` | Not used |
| 0x08 | Source ID | 16 bytes, null-padded UTF-8 | Not used |
| 0x18 | Timestamp | u64, Unix time in microseconds | Envelope age (Section A.6.2) |
| 0x20 | Size | u32, payload length in bytes | Input length must equal 44 + `Size` |
| 0x24 | TTL | u32, seconds; `0` = no expiry | Expiry check and lifetime bound (Section A.6.2) |
| 0x28 | CRC32 | u32 | Verified: IEEE 802.3 CRC-32 over bytes 0x00–0x2B with 0x28–0x2B set to zero, stored big-endian (PBS-ENV-01 Section 13) |

The header contains no destination, scope, authority or message identifier field, and no version field other than Magic. No header field contributes to a bundle EID. Every header byte and the payload travel unmodified in the payload block (Section A.7).

`PBS_LINK.parse_envelope` (PBS_LINK 0.1.1) performs the magic, CRC32, priority and payload-length checks in the order of PBS-ENV-01 Section 14. The adapter then checks the input length and the TTL. Section A.10 lists the rejections.

---

## A.4 BPv7 Bundle Produced

The bundle is a CBOR indefinite-length array: the primary block, the payload block, then the CBOR break code `0xFF` (RFC 9171 Section 4.1). The adapter adds no extension blocks.

| Element | Value | RFC 9171 |
|---------|-------|----------|
| Version | 7 | 4.3.1 |
| Bundle processing control flags | 0 | 4.2.3 |
| CRC type | 2 (CRC32C) | 4.2.1 |
| Destination EID | Authority Context `dest` | 4.3.1 |
| Source node ID | Authority Context `src` | 4.2.5.2, 4.3.1 |
| Report-to EID | Authority Context `report_to` | 4.3.1 |
| Creation timestamp | [DTN time in ms, sequence number] (Section A.6.1) | 4.2.6, 4.2.7 |
| Lifetime | Section A.6.2, milliseconds | 4.3.1 |
| CRC | CRC32C over the encoded primary block with the CRC field set to zeros; 4-byte CBOR byte string, network byte order | 4.2.2, 4.3.1 |
| Payload block | `[1, 1, 0, 0, envelope]`: type 1, number 1, flags 0, CRC type 0, envelope bytes | 4.3.2 |

---

## A.5 Endpoint Identifiers

### A.5.1 Source of the EIDs

The Authority Context map is adapter configuration (`AuthorityContextMap` in the worked example). Each entry, keyed by an authority context name, holds three BPv7 EIDs: `dest`, `src` and `report_to`. The caller names one context for each envelope. No envelope field contributes to any EID. PBS-DTN-MAP-01 Sections 6.1 and 8 likewise configure the destination EID at the gateway, not in the envelope. [PBS-AUTHORITY-CONTEXT](PBS-AUTHORITY-CONTEXT.md) defines the Authority Context.

### A.5.2 EID Schemes and Encoding

| URI | CBOR encoding | RFC 9171 |
|-----|---------------|----------|
| `dtn://pbsf.example/luna/ops` | `[1, "//pbsf.example/luna/ops"]` | 4.2.5.1.1, 9.6 |
| `dtn:none` | `[1, 0]` | 4.2.5.1.1 |
| `ipn:4001.10` | `[2, [4001, 10]]` | 4.2.5.1.2, 9.6 |

### A.5.3 Source Node ID

The primary block's source field holds a node ID or the null endpoint `dtn:none` (RFC 9171 Section 4.3.1). A dtn-scheme EID serves as a node ID only when its demux is empty, for example `dtn://edge-17.pbsf.example/` (Section 4.2.5.1.1). An ipn-scheme EID serves as a node ID only when its service number is 0, for example `ipn:4017.0` (Section 4.2.5.1.2). `AuthorityContextMap` rejects any other `src` when it is constructed.

### A.5.4 Source ID Translation

The worked example does not implement the PBS-DTN-MAP-01 Section 8 translation of each envelope Source ID to its own EID. Every bundle carries the configured `src` node ID. The envelope Source ID reaches the receiver inside the payload block.

---

## A.6 Primary Block Timing

### A.6.1 Creation Timestamp

- **Creation time.** DTN time is the count of milliseconds since 2000-01-01 00:00:00 +0000 (UTC) and is not affected by leap seconds (RFC 9171 Section 4.2.6). Unix time also excludes leap seconds, and the DTN epoch is Unix time 946 684 800 s. The adapter therefore computes creation time = Unix time in ms − 946 684 800 000, truncating one reading of the clock (`clock_us`, Unix time in microseconds) to whole milliseconds. A clock reading at or before the DTN epoch is rejected, because DTN time 0 means "time unknown".
- **Sequence number.** RFC 9171 Section 4.2.7 takes the sequence number from a counter managed by the source node's bundle protocol agent. The worked example takes it as the `creation_seq` argument.

### A.6.2 Lifetime

PBS-DTN-MAP-02 Section 4 requires a lifetime that cannot extend the PBS message beyond its expiry. Let *D* be the configured default lifetime in ms (*D* > 0), *T* the envelope TTL in seconds, and *age* = now − Timestamp in µs, with now taken from the same clock reading as the creation time.

| Condition | Result | Rule |
|-----------|--------|------|
| *T* = 0 | lifetime = *D* | PBS-ENV-01 Section 12.1: TTL 0 never expires |
| *T* > 0 and *age* > *T* × 10⁶ µs | rejected, `EnvelopeExpiredError` | PBS-ENV-01 Sections 12.1, 12.2 and 15: gateways discard expired envelopes |
| *T* > 0, *remaining* ≤ 0 | rejected, `EnvelopeExpiredError` | Less than 1 ms remains; no positive lifetime fits |
| *T* > 0, otherwise | lifetime = min(*D*, *remaining*) | PBS-DTN-MAP-02 Section 4 |

*remaining* = ⌊(*T* × 10⁶ − *age*) / 1000⌋ ms, which equals *T* × 1000 minus the age in milliseconds rounded up. Because creation time and age come from one clock reading, creation time + lifetime never exceeds Timestamp + TTL on the DTN time scale.

Examples with *D* = 60 000 ms, taken from the tests:

| TTL | Age | Lifetime |
|-----|-----|----------|
| 0 s | 10 days | 60 000 ms |
| 30 s | 0 s | 30 000 ms |
| 3600 s | 0 s | 60 000 ms |
| 30 s | 12.5005 s | 17 499 ms |
| 30 s | 29.999 s | 1 ms |
| 30 s | 30 s | rejected |
| 30 s | 30.000001 s | rejected |

The adapter evaluates expiry against the Timestamp and leaves the TTL field unchanged (the timestamp-based method, RECOMMENDED by PBS-ENV-01 Section 12.3). The header CRC32 therefore stays valid, and PBS-DTN-MAP-01 Section 6.4 ("PBS envelopes MUST NOT be modified during DTN encapsulation") holds.

PBS-DTN-MAP-01 Section 6.1 maps TTL to lifetime by unit conversion. PBS-DTN-MAP-02 Section 4 also subtracts the time elapsed before bundle creation. For an envelope of age 0 with *T* × 1000 ≤ *D*, both rules give *T* × 1000 ms.

### A.6.3 Fields Not Mapped

- **Priority.** PBS-DTN-MAP-01 Section 6.3 maps priority to a DTN class of service. PBS-DTN-MAP-02 Section 5 requires a documented BP QoS mechanism. The worked example implements neither. Priority travels unchanged in the envelope.
- **Sequence.** PBS-DTN-MAP-01 Section 6.1 maps Sequence to the bundle sequence. The worked example does not; see Section A.6.1.
- **Flags.** The ACK-requested flag sets no bundle processing control flag. PBS-DTN-MAP-02 Section 6 keeps PBS acknowledgement an application semantic.

---

## A.7 Payload Block

The payload block's data field is the complete input: the 44-byte header followed by `Size` payload bytes, as one definite-length CBOR byte string. The adapter does not compress, encrypt, fragment, re-encode or modify it. The header CRC32 travels unchanged and remains verifiable by the receiving PBS node (PBS-DTN-MAP-01 Sections 6.2 and 6.4).

---

## A.8 Envelope Identity

The envelope's Source ID, Sequence and Timestamp travel inside the payload block. The bundle's source node ID and creation timestamp identify the bundle (RFC 9171 Section 4.2.7), not the envelope. No extension block carries PBS identity.

---

## A.9 Inbound Direction (BPv7 to PBS)

The worked example does not implement the inbound direction. PBS-DTN-MAP-01 Section 7 defines it:

1. The bundle protocol agent validates the bundle first. Invalid bundles are discarded before PBS processing (Section 7.1).
2. The payload block content is the envelope. It is extracted verbatim, and no envelope field is modified (Section 7.2).
3. Expiry of the bundle lifetime results in envelope discard. The PBS TTL is not incremented or reset (Section 7.3).

The receiving PBS node then processes the envelope in the order of PBS-ENV-01 Section 14: magic, CRC32, priority, TTL, payload. No envelope field is derived from bundle EIDs.

---

## A.10 Error Handling

`pbs_to_bpv7_bundle_mv` raises an exception and produces no bundle in each of these cases:

| Condition | Exception | Rule |
|-----------|-----------|------|
| Magic ≠ `0x10` | `PBS_LINK.PBSMagicError` | PBS-ENV-01 Sections 5 and 14 |
| Header CRC32 mismatch | `PBS_LINK.PBSCRCError` | PBS-ENV-01 Sections 13 and 14 |
| Priority 5–255 | `PBS_LINK.PBSPriorityError` | PBS-ENV-01 Sections 6 and 14 |
| Input shorter than 44 bytes or than 44 + `Size` | `PBS_LINK.PBSValidationError` | PBS-ENV-01 Sections 4 and 11 |
| Input longer than 44 + `Size` | `EnvelopeLengthError` | One envelope per payload block (PBS-DTN-MAP-01 Sections 5.1 and 6.2) |
| Envelope expired, or less than 1 ms of TTL left | `EnvelopeExpiredError` | Section A.6.2 |
| Unknown authority context name | `KeyError` | Section A.5.1 |
| Clock at or before the DTN epoch | `ValueError` | Section A.6.1 |

---

## A.11 Verification

`TESTS/test_pbs_edge_adapter_worked_example_validation.py` covers three of the PBS-DTN-MAP-02 Section 10 conformance items:

| PBS-DTN-MAP-02 Section 10 item | Tests |
|--------------------------------|-------|
| Envelope preservation through BP encapsulation | Payload block bytes equal the envelope bytes, including a 256-byte payload of every byte value |
| Deadline-to-lifetime bounding | TTL 0, TTL below and above the default, partially aged, expired; creation time + lifetime never exceeds the PBS expiry |
| EID mapping stability | Identical inputs give identical bundle bytes |

The tests also check the bundle and block structure, the primary block CRC32C, the RFC 7143 Appendix A.4 CRC32C examples, the DTN-millisecond creation time, rejection of corrupted headers and wrong lengths, and the source node ID rule. They do not cover priority preservation, store-and-forward delivery, expiry during disruption, duplicate handling or PBS-SEC-B with BPSec, which need a bundle protocol agent.
