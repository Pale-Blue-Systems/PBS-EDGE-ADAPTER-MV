# Why Now — Basis for the PBS Edge Adapter Reference

The PBS Edge Adapter defines where and how PBS messages enter a shared BPv7 network: which endpoint addresses they take and how long the network may hold them. This document records the published sources that make that boundary a present engineering need.

---

## 1. Basis

- **Multiple providers, one network service.** The LunaNet Interoperability Specification, Version 5 (LNIS V005, 29 January 2025) was written and approved by NASA, ESA and JAXA (Section 1.1). It describes LunaNet as a network of cooperating networks. It states that LunaNet 1.0, the initial instantiation, will include LunaNet service providers from NASA, ESA and Japan, comprising government systems or commercial service providers under contract to an agency, and that no single provider is required to meet all network services for all users (Section 1). <https://www.nasa.gov/wp-content/uploads/2025/02/lunanet-interoperability-specification-v5-baseline.pdf>
- **BPv7 at the DTN layer.** LNIS V005 Section 3.1.2: "The Bundle Protocol version 7 (BPv7) shall be used" for DTN network communications services.
- **Addresses not yet registered.** LNIS V005 Section 3.1.3 states that LNIS-TBD-AD0006, which will list the addresses and IDs to be registered for LunaNet, will be developed in future LNIS versions.
- **Shared surface communications.** NASA *2026 Civil Space Shortfalls* (released 12 January 2026), shortfall 15, "Operate multi-agent robotic and crewed systems in cooperative planetary surface activities", need statement 15.01: "Provide scalable, reliable surface-to-surface communications between assets on the lunar surface that is usable by all participating elements." <https://www.nasa.gov/wp-content/uploads/2026/03/2026-civil-space-shortfalls.pdf>. PBS v1.4 traces to it in PBS-TRACE-NASA-FY26-01, which cites the same need statement from Appendix A of NASA STMD, *FY26 Civil Space Shortfall Prioritization* (May 2026), <https://www.nasa.gov/wp-content/uploads/2026/05/fy26-civil-space-shortfall-prioritization.pdf>.

---

## 2. The Boundary

A PBS-ENV-01 v1.3 envelope has a fixed 44-byte header of eleven fields: Magic, Priority, Flags, two reserved fields, Sequence, Source ID, Timestamp, Size, TTL and CRC32. It has no destination, authority or scope field. A BPv7 primary block requires a destination EID, a source node ID, a report-to EID, a creation time and a lifetime (RFC 9171 Section 4.3.1). A PBS-to-BPv7 gateway therefore supplies the addressing from its own configuration and derives the lifetime from the PBS TTL. On a network shared by several providers and authorities, these two choices determine which namespace a PBS message enters and how long the network may hold it.

Three errors at this boundary have defined consequences:

- **Lifetime.** A bundle lifetime set independently of the TTL lets the network deliver an envelope after its PBS expiry. PBS-DTN-MAP-02 Section 4 prohibits this.
- **Time base.** RFC 9171 DTN time is in milliseconds (Section 4.2.6). A creation time written in seconds places the bundle's expiration in January 2000, so a bundle protocol agent treats the bundle as expired. The worked example in this repository had this defect; CHANGELOG.md records the fix.
- **Addressing.** The PBS-ENV-01 v1.3 header names no destination. A destination address, when present, is a PBS-ADDR-01 TLV in the payload (PBS-ADDR-01 Section 3.1). Without an explicit, deterministic map from authority to EIDs, a gateway has no defined destination EID for the bundle (PBS-DTN-MAP-02 Section 3).

---

## 3. Why at the Edge

- The bundle protocol agent carries the envelope as an opaque payload. Neither PBS-ENV-01 nor BPv7 changes (PBS-DTN-MAP-01 Sections 6.2 and 6.4).
- The encapsulating gateway sets the BPv7 lifetime, and it reads the PBS Timestamp and TTL when it does.
- Addressing is configuration, so it can follow the LunaNet address registration when LNIS-TBD-AD0006 is published, without a change to PBS or to the agent.

---

## 4. What This Repository Provides

- The mapping specification, Authority Context definition and configuration schema (`DOCS/`).
- A worked example that validates the envelope with PBS_LINK, takes the bundle EIDs from the Authority Context map, writes the creation time in DTN milliseconds, bounds the lifetime per PBS-DTN-MAP-02 Section 4, and carries the envelope unmodified, with 55 tests run in CI.
