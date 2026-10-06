# Authority Context Specification  
**Document ID:** PBS-AUTHORITY-CONTEXT  
**Status:** Reference Draft  
**Applies To:** PBS-EDGE-ADAPTER-MV  
**Steward:** Pale Blue Systems Foundation  

---

## 1. Purpose

This document defines the **Authority Context** of the PBS Edge Adapter: the configuration entry that sets the BPv7 addressing of an encapsulated PBS envelope. `AuthorityContextMap` in `pbs_edge_adapter_worked_example.py` implements it.

---

## 2. Definition

An Authority Context is a named entry in the adapter configuration. It holds three BPv7 endpoint identifiers (EIDs):

| Field | Content | RFC 9171 |
|-------|---------|----------|
| `dest` | Destination EID of every bundle built under this context | 4.3.1 |
| `src` | Source node ID: a node ID of the adapter's BP node, or `dtn:none` | 4.2.5.2, 4.3.1 |
| `report_to` | Report-to EID for bundle status reports | 4.3.1 |

The name is a string unique within the adapter configuration, for example `pbsf.luna.ops`.

---

## 3. Why Configuration Supplies the Addressing

- The PBS-ENV-01 v1.3 header carries a 16-byte Source ID. It has no destination, authority or scope field.
- A BPv7 primary block requires a destination EID, a source node ID and a report-to EID (RFC 9171 Section 4.3.1).
- PBS-DTN-MAP-01 Sections 6.1 and 8 configure the destination EID at the gateway, not in the envelope.
- PBS-DTN-MAP-02 Section 3 requires the mapping to BP EIDs to be deterministic, stable for the duration the mission transaction requires, and to preserve authority scope in the mapping registry or binding context.

The Authority Context map is that binding context.

---

## 4. Relationship to PBS-AUTH-01

PBS-AUTH-01 v1.4 (Authority and Scope Context) carries an authority identifier, role and policy epoch as PBS-MUX frame type `0x08` inside the envelope payload. PBS-SEC-B authenticates it when used for protected operations. The edge adapter does not read the envelope payload. It does not parse, validate or act on PBS-AUTH-01 frames, and it performs no command authorization (PBS-AUTH-REQ-003). These remain functions of the receiving PBS node.

---

## 5. Selection

The adapter configuration holds a map of Authority Contexts. Each envelope is encapsulated under exactly one context, named by the caller (the `authority_context` argument of `pbs_to_bpv7_bundle_mv`). The envelope does not name the context. This document does not specify how a deployment chooses the name for a given envelope.

---

## 6. Validation

`AuthorityContextMap` validates the map when it is constructed:

- Each entry has `dest`, `src` and `report_to`. A missing field raises `ValueError`.
- Each `src` is a node ID or `dtn:none`. A dtn-scheme EID qualifies only with an empty demux, for example `dtn://edge-17.pbsf.example/` (RFC 9171 Section 4.2.5.1.1). An ipn-scheme EID qualifies only with service number 0, for example `ipn:4017.0` (Section 4.2.5.1.2). Any other `src` raises `ValueError`.

Resolving a name absent from the map raises `KeyError`.

---

## 7. Determinism and Separation

A given context name always resolves to the same three EIDs. Envelopes encapsulated under different contexts carry the EIDs of their own contexts. Separation between authorities in the DTN follows from the EID namespaces assigned to each context and from bundle protocol agent policy. The adapter performs no cross-context inference, arbitration or routing.

---

## 8. Inbound Direction

The worked example implements no inbound processing. Under PBS-DTN-MAP-01 Section 7.2, the receiving gateway extracts the envelope from the payload block verbatim. No envelope field is derived from bundle EIDs.

---

## 9. Example

The worked example configures two contexts:

| Name | `dest` | `src` | `report_to` |
|------|--------|-------|-------------|
| `pbsf.luna.ops` | `dtn://pbsf.example/luna/ops` | `dtn://edge-17.pbsf.example/` | `dtn://pbsf.example/ops/reports` |
| `pbsf.mars.science` | `ipn:4001.10` | `ipn:4017.0` | `ipn:4001.11` |

The `pbsf.example` names and ipn node numbers are illustrative.
