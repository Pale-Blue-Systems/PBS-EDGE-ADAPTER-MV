# Changelog  
All notable changes to this repository are documented in this file.

This project follows a **reference-driven change history**, where entries describe
documentation, specifications, and illustrative artifacts rather than production releases.

---

## [Unreleased]

### Added
- Initial repository structure for the PBS Edge Adapter Minimum Viable Reference.
- README describing scope, intent, and alignment with DTN and BPv7 standards.
- PBS Edge Adapter reference specification (`PBS-EDGE-ADAPTER-MV`).
- PBS ↔ BPv7 Mapping Appendix defining deterministic encapsulation rules.
- Authority Context specification defining namespace and routing isolation.
- Architecture and message flow documentation with reference diagrams.
- Configuration Schema Appendix defining authoritative adapter configuration inputs.
- Worked example reference code demonstrating PBS envelope encapsulation into a BPv7 bundle.
- Validation test verifying BPv7 bundle structure, Primary Block CRC32C correctness, and payload integrity.
- Apache License 2.0 (`LICENSE`).

### Fixed
- Worked example and validation test import `PBS_LINK`, the package name PBS_LINK actually installs; `pbs_link` failed to import on case-sensitive systems, so `pytest -q` stopped at collection.
- README repository structure lists the directories that exist.
- Instructions for running validation tests.

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
