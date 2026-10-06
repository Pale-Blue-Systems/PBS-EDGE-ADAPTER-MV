# PBS Edge Adapter – Minimum Viable Reference (PBS-EDGE-ADAPTER-MV)

[![tests](https://github.com/Pale-Blue-Systems/PBS-EDGE-ADAPTER-MV/actions/workflows/tests.yml/badge.svg)](https://github.com/Pale-Blue-Systems/PBS-EDGE-ADAPTER-MV/actions/workflows/tests.yml)

This repository specifies the **Pale Blue Systems (PBS) Edge Adapter** and demonstrates it with a tested Python worked example. The adapter encapsulates a PBS-ENV-01 v1.3 envelope in a Bundle Protocol Version 7 (BPv7) bundle (IETF RFC 9171) for carriage across a delay/disruption-tolerant network (DTN).

No PBS edge adapter product is published. The worked example builds bundle bytes; it does not connect to a bundle protocol agent.

---

## What the Worked Example Implements

`pbs_edge_adapter_worked_example.py` converts one envelope into one bundle (`pbs_to_bpv7_bundle_mv`):

| Step | Clause |
|------|--------|
| Parse the envelope with PBS_LINK; reject a bad magic byte, a header CRC32 mismatch, a reserved priority (5–255) or a short payload | PBS-ENV-01 v1.3 Sections 13, 14 |
| Reject input longer than the 44-byte header plus `Size` | PBS-DTN-MAP-01 Sections 5.1, 6.2 (one envelope per payload block) |
| Reject an expired envelope | PBS-ENV-01 Sections 12.1, 12.2, 15 |
| Map one envelope to exactly one bundle | PBS-DTN-MAP-01 Section 5.1; PBS-DTN-MAP-02 Section 2 |
| Place the entire envelope (header and payload) in a single payload block, unmodified, header CRC32 preserved | PBS-DTN-MAP-01 Sections 6.2, 6.4 |
| Set the lifetime to the configured default for TTL 0, otherwise min(default, TTL × 1000 − age in ms) | PBS-DTN-MAP-02 Section 4 |
| Take the destination EID, source node ID and report-to EID from the Authority Context map; accept as source the null endpoint, a dtn EID with an empty demux, or an ipn EID | PBS-DTN-MAP-01 Section 6.1 (Destination EID row) and Section 8 (destination EIDs configured at the gateway); RFC 9171 Section 4.2.5.1.1; RFC 9758 Sections 3.4.1, 5.3 |
| Write the creation time as DTN time in milliseconds since 2000-01-01T00:00:00Z | RFC 9171 Sections 4.2.6, 4.2.7 |
| Set processing control flags 0, or 0x04 (bundle must not be fragmented) when the source is the null endpoint | RFC 9171 Section 4.2.3 |
| Encode the bundle in CBOR with a CRC32C primary block and a CRC-type-0 payload block | RFC 9171 Sections 4.1, 4.2.1, 4.2.2, 4.3.1, 4.3.2 |

It does not implement the PBS-DTN-MAP-01 Section 8 translation of each Source ID to its own EID, the Sequence-to-bundle-sequence row of PBS-DTN-MAP-01 Section 6.1 (the caller supplies `creation_seq`), priority-to-class-of-service mapping (PBS-DTN-MAP-01 Section 6.3; PBS-DTN-MAP-02 Section 5), store-and-forward (PBS-DTN-MAP-01 Section 9), mapping of PBS-ADDR-01 payload addresses to EIDs (PBS-ADDR-01 Section 11), service intent (PBS-DTN-MAP-02 Section 6), security (PBS-DTN-MAP-02 Section 7), failure and status translation (PBS-DTN-MAP-02 Section 9), or the inbound direction (PBS-DTN-MAP-01 Section 7). In place of the PBS-DTN-MAP-01 Section 6.1 TTL-to-lifetime unit conversion, it applies the PBS-DTN-MAP-02 Section 4 bound ([Appendix A, Section A.6.2](DOCS/PBS-BPv7-MAPPING-APPENDIX.md)).

PBS-DTN-MAP-01 (v1.3) and PBS-DTN-MAP-02 (v1.4) are both optional interoperability specifications in the [PBS protocol library](https://github.com/Pale-Blue-Systems/PBS-PROTOCOL-OPEN/tree/main/PBS-RFC-LIB). DTN-MAP-01 defines the envelope-to-bundle mapping at a gateway boundary; DTN-MAP-02 defines endpoint mapping, lifetime and freshness, priority and QoS, service intent and security for BPv7 carriage. [`DOCS/PBS-BPv7-MAPPING-APPENDIX.md`](DOCS/PBS-BPv7-MAPPING-APPENDIX.md) gives the field-level mapping.

---

## What the Tests Verify

`TESTS/test_pbs_edge_adapter_worked_example_validation.py` (53 tests) builds envelopes with PBS_LINK at a fixed Timestamp and injects the adapter clock, so every value checked is exact:

- **Bundle structure:** CBOR indefinite-length array; primary block of 9 items with version 7, CRC type 2 and the configured EIDs; processing control flags 0, and 0x04 for a `dtn:none` or `ipn:0.0` source; payload block `[1, 1, 0, 0, envelope]`.
- **CRC32C:** the primary block CRC recomputes correctly, and `crc32c` reproduces the five CRC32C examples of RFC 7143 Appendix A.4, to which RFC 9171 Section 4.2.1 refers.
- **Creation time:** DTN milliseconds; a clock of 2026-01-01T00:00:01.234567Z gives 820 540 801 234 ms. The DTN epoch is Unix time 946 684 800 000 ms.
- **Lifetime:** TTL 0 gives the default; a TTL below the default gives the TTL, and one above it gives the default; a partially aged envelope gives the remaining TTL (17 499 ms at TTL 30 s, age 12.5005 s); a Timestamp 1 h ahead of the adapter clock gives the TTL (30 000 ms); creation time + lifetime never exceeds the envelope's Timestamp + TTL.
- **Rejections:** expired envelopes, less than 1 ms of TTL left, a corrupted header (Source ID, Timestamp, TTL or CRC32 byte), trailing or missing bytes, unknown authority context, a source EID that cannot serve as a node ID, a negative sequence number, a non-positive default lifetime.
- **Source EID rule:** a dtn src is accepted only with an empty demux (RFC 9171 Section 4.2.5.1.1). `dtn://edge-17.pbsf.example/`, `ipn:4017.0`, `ipn:4001.99`, the PBS-DTN-MAP-01 Section 8 example `ipn:99.1` and both null endpoints are accepted; `dtn://pbsf.example/edge/node-17`, `dtn://pbsf.example/~ops` and `ipn:0.5` are rejected.
- **Envelope preservation:** payload block bytes equal the envelope bytes, for a 256-byte payload containing every byte value.
- **Determinism:** identical inputs and clock reading give identical bundle bytes.

---

## How to Run

CI runs these commands on Python 3.10, 3.11 and 3.12.

```bash
pip install pytest cbor2 git+https://github.com/Pale-Blue-Systems/PBS_LINK.git
pytest -q
python pbs_edge_adapter_worked_example.py
```

[PBS_LINK](https://github.com/Pale-Blue-Systems/PBS_LINK) is the PBS reference SDK (pip distribution `pbs-link` 0.1.1; import package `PBS_LINK`). It implements PBS-ENV-01 v1.3, including the header CRC32 over bytes 0x00–0x2B with the CRC32 field set to zero.

The worked example prints the envelope header, the bundle in hex, the decoded primary block, the creation time as a UTC instant, and the lifetime. With a 120 s TTL and a 300 000 ms configured default, the lifetime is 120 000 ms minus the envelope's age at bundle creation, with the age rounded up to whole milliseconds.

---

## Repository Contents

| Path | Content |
|------|---------|
| `pbs_edge_adapter_worked_example.py` | Worked example: envelope to BPv7 bundle |
| `TESTS/` | Validation tests |
| `DOCS/PBS-EDGE-ADAPTER-MV.md` | Adapter reference design and implementation status |
| `DOCS/PBS-BPv7-MAPPING-APPENDIX.md` | Appendix A: field-level mapping, lifetime rule, error handling |
| `DOCS/PBS-AUTHORITY-CONTEXT.md` | Authority Context: source of the bundle EIDs |
| `DOCS/PBS-EDGE-CONFIG-SCHEMA.md` | Appendix B: configuration inputs |
| `DOCS/PBS-EDGE-ARCHITECTURE.md` | Placement, components and message flows (Mermaid) |
| `WHY-NOW.md` | Basis for the work |
| `CHANGELOG.md` | Change history |
| `.github/workflows/tests.yml` | CI: tests and worked example |

---

## Standards Basis

- **PBS:** PBS-ENV-01 v1.3, PBS-DTN-MAP-01 v1.3 and PBS-DTN-MAP-02 v1.4. The current PBS release is PBS v1.4.1 (2026-10-06), an errata and documentation release of PBS v1.4 with no wire-format change.
- **BPv7:** IETF RFC 9171, *Bundle Protocol Version 7*, <https://www.rfc-editor.org/rfc/rfc9171>.
- **LunaNet:** LunaNet Interoperability Specification, Version 5 (LNIS V005, NASA, 29 January 2025), Section 3.1.2: "The Bundle Protocol version 7 (BPv7) shall be used" for DTN network communications services. <https://www.nasa.gov/wp-content/uploads/2025/02/lunanet-interoperability-specification-v5-baseline.pdf>

---

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
