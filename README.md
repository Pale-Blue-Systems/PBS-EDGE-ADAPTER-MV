# PBS Edge Adapter – Minimum Viable Reference (PBS-EDGE-ADAPTER-MV)

This repository documents and demonstrates the **Pale Blue Systems (PBS) Edge Adapter** concept through a **minimum viable reference design** aligned with existing Delay/Disruption-Tolerant Networking (DTN) standards.

The purpose of this repository is to provide a **clear, technically accurate description** of how PBS envelopes can be mapped at the network edge into **Bundle Protocol Version 7 (BPv7)**–based transport environments, using established DTN architectures.

This work is published to support technical review, standards discussion, and interoperability analysis.

---

## Context and Intent

Pale Blue Systems publishes this work in anticipation of a future space environment that includes multiple space agencies, commercial operators, private missions, and long-lived infrastructure operating concurrently beyond Earth.

This repository does not claim to solve a current operational deficiency. It contributes to early architectural discussion by making future authority and interoperability considerations explicit—before infrastructure, protocols, and assumptions become fixed.

Additional context on why this work is published now is available in [`WHY-NOW.md`](WHY-NOW.md).

---

## Scope and Intent

The PBS Edge Adapter serves as a **boundary component** between:

- **PBS envelopes**, which carry authority-aware routing and scope metadata, and  
- **BPv7 bundle agents**, which provide delay-tolerant transport across heterogeneous and disrupted networks.

This repository focuses on **clarifying that boundary** and demonstrating how the mapping can be performed deterministically and transparently.

---

## What This Repository Provides

### 1. Reference Architecture

A documented architectural model showing where the PBS Edge Adapter sits within a DTN stack, including its relationship to:

- PBS envelope producers and consumers  
- Authority Context configuration  
- BPv7 bundle agents (e.g., ION)

This architecture is intended to be readable and reviewable by engineers familiar with DTN, CCSDS, and space communications systems.

---

### 2. PBS → BPv7 Mapping Specification

A concrete, inspectable description of how:

- PBS envelope fields are mapped to BPv7 bundle elements  
- PBS authority and scope identifiers are translated into BPv7 Endpoint Identifiers (EIDs)  
- PBS payloads are encapsulated as opaque BPv7 payload blocks  

The mapping is designed to be **deterministic**, **lossless**, and **transport-agnostic**.

---

### 3. Authority-Aware Edge Behavior

The reference design treats **Authority Context** as a first-class input to routing and encapsulation decisions at the edge.

This ensures that PBS envelopes originating from different authorities remain logically separated while sharing common transport infrastructure.

---

### 4. Minimal Reference Logic

Illustrative reference logic (expressed in Python for clarity and accessibility) demonstrates:

- PBS envelope parsing and validation  
- Authority Context binding  
- Construction of BPv7 bundle structures suitable for injection into an existing BP agent  

This logic is intended to support understanding, experimentation, and verification of the mapping rules described in the specification.

---

### 5. Alignment with Existing Standards

The reference design aligns with:

- **Bundle Protocol Version 7 (BPv7)** as defined in RFC 9171 and corresponding CCSDS recommendations  
- Operational DTN architectures that employ established bundle agents  

By grounding the PBS Edge Adapter in existing standards, the repository provides a concrete basis for interoperability analysis and future discussion.

---

## Intended Audience

This repository is written for:

- Space and DTN engineers evaluating interoperability approaches  
- Standards bodies and working groups reviewing edge-mapping concepts  
- Researchers and system architects exploring authority-aware networking models  
- Organizations assessing how PBS envelopes integrate with existing DTN infrastructure  

---

## Repository Structure (High Level)

- `README.md` — Overview, context, and intent  
- `WHY-NOW.md` — Architectural motivation and future context  
- `DOCS/` — Architecture, BPv7 mapping, authority context, and configuration specifications  
- `pbs_edge_adapter_worked_example.py` — Worked example: a PBS envelope encapsulated into a BPv7 bundle  
- `TESTS/` — Validation test for the worked example  
- `CHANGELOG.md` — Change history  

---

## Validation Test — How to Run

This repository includes a reference validation test that verifies:

- BPv7 bundle structural correctness  
- Primary Block field layout and version  
- Primary Block CRC32C computation  
- Payload block byte-for-byte integrity  

To run the validation locally:

```bash
pip install pytest cbor2 git+https://github.com/Pale-Blue-Systems/PBS_LINK.git
pytest -q
```

The validation test consumes the worked example reference code and confirms that the generated BPv7 bundle conforms to the mapping and structural rules documented in this repository.

---

## Status

This repository represents a **minimum viable reference** for the PBS Edge Adapter concept.  
It is published to support technical clarity, review, and discussion as PBS standards evolve.

The current PBS-to-BPv7 mapping profile in the protocol specifications is [`PBS-DTN-MAP-02`](https://github.com/Pale-Blue-Systems/PBS-PROTOCOL-OPEN/blob/main/PBS-RFC-LIB/PBS-DTN-MAP-02.md) (PBS v1.4).

---

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
