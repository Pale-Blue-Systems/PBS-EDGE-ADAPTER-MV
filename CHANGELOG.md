# Changelog  
All notable changes to this repository are documented in this file.

This project follows a **reference-driven change history**, where entries describe
documentation, specifications, and illustrative artifacts rather than production releases.

---

## [Unreleased]

### Added
- Initial repository structure for the PBS Edge Adapter Minimum Viable Reference.
- README: clauses implemented, tests, run instructions.
- PBS Edge Adapter reference specification (`PBS-EDGE-ADAPTER-MV`).
- Appendix A, PBS to BPv7 mapping (`DOCS/PBS-BPv7-MAPPING-APPENDIX.md`).
- Authority Context specification: the configuration entry that supplies the bundle EIDs.
- Architecture and message flow documentation with reference diagrams.
- Appendix B, adapter configuration schema (`DOCS/PBS-EDGE-CONFIG-SCHEMA.md`).
- Worked example reference code demonstrating PBS envelope encapsulation into a BPv7 bundle.
- Validation test verifying BPv7 bundle structure, Primary Block CRC32C correctness, and payload integrity.
- Apache License 2.0 (`LICENSE`).
- Envelope validation in the worked example: `PBS_LINK.parse_envelope` checks magic, header CRC32, priority and payload length (PBS-ENV-01 Sections 13 and 14); input longer than 44 + `Size` bytes raises `EnvelopeLengthError`; an expired envelope, or one with less than 1 ms of TTL left, raises `EnvelopeExpiredError` (PBS-ENV-01 Section 12.2); a negative `creation_seq` or a non-positive `default_lifetime_ms` raises `ValueError`.
- Tests, 53 in total: creation time in DTN milliseconds with an injected clock (exact value); lifetime for TTL 0, TTL below and above the default, a partially aged envelope, a Timestamp ahead of the adapter clock and an expired envelope; creation time + lifetime never past the PBS expiry; corrupted header CRC32; trailing and missing bytes; payload block bytes equal to the envelope bytes; identical inputs giving identical bundles; the five RFC 7143 Appendix A.4 CRC32C examples; the source EID rule; flag 0x04 for a null source; rejection of a negative sequence number and a non-positive default lifetime.
- `pytest.ini` (`testpaths = TESTS`, `pythonpath = .`).
- CI workflow `.github/workflows/tests.yml`: on push and pull request, ubuntu-latest, Python 3.10, 3.11 and 3.12; installs pytest, cbor2 and PBS_LINK, runs `pytest -q` and the worked example. README badge.

### Changed
- Bundle lifetime follows PBS-DTN-MAP-02 Section 4: min(configured default, TTL × 1000 − envelope age in ms, age rounded up and taken as 0 when the Timestamp is ahead of the adapter clock); TTL 0 uses the configured default. It was the configured value regardless of the TTL. Neither PBS-DTN-MAP-01 nor PBS-DTN-MAP-02 defines the lifetime for TTL 0; Appendix A Section A.6.2 and Appendix B Section B.5 state this and that the bundle protocol agent deletes the bundle, and the envelope with it, when that lifetime ends (RFC 9171 Section 5.5; PBS-DTN-MAP-01 Section 7.3). `pbs_to_bpv7_bundle_mv` takes `default_lifetime_ms` (was `lifetime_ms`) and `clock_us`, a callable returning Unix time in microseconds, read once for both the creation time and the envelope age.
- `AuthorityContextMap` rejects an entry that lacks `dest`, `src` or `report_to`, or whose `src` cannot serve as a source node ID. It accepts `dtn:none` and `ipn:0.0`; a dtn src only with an empty demux (RFC 9171 Section 4.2.5.1.1); and an ipn `src` with any service number, except `ipn:0.N` with N ≠ 0 (RFC 9758 Sections 3.4.1, 5.3).
- The example ipn source EID is the administrative endpoint `ipn:4017.0` (was `ipn:4001.99`).
- The worked example imports PBS_LINK directly. The fallback that printed a warning and continued without it, and the `sys.path` entries pointing at a sibling PBS_LINK checkout, are removed. Console messages name PBS_LINK and report the creation time as a UTC instant and the lifetime.
- `DOCS/` describe the PBS-ENV-01 v1.3 header and the code: the Authority Context is a map of named entries selected per envelope; it is distinct from the PBS-AUTH-01 payload frame; the adapter performs no routing (PBS-DTN-MAP-02 Section 8); the configuration schema uses `default_lifetime_ms` and reserves the interface keys; the architecture diagrams mark the components the worked example does not implement. Appendix A states the source EID rule and the RFC 9171 Section 4.2.5.1.1 text it applies (Section A.5.3), the DTN time offset and its 5 s leap-second difference (Section A.6.1), the check order relative to PBS-ENV-01 Section 14 (Section A.3), the PBS-ENV-01 Section 15 TTL decrement the adapter does not perform (Section A.6.2), and that PBS-ADDR-01 payload addresses are not mapped to EIDs (Section A.5.1).
- README states the clauses the worked example implements and what the tests verify. WHY-NOW cites LNIS V005, NASA *2026 Civil Space Shortfalls* need statement 15.01 and the *FY26 Civil Space Shortfall Prioritization* that PBS-TRACE-NASA-FY26-01 cites, in place of general statements about future operations.

### Fixed
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
