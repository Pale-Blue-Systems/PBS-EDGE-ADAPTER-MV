# Appendix B — PBS Edge Adapter Configuration Schema
**Document ID:** PBS-EDGE-CONFIG-SCHEMA  
**Status:** Reference Draft  
**Applies To:** PBS-EDGE-ADAPTER-MV  

---

## B.1 Purpose

This appendix defines the configuration inputs of a PBS Edge Adapter instance. The worked example has no configuration loader. It takes the equivalent values as Python arguments:

| Configuration key | Worked example | Status |
|-------------------|----------------|--------|
| `authority_contexts` | `AuthorityContextMap(table=...)` | Implemented |
| `bundle.default_lifetime_ms` | `default_lifetime_ms` argument of `pbs_to_bpv7_bundle_mv` | Implemented |
| `adapter` | — | Not implemented |
| `interfaces` | — | Reserved; not specified in this revision |

`pbs_to_bpv7_bundle_mv` fixes the primary block CRC type at 2 (CRC32C) and the payload block CRC type at 0. Neither is a configuration input.

---

## B.2 Top-Level Structure

Configuration is a structured document (YAML shown) loaded before the adapter starts.

```yaml
adapter:
  id: string
  version: string

authority_contexts:
  <name>:
    dest: string          # BPv7 EID, dtn or ipn URI
    src: string           # node ID URI: "dtn://node-name/", "ipn:node.service", "dtn:none" or "ipn:0.0"
    report_to: string     # BPv7 EID, dtn or ipn URI

bundle:
  default_lifetime_ms: integer

interfaces: {}            # reserved
```

---

## B.3 Adapter Section

```yaml
adapter:
  id: "pbs-edge-adapter-alpha"
  version: "0.1"
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Identifier of the adapter instance, for diagnostics |
| `version` | string | Configuration version label |

---

## B.4 Authority Contexts Section

```yaml
authority_contexts:
  pbsf.luna.ops:
    dest: "dtn://pbsf.example/luna/ops"
    src: "dtn://edge-17.pbsf.example/"
    report_to: "dtn://pbsf.example/ops/reports"
  pbsf.mars.science:
    dest: "ipn:4001.10"
    src: "ipn:4017.0"
    report_to: "ipn:4001.11"
```

| Field | Type | Description |
|-------|------|-------------|
| `<name>` | string key | Authority context name, unique in this file |
| `dest` | EID URI | Destination EID (RFC 9171 Section 4.3.1) |
| `src` | EID URI | Source node ID of the adapter's BP node, or the null endpoint `dtn:none` or `ipn:0.0`. A dtn src is accepted only with an empty demux (RFC 9171 Section 4.2.5.1.1). An ipn `src` is accepted with any service number (RFC 9758 Section 5.3), except `ipn:0.N` with N ≠ 0 (RFC 9758 Section 3.4.1). |
| `report_to` | EID URI | Report-to EID (RFC 9171 Section 4.3.1) |

EID URIs use the dtn scheme (`dtn://node-name/demux` or `dtn:none`) or the ipn scheme (`ipn:node.service`), encoded in the bundle as RFC 9171 Section 4.2.5.1 specifies. No envelope field enters any EID. [PBS-AUTHORITY-CONTEXT](PBS-AUTHORITY-CONTEXT.md) defines the Authority Context.

---

## B.5 Bundle Section

```yaml
bundle:
  default_lifetime_ms: 60000
```

| Field | Type | Description |
|-------|------|-------------|
| `default_lifetime_ms` | integer, ms, > 0 | Bundle lifetime for an envelope with TTL 0, and the upper bound of the lifetime otherwise. The remaining PBS TTL bounds the lifetime further (PBS-DTN-MAP-02 Section 4; [PBS-BPv7-MAPPING-APPENDIX](PBS-BPv7-MAPPING-APPENDIX.md) Section A.6.2). |

An envelope with TTL 0 never expires (PBS-ENV-01 Section 12.1). Neither PBS-DTN-MAP-01 nor PBS-DTN-MAP-02 defines the bundle lifetime for TTL 0; the adapter uses `default_lifetime_ms`. When the bundle's age exceeds it, the bundle protocol agent deletes the bundle (RFC 9171 Section 5.5), and the envelope it carries is discarded (PBS-DTN-MAP-01 Section 7.3).

`pbs_to_bpv7_bundle_mv` defaults `default_lifetime_ms` to 60 000 ms; the worked example run passes 300 000 ms.

---

## B.6 Routing

The configuration has no routing section. Contact plans, route computation and convergence-layer selection are DTN and network-service functions (PBS-DTN-MAP-02 Section 8). They are configured in the bundle protocol agent, not in the adapter.

---

## B.7 Interfaces

`interfaces` is reserved for the ingress, egress and bundle protocol agent bindings. This revision specifies no keys under it. The worked example has no ingress, egress or agent interface.

---

## B.8 Validation

A valid configuration has:

- at least one entry under `authority_contexts`;
- `dest`, `src` and `report_to` in every entry;
- as every `src`, a source node ID that Section B.4 accepts;
- a positive integer `bundle.default_lifetime_ms`.

The worked example enforces the second and third rules when `AuthorityContextMap` is constructed, and the fourth when it selects a lifetime.

---

## B.9 Determinism

With identical configuration, the same authority context name always yields the same three EIDs, and the same envelope, sequence number and clock reading always yield the same lifetime and bundle bytes.
