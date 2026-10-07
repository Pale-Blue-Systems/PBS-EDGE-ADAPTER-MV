# PBS Edge Adapter – Minimum Viable Reference (PBS-EDGE-ADAPTER-MV)

[![tests](https://github.com/Pale-Blue-Systems/PBS-EDGE-ADAPTER-MV/actions/workflows/tests.yml/badge.svg)](https://github.com/Pale-Blue-Systems/PBS-EDGE-ADAPTER-MV/actions/workflows/tests.yml)

This repository specifies the **Pale Blue Systems (PBS) Edge Adapter** and demonstrates it with a tested Python worked example. The adapter encapsulates a PBS-ENV-01 v1.3 envelope in a Bundle Protocol Version 7 (BPv7) bundle (IETF RFC 9171) for carriage across a delay/disruption-tolerant network (DTN).

No PBS edge adapter product is published. The worked example builds bundle bytes; it does not connect to a bundle protocol agent. The [ION end-to-end demonstration](#end-to-end-demonstration-over-nasajpl-ion) does: it carries envelopes between two NASA/JPL ION nodes across an emulated Earth–Moon link.

A deployment requires a BPv7 bundle protocol agent. The NASA/JPL Interplanetary Overlay Network (ION, <https://github.com/nasa-jpl/ION-DTN>) is one; its `bpv7` module implements RFC 9171. JPL's ION configuration tools are at <https://github.com/nasa-jpl/ion-config-tool>. Use the upstream repositories; Pale Blue Systems does not maintain forks of them.

---

## Context and Intent

Pale Blue Systems publishes this work in anticipation of a future space environment that includes multiple space agencies, commercial operators, private missions, and long-lived infrastructure operating concurrently beyond Earth.

This repository does not claim to solve a current operational deficiency. It contributes to early architectural discussion by making future authority and interoperability considerations explicit—before infrastructure, protocols, and assumptions become fixed.

---

## Planned Edge Adapter (in development)

Pale Blue Systems is building the full PBS Edge Adapter that `DOCS/` specifies. The worked example implements the part described in the next section.

### Scope and Intent

The PBS Edge Adapter serves as a **boundary component** between:

- **PBS envelopes**, which carry authority-aware routing and scope metadata in PBS-ADDR-01 and PBS-AUTH-01 payload frames (the 44-byte PBS-ENV-01 header has no such field), and
- **BPv7 bundle agents**, which provide delay-tolerant transport across heterogeneous and disrupted networks.

This repository focuses on **clarifying that boundary** and demonstrating how the mapping can be performed deterministically and transparently.

### PBS → BPv7 Mapping Specification

A concrete, inspectable description of how:

- PBS envelope fields are mapped to BPv7 bundle elements
- PBS authority and scope identifiers, taken from the gateway's Authority Context configuration or a PBS-AUTH-01 frame, are translated into BPv7 Endpoint Identifiers (EIDs)
- Entire PBS envelopes (44-byte header and payload) are encapsulated as opaque BPv7 payload blocks

The mapping is designed to be **deterministic**, **lossless**, and **transport-agnostic**.

### Authority-Aware Edge Behavior

The reference design treats **Authority Context** as a first-class input to routing and encapsulation decisions at the edge. Routing decisions take effect as configuration of the bundle protocol agent's routing; route computation and path selection remain in the agent (PBS-DTN-MAP-02 Section 8).

This ensures that PBS envelopes originating from different authorities remain logically separated while sharing common transport infrastructure.

---

## What the Worked Example Implements

`pbs_edge_adapter_worked_example.py` converts one envelope into one bundle (`pbs_to_bpv7_bundle_mv`):

| Step | Clause |
|------|--------|
| Parse the envelope with PBS_LINK; reject a bad magic byte, a header CRC32 mismatch, a reserved priority (5–255) or a short payload | PBS-ENV-01 Sections 13, 14 |
| Reject input longer than the 44-byte header plus `Size` | PBS-DTN-MAP-01 Sections 5.1, 6.2 (one envelope per payload block) |
| Reject an expired envelope, or one with less than 1 ms of TTL left | PBS-ENV-01 Sections 12.1, 12.2, 15; PBS-DTN-MAP-01 Section 6.1 |
| Map one envelope to exactly one bundle | PBS-DTN-MAP-01 Section 5.1 (SHALL); PBS-DTN-MAP-02 Section 2 (one PDU SHOULD map to one BP ADU) |
| Place the entire envelope (header and payload) in a single payload block, unmodified: the 44 header bytes, TTL and CRC32 included, are carried as received | PBS-DTN-MAP-01 Sections 6.2, 6.4, 7.3; PBS-ENV-01 Sections 12.3, 15 |
| Set the lifetime to min(default, TTL × 1000 − age in ms); for TTL 0, the configured default (the no-expiry lifetime, 1 to 4 294 967 295 000 ms) | PBS-DTN-MAP-01 Sections 6.1, 6.1.1; PBS-DTN-MAP-02 Section 4; [Appendix A, Section A.6.2](DOCS/PBS-BPv7-MAPPING-APPENDIX.md) |
| Take the destination EID, source node ID and report-to EID from the Authority Context map; accept as source the null endpoint, a dtn EID with an empty demux, or an ipn EID | PBS-DTN-MAP-01 Section 6.1 (Destination EID row) and Section 8 (destination EIDs configured at the gateway); RFC 9171 Section 4.2.5.1.1; RFC 9758 Sections 3.4.1, 5.3 |
| Write the creation timestamp: creation time as DTN time in milliseconds since 2000-01-01T00:00:00Z; sequence number from the adapter's counter, 0 for the first bundle in a millisecond and one higher for each further bundle in it, or the caller's `creation_seq`; never from the envelope Sequence | RFC 9171 Sections 4.2.6, 4.2.7; PBS-DTN-MAP-01 Section 6.1 |
| Set processing control flags 0, or 0x04 (bundle must not be fragmented) when the source is the null endpoint; set no reserved or unassigned flag, so no flag conveys priority | RFC 9171 Section 4.2.3; PBS-DTN-MAP-01 Section 6.3 |
| Encode the bundle in CBOR with a CRC32C primary block and a CRC-type-0 payload block | RFC 9171 Sections 4.1, 4.2.1, 4.2.2, 4.3.1, 4.3.2 |

It does not implement the PBS-DTN-MAP-01 Section 8 translation of each Source ID to its own EID, assignment of the creation timestamp by the gateway's bundle protocol agent (PBS-DTN-MAP-01 Section 6.1; the worked example is not a bundle protocol agent and assigns the creation timestamp itself, [Appendix A, Section A.6.1](DOCS/PBS-BPv7-MAPPING-APPENDIX.md)), a mapping profile for priority-based network treatment (PBS-DTN-MAP-01 Section 6.3; PBS-DTN-MAP-02 Section 5), store-and-forward (PBS-DTN-MAP-01 Section 9), mapping of PBS-ADDR-01 payload addresses to EIDs (PBS-ADDR-01 Section 11), service intent, including the Service Intent deadline and maximum age limits of PBS-DTN-MAP-02 Section 4 (PBS-DTN-MAP-02 Section 6), security (PBS-DTN-MAP-02 Section 7), failure and status translation (PBS-DTN-MAP-02 Section 9), or the inbound direction (PBS-DTN-MAP-01 Section 7).

PBS-DTN-MAP-01 (v1.5) and PBS-DTN-MAP-02 (v1.5) are both optional interoperability specifications in the [PBS protocol library](https://github.com/Pale-Blue-Systems/PBS-PROTOCOL-OPEN/tree/main/PBS-RFC-LIB). DTN-MAP-01 defines the envelope-to-bundle mapping at a gateway boundary; DTN-MAP-02 defines endpoint mapping, lifetime and freshness, priority and QoS, service intent and security for BPv7 carriage. PBS-DTN-MAP-01 Sections 6.1 and 6.3 refer to PBS-DTN-MAP-02 Section 4 for finite lifetime limits and Section 5 for the mapping profile. [`DOCS/PBS-BPv7-MAPPING-APPENDIX.md`](DOCS/PBS-BPv7-MAPPING-APPENDIX.md) gives the field-level mapping.

---

## What the Tests Verify

`TESTS/test_pbs_edge_adapter_worked_example_validation.py` (72 tests) builds envelopes with PBS_LINK at a fixed Timestamp and injects the adapter clock, so every value checked is exact:

- **Bundle structure:** CBOR indefinite-length array; primary block of 9 items with version 7, CRC type 2 and the configured EIDs; processing control flags 0, and 0x04 for a `dtn:none` or `ipn:0.0` source; payload block `[1, 1, 0, 0, envelope]`.
- **Priority:** for each priority 0 to 4, processing control flag bits 7 and 8 (0x180) are clear and the envelope in the payload block keeps its Priority byte; a primary block with flag 0x80, 0x100, 0x180, 0x08 or 0x200000 is rejected.
- **CRC32C:** the primary block CRC recomputes correctly, and `crc32c` reproduces the five CRC32C examples of RFC 7143 Appendix A.4, to which RFC 9171 Section 4.2.1 refers.
- **Creation timestamp:** DTN milliseconds; a clock of 2026-01-01T00:00:01.234567Z gives 820 540 801 234 ms. The DTN epoch is Unix time 946 684 800 000 ms. Three bundles created in one millisecond get sequence numbers 0, 1 and 2, and the next millisecond starts again at 0; without a counter argument, two bundles in one millisecond get different creation timestamps; a caller-supplied `creation_seq` is used as given and does not advance the counter.
- **Lifetime:** TTL 0 gives the default; a TTL below the default gives the TTL, and one above it gives the default; a partially aged envelope gives the remaining TTL (17 499 ms at TTL 30 s, age 12.5005 s); a Timestamp 1 h ahead of the adapter clock gives the TTL (30 000 ms); creation time + lifetime never exceeds the envelope's Timestamp + TTL; a default of 4 294 967 295 000 ms is accepted and 4 294 967 296 000 ms rejected; the TTL 0 lifetime is not less than the lifetime for any TTL from 1 s to 4 294 967 295 s.
- **Rejections:** expired envelopes, less than 1 ms of TTL left, a corrupted header (Source ID, Timestamp, TTL or CRC32 byte), trailing or missing bytes, unknown authority context, a source EID that cannot serve as a node ID, a negative sequence number, a default lifetime outside 1 to 4 294 967 295 000 ms.
- **Source EID rule:** a dtn src is accepted only with an empty demux (RFC 9171 Section 4.2.5.1.1). `dtn://edge-17.pbsf.example/`, `ipn:4017.0`, `ipn:4001.99`, the PBS-DTN-MAP-01 Section 8 example `ipn:99.1` and both null endpoints are accepted; `dtn://pbsf.example/edge/node-17`, `dtn://pbsf.example/~ops` and `ipn:0.5` are rejected.
- **Envelope preservation:** payload block bytes equal the envelope bytes, for a 256-byte payload containing every byte value.
- **Determinism:** identical inputs, sequence number and clock reading give identical bundle bytes.

---

## End-to-End Demonstration over NASA/JPL ION

`pbs_ion_demo/` carries PBS envelopes end to end through ION, release `ion-open-source-4.2.0`, built unmodified from <https://github.com/nasa-jpl/ION-DTN>. Two ION nodes, a lunar surface gateway (`ipn:1`) and an Earth operations gateway (`ipn:2`), are joined over ION's UDP convergence layer by a link emulator. The emulator adds the 1.2822 s one-way light time of the Moon's mean distance and records every bundle on the link. The gateway validates each envelope, selects the bundle lifetime and ION class of service, and hands the envelope to ION with ION's `bpsendfile`. ION creates the bundle and assigns its creation timestamp (PBS-DTN-MAP-01 Section 6.1). The receiving gateway collects ION's deliveries from `bprecvfile` and checks the restored envelope.

The demonstration shows downlink and uplink delivery, priority mapped to ION's expedited, standard and bulk classes, a bundle held through a contact gap and forwarded when the contact opens, a bundle whose lifetime ends in storage and is never sent, and ION accepting bundles encoded by the worked example.

| Document | Content |
|----------|---------|
| [`DOCS/PBS-ION-E2E-DEMO.md`](DOCS/PBS-ION-E2E-DEMO.md) | Architecture, how to run, example output, limitations, references |
| [`DOCS/PBS-ION-MAPPING-PROFILE.md`](DOCS/PBS-ION-MAPPING-PROFILE.md) | Mapping profile and no-expiry lifetime for ION 4.2.0 (PBS-DTN-MAP-01 Sections 6.1.1, 6.3; PBS-DTN-MAP-02 Sections 4, 5) |
| [`DOCS/PBS-ION-E2E-TEST-PLAN.md`](DOCS/PBS-ION-E2E-TEST-PLAN.md) | Requirements, verification cross-reference matrix, test cases UT-01 to UT-26 and IT-01 to IT-13, procedures and records |

```bash
scripts/build_ion.sh                       # pinned ION release into .ion/install
export ION_PREFIX="$PWD/.ion/install"
python -m pip install -r requirements-ion-demo.txt
python -m pbs_ion_demo                     # the demonstration
PBS_ION_REQUIRED=1 pytest -v               # all tests, including ION end to end
```

`TESTS/test_ion_demo_units.py` (37 tests) runs without ION. `TESTS/ion/test_ion_end_to_end.py` (14 tests) runs against ION and is skipped without it, unless `PBS_ION_REQUIRED=1`. The CI job `ion-e2e` builds ION, runs every test and the demonstration, and keeps the as-run records.

---

## How to Run

CI runs these commands on Python 3.10, 3.11 and 3.12. They also run the ION demonstration's unit tests; the ION end-to-end tests are skipped without ION (see the previous section).

```bash
pip install pytest cbor2 git+https://github.com/Pale-Blue-Systems/PBS_LINK.git
pytest -q
python pbs_edge_adapter_worked_example.py
```

[PBS_LINK](https://github.com/Pale-Blue-Systems/PBS_LINK) is the PBS reference SDK (pip distribution `pbs-link` 0.1.3; import package `PBS_LINK`). It implements PBS-ENV-01 v1.3, including the header CRC32 over bytes 0x00–0x2B with the CRC32 field set to zero.

The worked example prints the envelope header, the bundle in hex, the decoded primary block, the creation time as a UTC instant with its sequence number, and the lifetime. With a 120 s TTL and a 300 000 ms configured default, the lifetime is 120 000 ms minus the envelope's age at bundle creation, with the age rounded up to whole milliseconds.

---

## Intended Audience

This repository is written for:

- Space and DTN engineers evaluating interoperability approaches
- Standards bodies and working groups reviewing edge-mapping concepts
- Researchers and system architects exploring authority-aware networking models
- Organizations assessing how PBS envelopes integrate with existing DTN infrastructure

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
| `pbs_ion_demo/` | End-to-end demonstration over ION: gateway, ION node control, link emulator, BPv7 wire decoder |
| `TESTS/test_ion_demo_units.py`, `TESTS/ion/` | Demonstration tests: unit tests, and end-to-end tests against ION |
| `DOCS/PBS-ION-E2E-DEMO.md`, `DOCS/PBS-ION-MAPPING-PROFILE.md`, `DOCS/PBS-ION-E2E-TEST-PLAN.md` | Demonstration, ION mapping profile, test plan |
| `scripts/build_ion.sh`, `scripts/ion-release.env` | Build of the pinned ION release |
| `requirements-ion-demo.txt` | Pinned Python dependencies of the demonstration |
| `.github/workflows/tests.yml` | CI: tests and worked example; job `ion-e2e` builds ION and runs the end-to-end tests and the demonstration |

Planned additions (in development):

- `reference/` — Minimal reference logic illustrating the adapter concept
- `examples/` — Example PBS envelopes and corresponding BPv7 mappings

---

## Standards Basis

- **PBS:** PBS-ENV-01 v1.5, PBS-DTN-MAP-01 v1.5 and PBS-DTN-MAP-02 v1.5. The current PBS release is PBS v1.5.0 (2026-10-06), a corrective release with no wire-format change: the 44-byte PBS-ENV-01 header defined in v1.3 is unchanged.
- **BPv7:** IETF RFC 9171, *Bundle Protocol Version 7*, <https://www.rfc-editor.org/rfc/rfc9171>.
- **LunaNet:** LunaNet Interoperability Specification, Version 5 (LNIS V005, NASA, ESA and JAXA, 29 January 2025), Section 3.1.2: "The Bundle Protocol version 7 (BPv7) shall be used" for DTN network communications services. <https://www.nasa.gov/wp-content/uploads/2025/02/lunanet-interoperability-specification-v5-baseline.pdf>

### 5. Alignment with Existing Standards

The reference design aligns with:

- **Bundle Protocol Version 7 (BPv7)** as defined in RFC 9171 and corresponding CCSDS recommendations
- Operational DTN architectures that employ established bundle agents

By grounding the PBS Edge Adapter in existing standards, the repository provides a concrete basis for interoperability analysis and future discussion.

---

## Status

This repository represents a **minimum viable reference** for the PBS Edge Adapter concept.
It is published to support technical clarity, review, and discussion as PBS standards evolve.

---

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
