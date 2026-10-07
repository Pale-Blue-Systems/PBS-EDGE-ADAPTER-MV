# Changelog  
All notable changes to this repository are documented in this file.

This project follows a **reference-driven change history**, where entries describe
documentation, specifications, and illustrative artifacts rather than production releases.

---

## [Unreleased]

### ION end-to-end demonstration

#### Added
- `pbs_ion_demo/`: PBS envelopes carried end to end through NASA/JPL ION, release `ion-open-source-4.2.0` (commit `568df887cb9f18aa8ec013b1a566d83215e499ae`), between a lunar gateway node (`ipn:1`) and an Earth gateway node (`ipn:2`) over ION's UDP convergence layer. A link emulator adds the Earth–Moon one-way light time (384 400 km / c = 1.2822 s) and records every bundle on the link. `IonGateway` validates each envelope and evaluates the PBS-DTN-MAP-01 Section 6.1 lifetime bound at `c_us` = clock reading + maximum submission latency (2 s). It requests that lifetime from ION in whole seconds, rounded down, and requests the ION class of service from the Section 6.3 table. It submits with `bpsendfile`, so ION creates the bundle and assigns its creation timestamp, and confirms ION's acceptance from `ion.log`. It collects deliveries from `bprecvfile` and checks the restored envelope (header CRC32, length, TTL counted from Timestamp). `bpv7_wire.decode_bundle` decodes captured bundles and checks every block CRC over the received bytes. `python -m pbs_ion_demo` runs the demonstration: downlink, uplink, worked-example interoperability, and a contact gap in which one bundle is stored and forwarded and another expires in storage.
- `DOCS/PBS-ION-E2E-DEMO.md`, `DOCS/PBS-ION-MAPPING-PROFILE.md` (mapping profile and no-expiry lifetime of 2 147 483 647 000 ms for ION 4.2.0, PBS-DTN-MAP-01 Sections 6.1.1 and 6.3, PBS-DTN-MAP-02 Sections 4 and 5), `DOCS/PBS-ION-E2E-TEST-PLAN.md` (requirements, verification cross-reference matrix, test cases, procedures and records, in the form of NASA-HDBK-2203 topics 5.10, 5.11 and 5.14).
- Tests: `TESTS/test_ion_demo_units.py`, 35 tests that need no ION (UT-01 to UT-24); `TESTS/ion/test_ion_end_to_end.py`, 12 tests against ION (IT-01 to IT-11). They write an as-run record of measured values to `ion-test-results/`. The ION tests are skipped without ION, unless `PBS_ION_REQUIRED=1`.
- `scripts/build_ion.sh` and `scripts/ion-release.env`: build the pinned ION release, refusing a tag that does not resolve to the pinned commit. `requirements-ion-demo.txt` pins cbor2, pytest and PBS_LINK. CI job `ion-e2e` builds ION, runs every test with `PBS_ION_REQUIRED=1` and the demonstration, and uploads the records. `pytest.ini` declares the `ion` marker.

### PBS v1.5.0 (2026-10-06)

#### Fixed
- Bundles created without a caller-supplied `creation_seq` all carried sequence number 1, so two bundles created in the same millisecond had the same creation timestamp (RFC 9171 Section 4.2.7). `CreationTimestampCounter` now assigns the sequence number: 0 for the first bundle in a later millisecond and one higher for each further bundle; it is not reset when the clock steps back. `pbs_to_bpv7_bundle_mv` takes `creation_seq=None` and `sequence_counter`, which defaults to `ADAPTER_SEQUENCE_COUNTER`. A supplied `creation_seq` is used as given and does not advance the counter. The envelope Sequence field is not read (PBS-DTN-MAP-01 v1.5 Section 6.1). The worked example run lets the counter assign the sequence number (was 42).

#### Changed
- `default_lifetime_ms` is the no-expiry lifetime of PBS-DTN-MAP-01 v1.5 Section 6.1.1 and PBS-DTN-MAP-02 v1.5 Section 4. `bundle_lifetime_ms` raises `ValueError` outside 1 to 4 294 967 295 000 ms; it raised only for 0 or less. The 60 000 ms default and min(default, remaining TTL) for TTL > 0 are unchanged and meet Sections 6.1 and 6.1.1.
- `BPv7Primary` rejects bundle processing control flags that RFC 9171 Section 4.2.3 does not assign (`BPF_ASSIGNED_MASK`, 0x074067), including bits 7 and 8, which PBS-DTN-MAP-01 v1.5 Section 6.3 forbids for conveying priority. The adapter never set them.
- README, WHY-NOW and `DOCS/` cite PBS-ENV-01, PBS-DTN-MAP-01 and PBS-DTN-MAP-02 v1.5 (PBS v1.5.0). For TTL 0 they cite PBS-DTN-MAP-01 Section 6.1.1 and PBS-DTN-MAP-02 Section 4 in place of the statement that no PBS mapping defines the lifetime; Appendix B Section B.5 gives the 4294967295000 ms bound and the bundle protocol agent overflow condition, which the worked example does not check. Appendix A states that the worked example is not a bundle protocol agent and how it assigns the creation timestamp (Section A.6.1), that Priority and Sequence map to no primary block field and no reserved flag is set (Section A.6.3), and that TTL is not modified (PBS-ENV-01 Sections 12.3 and 15; PBS-DTN-MAP-01 Section 7.3), in place of the statement that PBS-ENV-01 Section 15 requires TTL decrement.

#### Added
- The planned design removed from README, WHY-NOW, `DOCS/` and the worked example comments is restored and labelled as planned (in development), alongside the statements of what the worked example implements: README Context and Intent, Planned Edge Adapter, Intended Audience, the planned `reference/` and `examples/` directories and Status; WHY-NOW's future authority landscape, architectural risk, purpose of publishing now and summary; in `DOCS/`, the planned adapter functions and inbound flow, the single active Authority Context with its Authority Identifier, Namespace Root and routing scope rules, endpoint identification, the Routing Resolver and Mapping Engine components and flows, the lunar demo Authority Context with its EID rules, the routing and interface configuration sections, applicability, extensibility and summaries; in the worked example, the Authority Context registry note and the production-gateway clock note. Where the restored text contradicted PBS v1.5.0 it is changed: destination and scope come from the Authority Context configuration or a PBS-AUTH-01 frame, since the PBS-ENV-01 header has no destination, scope or message identifier field (PBS-DTN-MAP-01 Sections 6.1 and 8); the payload block carries the whole envelope and inbound bundles yield the envelope verbatim (PBS-DTN-MAP-01 Sections 6.2 and 7.2); the routing stage configures the bundle protocol agent's routing (PBS-DTN-MAP-02 Section 8; PBS-ROUTE-01 Section 6); the routing default lifetime is bounded by the remaining TTL (PBS-DTN-MAP-01 Sections 6.1 and 6.1.1); the lunar demo source EID is the originating asset's own node ID (RFC 9171 Section 5.2); payload integrity rests on payload protection, PBS-SEC-B-01 or application checks, as the header CRC32 covers the 44-byte header only; the production gateway takes the creation timestamp from its bundle protocol agent (PBS-DTN-MAP-01 Section 6.1).
- README Standards Basis again includes Section 5, Alignment with Existing Standards (BPv7 as defined in RFC 9171 and corresponding CCSDS recommendations; operational DTN architectures that employ established bundle agents), and the worked example again carries, at the creation time computation in `pbs_to_bpv7_bundle_mv`, its original comment that implementations often supply DTN time via the local BP stack. Both passages are restored as originally written.
- 17 tests, 72 in total: the no-expiry lifetime bound (4 294 967 295 000 ms accepted, 4 294 967 296 000 ms rejected); the TTL 0 lifetime not less than the lifetime for any TTL from 1 s to 4 294 967 295 s; processing control flag bits 7 and 8 clear for priorities 0 to 4, with the Priority byte kept in the envelope; flags 0x80, 0x100, 0x180, 0x08 and 0x200000 rejected; sequence numbers 0, 1, 2 for three bundles in one millisecond and 0 in the next; different creation timestamps from the adapter counter; a caller-supplied `creation_seq` used as given.

### Before PBS v1.5.0

#### Added
- Initial repository structure for the PBS Edge Adapter Minimum Viable Reference.
- README: clauses implemented, tests, run instructions.
- PBS Edge Adapter reference specification (`PBS-EDGE-ADAPTER-MV`).
- Appendix A, PBS to BPv7 mapping (`DOCS/PBS-BPv7-MAPPING-APPENDIX.md`).
- Authority Context specification defining namespace and routing isolation: the configuration entry that supplies the bundle EIDs; routing isolation is applied through the bundle protocol agent's routing configuration (PBS-DTN-MAP-02 Section 8).
- Architecture and message flow documentation with reference diagrams.
- Appendix B, adapter configuration schema (`DOCS/PBS-EDGE-CONFIG-SCHEMA.md`).
- Worked example reference code demonstrating PBS envelope encapsulation into a BPv7 bundle.
- Validation test verifying BPv7 bundle structure, Primary Block CRC32C correctness, and payload integrity.
- Apache License 2.0 (`LICENSE`).
- Envelope validation in the worked example: `PBS_LINK.parse_envelope` checks magic, header CRC32, priority and payload length (PBS-ENV-01 Sections 13 and 14); input longer than 44 + `Size` bytes raises `EnvelopeLengthError`; an expired envelope, or one with less than 1 ms of TTL left, raises `EnvelopeExpiredError` (PBS-ENV-01 Section 12.2); a negative `creation_seq` or a non-positive `default_lifetime_ms` raises `ValueError`.
- Tests, 55 in total: creation time in DTN milliseconds with an injected clock (exact value); lifetime for TTL 0, TTL below and above the default, a partially aged envelope, a Timestamp ahead of the adapter clock and an expired envelope; creation time + lifetime never past the PBS expiry; corrupted header CRC32; trailing and missing bytes; payload block bytes equal to the envelope bytes; identical inputs giving identical bundles; the five RFC 7143 Appendix A.4 CRC32C examples; the source EID rule; flag 0x04 for a null source; rejection of a negative sequence number and a non-positive default lifetime.
- `pytest.ini` (`testpaths = TESTS`, `pythonpath = .`).
- CI workflow `.github/workflows/tests.yml`: on push and pull request, ubuntu-latest, Python 3.10, 3.11 and 3.12; installs pytest, cbor2 and PBS_LINK, runs `pytest -q` and the worked example. README badge.

#### Changed
- Bundle lifetime follows PBS-DTN-MAP-02 Section 4: min(configured default, TTL × 1000 − envelope age in ms, age rounded up and taken as 0 when the Timestamp is ahead of the adapter clock); TTL 0 uses the configured default. It was the configured value regardless of the TTL. Neither PBS-DTN-MAP-01 nor PBS-DTN-MAP-02 defines the lifetime for TTL 0; Appendix A Section A.6.2 and Appendix B Section B.5 state this and that the bundle protocol agent deletes the bundle, and the envelope with it, when that lifetime ends (RFC 9171 Section 5.5; PBS-DTN-MAP-01 Section 7.3). `pbs_to_bpv7_bundle_mv` takes `default_lifetime_ms` (was `lifetime_ms`) and `clock_us`, a callable returning Unix time in microseconds, read once for both the creation time and the envelope age.
- `AuthorityContextMap` rejects an entry that lacks `dest`, `src` or `report_to`, or whose `src` cannot serve as a source node ID. It accepts `dtn:none` and `ipn:0.0`; a dtn src only with an empty demux (RFC 9171 Section 4.2.5.1.1); and an ipn `src` with any service number, except `ipn:0.N` with N ≠ 0, the LocalNode node number 4294967295 and node numbers of 2^32 or more (RFC 9758 Sections 3.4.1, 5.3, 5.4, 9.2).
- The example ipn source EID is the administrative endpoint `ipn:4017.0` (was `ipn:4001.99`).
- The worked example imports PBS_LINK directly. The fallback that printed a warning and continued without it, and the `sys.path` entries pointing at a sibling PBS_LINK checkout, are removed. Console messages name PBS_LINK and report the creation time as a UTC instant and the lifetime.
- `DOCS/` describe the PBS-ENV-01 v1.3 header and the code: the Authority Context is a map of named entries selected per envelope; it is distinct from the PBS-AUTH-01 payload frame; the adapter performs no routing (PBS-DTN-MAP-02 Section 8); the configuration schema uses `default_lifetime_ms` and reserves the interface keys; the architecture diagrams mark the components the worked example does not implement. Appendix A states the source EID rule and the RFC 9171 Section 4.2.5.1.1 text it applies (Section A.5.3), the DTN time offset and its 5 s leap-second difference (Section A.6.1), the check order relative to PBS-ENV-01 Section 14 (Section A.3), the PBS-ENV-01 Section 15 TTL decrement the adapter does not perform (Section A.6.2), and that PBS-ADDR-01 payload addresses are not mapped to EIDs (Section A.5.1).
- README states the clauses the worked example implements and what the tests verify. README, `DOCS/PBS-EDGE-ADAPTER-MV.md` and WHY-NOW cite LNIS V005 (NASA, ESA and JAXA, 29 January 2025); WHY-NOW also cites NASA *2026 Civil Space Shortfalls* need statement 15.01 and the *FY26 Civil Space Shortfall Prioritization* that PBS-TRACE-NASA-FY26-01 cites, in place of general statements about future operations.

#### Fixed
- Bundle creation time was written in seconds since 2000-01-01, and the code comment said RFC 9171 DTN time is seconds. RFC 9171 Section 4.2.6 defines DTN time in milliseconds. Read as milliseconds, a 2026-10-06 creation time of 844 575 531 falls on 2000-01-10, so creation time + lifetime had passed and a bundle protocol agent treats the bundle as expired. Creation time is now Unix time in ms − 946 684 800 000.
- `pytest -q` from a clean checkout failed at collection with `ModuleNotFoundError: No module named 'pbs_edge_adapter_worked_example'`; `pytest.ini` puts the repository root on the import path.
- The example dtn source EID was `dtn://pbsf.example/edge/node-17`. Its demux is non-empty, and RFC 9171 Section 4.2.5.1.1 states that no such dtn EID may serve as a node ID. The example now uses the administrative endpoint `dtn://edge-17.pbsf.example/`, and `AuthorityContextMap` rejects a dtn `src` with a non-empty demux.
- A bundle whose source is the null endpoint (`dtn:none` or `ipn:0.0`) carried processing control flags 0. RFC 9171 Section 4.2.3 requires the "bundle must not be fragmented" flag; such a bundle now carries 0x04.
- `DOCS/PBS-BPv7-MAPPING-APPENDIX.md` Section A.3 listed envelope elements (PBS Version, Destination Identifier, Scope Identifier, Message Identifier) that the 44-byte header does not contain, and Section A.5 derived EIDs from them. Section A.3 lists the header fields; Section A.5 takes every EID from the Authority Context map; Section A.6.2 states the lifetime rule; Section A.7 carries the whole envelope; Section A.9 extracts the envelope verbatim (PBS-DTN-MAP-01 Section 7.2) instead of reconstructing it.
- Worked example and validation test import `PBS_LINK`, the package name PBS_LINK actually installs; `pbs_link` failed to import on case-sensitive systems, so `pytest -q` stopped at collection.
- README repository structure lists the directories that exist.
- README run instructions install PBS_LINK from its GitHub repository and run `pytest -q`.

---

## [0.1.0] — Reference Baseline

### Summary
- Established the **Minimum Viable Reference** for the PBS Edge Adapter concept.
- Documented the authority-aware edge mapping model between PBS envelopes and BPv7 bundles.
- Anchored all reference material to existing DTN standards and operational architectures.

### Notes
- Version numbers refer to **documentation and reference maturity**, not software releases.
- No stability, performance, or operational guarantees are implied by this reference baseline.

---

## Versioning Policy

- Version increments reflect **changes to specifications, documentation, or reference artifacts**.
- The term *release* denotes a published reference state suitable for review.
- No semantic versioning guarantees are implied beyond traceability of changes.

---
