# PBS Edge Adapter — Minimum Viable Reference  
**Document ID:** PBS-EDGE-ADAPTER-MV  
**Status:** Reference Draft  
**Steward:** Pale Blue Systems Foundation  

---

## 1. Purpose

This document defines the minimum viable (MV) reference design of the **PBS Edge Adapter**. The adapter encapsulates PBS-ENV-01 v1.3 envelopes in Bundle Protocol Version 7 (BPv7, IETF RFC 9171) bundles and extracts them from received bundles.

| Document | Content |
|----------|---------|
| [PBS-BPv7-MAPPING-APPENDIX](PBS-BPv7-MAPPING-APPENDIX.md) | Field-level mapping, lifetime rule, error handling |
| [PBS-AUTHORITY-CONTEXT](PBS-AUTHORITY-CONTEXT.md) | Authority Context: source of the bundle EIDs |
| [PBS-EDGE-CONFIG-SCHEMA](PBS-EDGE-CONFIG-SCHEMA.md) | Configuration inputs |
| [PBS-EDGE-ARCHITECTURE](PBS-EDGE-ARCHITECTURE.md) | Component placement and message flows |

The governing PBS specifications are PBS-ENV-01 v1.5, PBS-DTN-MAP-01 v1.5 and PBS-DTN-MAP-02 v1.5 (PBS v1.5.0, 2026-10-06), published in [PBS-PROTOCOL-OPEN](https://github.com/Pale-Blue-Systems/PBS-PROTOCOL-OPEN/tree/main/PBS-RFC-LIB).

---

## 2. Implementation Status

No PBS edge adapter product is published. `pbs_edge_adapter_worked_example.py` implements the outbound conversion of one envelope into the bytes of one bundle (Section 4, steps 2 to 5), with tests. It does not implement ingress or egress interfaces, injection into or delivery from a bundle protocol agent, the inbound direction, configuration loading, translation of each Source ID to its own EID (PBS-DTN-MAP-01 Section 8), mapping of PBS-ADDR-01 payload addresses to EIDs (PBS-ADDR-01 Section 11), or a mapping profile for priority-based network treatment (PBS-DTN-MAP-01 Section 6.3; PBS-DTN-MAP-02 Section 5). It is not a bundle protocol agent: it assigns the creation timestamp itself, which PBS-DTN-MAP-01 Section 6.1 assigns to the gateway's agent ([PBS-BPv7-MAPPING-APPENDIX](PBS-BPv7-MAPPING-APPENDIX.md) Section A.6.1).

---

## 3. Role

The adapter sits at the boundary between systems that produce or consume PBS envelopes and a BPv7 bundle protocol agent. It performs encapsulation and extraction only. PBS-DTN-MAP-01 Section 4 defines mapping nodes as protocol translators, not originators. Contact plans, route computation, convergence-layer selection, custody-related operational policy and provider path selection are DTN and network-service functions (PBS-DTN-MAP-02 Section 8); the adapter performs none of them.

---

## 4. Functional Overview

Outbound (PBS to BPv7), per envelope:

1. Accept the envelope from the local ingress interface.
2. Validate it: magic, header CRC32, priority and payload length (PBS-ENV-01 Section 14, via `PBS_LINK.parse_envelope`), input length equal to 44 + `Size`, and TTL (PBS-ENV-01 Section 12.2).
3. Resolve the named Authority Context to a destination EID, source node ID and report-to EID.
4. Build the primary block: creation timestamp of DTN milliseconds and a sequence number from the adapter's counter (RFC 9171 Section 4.2.7); lifetime bounded by the remaining TTL, or for TTL 0 the configured no-expiry lifetime (PBS-DTN-MAP-01 Sections 6.1 and 6.1.1; PBS-DTN-MAP-02 Section 4); no reserved or unassigned processing control flag (PBS-DTN-MAP-01 Section 6.3); CRC32C.
5. Place the complete envelope, unmodified, in the payload block (PBS-DTN-MAP-01 Section 6.2).
6. Pass the bundle to the bundle protocol agent.

Inbound (BPv7 to PBS), per bundle (not implemented):

1. Accept a bundle validated by the bundle protocol agent (PBS-DTN-MAP-01 Section 7.1).
2. Extract the payload block content as the envelope, verbatim (PBS-DTN-MAP-01 Section 7.2).
3. Validate the envelope per PBS-ENV-01 Section 14 and deliver it to the local egress interface.

---

## 5. Authority Context

An Authority Context is a named configuration entry holding the destination EID, source node ID and report-to EID used for every bundle built under it. The adapter holds a map of contexts, and each envelope is encapsulated under exactly one context, named by the caller. The PBS-ENV-01 v1.3 header has no authority, scope or destination field. The adapter's Authority Context is distinct from the PBS-AUTH-01 authority context frame (PBS-MUX frame type `0x08`), which travels inside the envelope payload and which the adapter does not read. [PBS-AUTHORITY-CONTEXT](PBS-AUTHORITY-CONTEXT.md) specifies it.

---

## 6. PBS Envelope Handling

### 6.1 Envelope Acceptance

The adapter accepts PBS-ENV-01 v1.3 envelopes: a fixed 44-byte big-endian header followed by `Size` payload bytes. Each envelope is processed as one unit and maps to one bundle (PBS-DTN-MAP-01 Section 5.1). The adapter rejects an envelope that fails any check in Section 4, step 2, and produces no bundle. [PBS-BPv7-MAPPING-APPENDIX](PBS-BPv7-MAPPING-APPENDIX.md) Section A.10 lists each rejection.

### 6.2 Envelope Opacity

The adapter reads the Magic, Priority, Timestamp, Size, TTL and CRC32 header fields for validation and lifetime selection. It does not read the payload. It modifies no envelope byte: TTL is not modified and the originator's header CRC32 remains valid end to end (PBS-ENV-01 Sections 12.3 and 15; PBS-DTN-MAP-01 Sections 6.4 and 7.3). It does not read Sequence, and neither Sequence nor Priority enters a primary block field (PBS-DTN-MAP-01 Section 6.1).

---

## 7. Bundle Construction

Each bundle is a CBOR indefinite-length array of two blocks (RFC 9171 Section 4.1):

- **Primary block** (Section 4.3.1): version 7; processing control flags 0, or 0x04 (bundle must not be fragmented) when the source is the null endpoint (Section 4.2.3), and no reserved or unassigned flag (PBS-DTN-MAP-01 Section 6.3); CRC type 2 (CRC32C); destination EID, source node ID and report-to EID from the Authority Context; creation timestamp of DTN time in milliseconds and a sequence number from the adapter's counter or the caller (Section 4.2.7); lifetime in milliseconds, equal to the configured no-expiry lifetime for TTL 0 (PBS-DTN-MAP-01 Section 6.1.1) and to min(no-expiry lifetime, remaining TTL) otherwise (PBS-DTN-MAP-01 Section 6.1); CRC32C.
- **Payload block** (Section 4.3.2): type 1, number 1, flags 0, CRC type 0, the envelope bytes.

The adapter adds no extension blocks.

---

## 8. Deterministic Behavior

Identical envelope bytes, Authority Context entry, configured default lifetime, sequence number and clock reading produce identical bundle bytes; the tests check this. When the caller supplies no sequence number, the adapter's counter gives each bundle created in the same millisecond a different one. The adapter performs no policy arbitration, trust scoring or routing.

---

## 9. Transport Integration

A deployment requires a BPv7 bundle protocol agent that accepts bundles for forwarding and delivers received bundles to the adapter. The NASA/JPL Interplanetary Overlay Network (ION, <https://github.com/nasa-jpl/ION-DTN>) is one such agent; its `bpv7` module implements RFC 9171. The worked example produces bundle bytes and does not connect to an agent.

The LunaNet Interoperability Specification, Version 5 (LNIS V005, NASA, ESA and JAXA, 29 January 2025), Section 3.1.2, specifies BPv7 for LunaNet DTN network communications services.

---

## 10. Status

Reference draft. The worked example implements Section 4, outbound steps 2 to 5. The remaining steps and the inbound direction are specified here and not implemented.
