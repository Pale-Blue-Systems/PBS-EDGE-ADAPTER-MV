# Authority Context Specification  
**Document ID:** PBS-AUTHORITY-CONTEXT  
**Status:** Reference Draft  
**Applies To:** PBS-EDGE-ADAPTER-MV  
**Steward:** Pale Blue Systems Foundation  

---

## 1. Purpose

This document defines the **Authority Context** of the PBS Edge Adapter: the configuration entry that sets the BPv7 addressing of an encapsulated PBS envelope. `AuthorityContextMap` in `pbs_edge_adapter_worked_example.py` implements it.

Pale Blue Systems is building the full Authority Context model that this document also specifies, in the sections marked as planned. The Authority Context establishes the **administrative and routing namespace** within which PBS envelopes are interpreted and mapped into Bundle Protocol Version 7 (BPv7) transport environments.

This specification provides a deterministic and inspectable mechanism for namespace separation across shared transport infrastructure.

---

## 2. Definition

An Authority Context is a named entry in the adapter configuration. It holds three BPv7 endpoint identifiers (EIDs):

| Field | Content | RFC 9171 |
|-------|---------|----------|
| `dest` | Destination EID of every bundle built under this context | 4.3.1 |
| `src` | Source node ID: a node ID of the adapter's BP node (a dtn EID with an empty demux, or an ipn EID), or the null endpoint (`dtn:none`, `ipn:0.0`) | 4.2.5.1.1, 4.2.5.2, 4.3.1; RFC 9758 Section 5.3 |
| `report_to` | Report-to EID for bundle status reports | 4.3.1 |

The name is a string unique within the adapter configuration, for example `pbsf.luna.ops`.

### 2.1 Planned Authority Context Model (in development)

An **Authority Context** represents a single, coherent authority domain under which:

- PBS identifiers are interpreted
- Routing namespaces are resolved
- BPv7 Endpoint Identifiers (EIDs) are constructed

Each PBS Edge Adapter instance operates under **exactly one active Authority Context** at any given time.

An Authority Context consists of the following components:

| Component | Description |
|-----------|-------------|
| Authority Identifier | A unique identifier representing the administrative authority |
| Namespace Root | The root namespace used when constructing BPv7 EIDs |
| Routing Scope Rules | Deterministic rules for interpreting PBS scope identifiers, which deployment configuration or a PBS-AUTH-01 frame sets (PBS-ADDR-01 Section 3; the envelope header carries none) |
| Adapter Configuration Binding | Static binding between the adapter instance and the authority |

All components are defined through explicit configuration.

### 2.2 Authority Identifier (planned)

The **Authority Identifier** uniquely names the authority domain.

Characteristics:

- Stable across time
- Unique within the deployment environment
- Opaque to the adapter beyond equality comparison

The Authority Identifier is not transmitted within the PBS payload. It is adapter configuration, distinct from the `authority_id` that a PBS-AUTH-01 frame carries in the payload (Section 4).

### 2.3 Namespace Root (planned)

The **Namespace Root** defines the top-level namespace used when constructing BPv7 Endpoint Identifiers.

Examples include, but are not limited to:

- A domain-style namespace
- A numeric namespace
- A structured hierarchical identifier

The Namespace Root is combined with PBS routing identifiers to form complete BPv7 EIDs: with the envelope Source ID for the source EID (PBS-DTN-MAP-01 Section 8), and with identifiers configured at the gateway for the destination EID (PBS-DTN-MAP-01 Sections 6.1 and 8).

---

## 3. Why Configuration Supplies the Addressing

- The PBS-ENV-01 v1.3 header carries a 16-byte Source ID. It has no destination, authority or scope field. A destination address, when present, is a PBS-ADDR-01 TLV in the payload (PBS-ADDR-01 Section 3.1). The adapter does not read PBS-ADDR-01 address TLVs and does not map them to EIDs (PBS-ADDR-01 Section 11; PBS-DTN-MAP-02 Section 3).
- A BPv7 primary block requires a destination EID, a source node ID and a report-to EID (RFC 9171 Section 4.3.1).
- PBS-DTN-MAP-01 Sections 6.1 and 8 configure the destination EID at the gateway, not in the envelope.
- PBS-DTN-MAP-02 Section 3 requires the mapping to BP EIDs to be deterministic, stable for the duration the mission transaction requires, and to preserve authority scope in the mapping registry or binding context.

The Authority Context map is that binding context.

### 3.1 Motivation

Distributed communication environments frequently involve:

- Multiple organizations
- Multiple missions or programs
- Shared physical or logical transport infrastructure

The Authority Context provides a means to ensure that PBS envelopes originating from different authorities remain **logically distinct**, even when they traverse common DTN links.

### 3.2 Planned Use in PBS → BPv7 Mapping (in development)

When processing a PBS envelope, the adapter uses the active Authority Context to:

1. Interpret the PBS source identifier (the envelope Source ID) and the destination identifiers configured in the Authority Context (the envelope header carries no destination; PBS-DTN-MAP-01 Sections 6.1 and 8)
2. Resolve scope identifiers, from the Authority Context configuration or a PBS-AUTH-01 frame, within the authority namespace
3. Construct BPv7 Source and Destination EIDs
4. Ensure deterministic namespace separation

No cross-authority inference is performed.

---

## 4. Relationship to PBS-AUTH-01

PBS-AUTH-01 v1.4 (Authority and Scope Context) carries an authority identifier, role and policy epoch as PBS-MUX frame type `0x08` inside the envelope payload. PBS-SEC-B authenticates it when used for protected operations. The edge adapter does not read the envelope payload. It does not parse, validate or act on PBS-AUTH-01 frames, and it performs no command authorization (PBS-AUTH-REQ-003). These remain functions of the receiving PBS node.

---

## 5. Selection

The adapter configuration holds a map of Authority Contexts. Each envelope is encapsulated under exactly one context, named by the caller (the `authority_context` argument of `pbs_to_bpv7_bundle_mv`). The envelope does not name the context. This document does not specify how a deployment chooses the name for a given envelope.

### 5.1 Planned Adapter Binding (in development)

Each PBS Edge Adapter instance is bound to one Authority Context via configuration at initialization time.

The binding is static for the lifetime of the adapter instance.

### 5.2 Configuration Inputs (planned)

Authority Context configuration includes:

- Authority Identifier
- Namespace Root
- EID construction rules
- Default routing parameters, which the adapter supplies to the bundle protocol agent as routing configuration (PBS-DTN-MAP-02 Section 8)

Configuration is explicit and local to the adapter instance.

---

## 6. Validation

`AuthorityContextMap` validates the map when it is constructed:

- Each entry has `dest`, `src` and `report_to`. A missing field raises `ValueError`.
- Each `src` is a node ID of the adapter's BP node, or the null endpoint `dtn:none` or `ipn:0.0`. A dtn src is accepted only with an empty demux (RFC 9171 Section 4.2.5.1.1), for example `dtn://edge-17.pbsf.example/`. An ipn `src` is accepted with any service number (RFC 9758 Section 5.3), except `ipn:0.N` with N ≠ 0 (RFC 9758 Section 3.4.1), the LocalNode node number 4294967295 (Section 5.4) and node numbers of 2^32 or more (Section 9.2). RFC 9171 Section 4.2.5.2 states that the EID of any singleton endpoint may serve as a node ID; Section 4.2.5.1.1 excludes dtn-scheme EIDs with a non-empty demux. The adapter applies the Section 4.2.5.1.1 rule, so it rejects singleton dtn EIDs such as `dtn://pbsf.example/edge/node-17` that Section 4.2.5.2 alone would admit. Any other `src` raises `ValueError`. [PBS-BPv7-MAPPING-APPENDIX](PBS-BPv7-MAPPING-APPENDIX.md) Section A.5.3 states the rule and the RFC text it applies.

Resolving a name absent from the map raises `KeyError`.

---

## 7. Determinism and Separation

A given context name always resolves to the same three EIDs. Envelopes encapsulated under different contexts carry the EIDs of their own contexts. Separation between authorities in the DTN follows from the EID namespaces assigned to each context and from bundle protocol agent policy. The adapter performs no cross-context inference, arbitration or routing.

### 7.1 Planned Authority Isolation (in development)

Authority Contexts provide **logical isolation** through:

- Namespace separation
- Deterministic routing resolution, applied as configuration of the bundle protocol agent's routing (PBS-DTN-MAP-02 Section 8)
- Explicit configuration boundaries

Isolation is achieved without requiring separate transport infrastructure.

---

## 8. Inbound Direction

The worked example implements no inbound processing. Under PBS-DTN-MAP-01 Section 7.2, the receiving gateway extracts the envelope from the payload block verbatim. No envelope field is derived from bundle EIDs.

### 8.1 Planned Inbound Use (in development)

When receiving a BPv7 bundle, the adapter:

1. Parses the Source and Destination EIDs
2. Interprets them relative to the active Authority Context
3. Resolves PBS source and destination identifiers from them for delivery; the envelope itself is extracted verbatim from the payload block and not modified (PBS-DTN-MAP-01 Section 7.2)
4. Emits the PBS envelope within the same authority domain

Bundles whose EIDs do not align with the active Authority Context are not restored.

---

## 9. Example

The worked example configures two contexts:

| Name | `dest` | `src` | `report_to` |
|------|--------|-------|-------------|
| `pbsf.luna.ops` | `dtn://pbsf.example/luna/ops` | `dtn://edge-17.pbsf.example/` | `dtn://pbsf.example/ops/reports` |
| `pbsf.mars.science` | `ipn:4001.10` | `ipn:4017.0` | `ipn:4001.11` |

The `pbsf.example` names and ipn node numbers are illustrative.

---

## 10. Applicability

The Authority Context model applies to environments including:

- Multi-mission space systems
- Joint civil, commercial, and scientific networks
- Federated DTN deployments
- Intermittently connected and delay-tolerant networks

---

## 11. Extensibility

Future extensions may introduce:

- Multi-context adapters
- Dynamic context selection
- Federation-aware context resolution

Such extensions do not alter the correctness of the model defined herein.

---

## 12. Summary

The planned Authority Context model establishes a clear and deterministic foundation for authority-aware routing at the network edge, which the bundle protocol agent performs from the routing configuration the adapter supplies (PBS-DTN-MAP-02 Section 8).

By explicitly binding PBS Edge Adapters to a single authority namespace, the model enables safe coexistence of multiple authorities over shared BPv7 transport environments.
