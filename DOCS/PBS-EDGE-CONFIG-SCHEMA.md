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

Pale Blue Systems is building the full configuration schema, given in the sections marked as planned. The schema specifies how an adapter instance is bound to:
- a single Authority Context,
- deterministic routing rules, applied as configuration of the bundle protocol agent's routing (PBS-DTN-MAP-02 Section 8),
- BPv7 endpoint construction parameters, and
- ingress / egress interfaces.

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

The planned configuration model (in development) is composed of four top-level sections:

1. Adapter Identity
2. Authority Context
3. Routing Configuration
4. Interface Bindings

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
| `src` | EID URI | Source node ID of the adapter's BP node, or the null endpoint `dtn:none` or `ipn:0.0`. A dtn src is accepted only with an empty demux (RFC 9171 Section 4.2.5.1.1). An ipn `src` is accepted with any service number (RFC 9758 Section 5.3), except `ipn:0.N` with N ≠ 0 (RFC 9758 Section 3.4.1), the LocalNode node number 4294967295 (Section 5.4) and node numbers of 2^32 or more (Section 9.2). |
| `report_to` | EID URI | Report-to EID (RFC 9171 Section 4.3.1) |

EID URIs use the dtn scheme (`dtn://node-name/demux` or `dtn:none`) or the ipn scheme (`ipn:node.service`), encoded in the bundle as RFC 9171 Section 4.2.5.1 specifies. No envelope field enters any EID. [PBS-AUTHORITY-CONTEXT](PBS-AUTHORITY-CONTEXT.md) defines the Authority Context.

### B.4.1 Planned Authority Context Definition (in development)

The lunar demo configuration:

```yaml
authority_context:
  authority_id: "pbsf-lunar-demo"
  namespace_root: "dtn://pbsf/lunar"
  eid_scheme: "dtn"
  eid_rules:
    destination_format: "{namespace_root}/{scope}/{destination}"
    source_format: "dtn://{source}.lunar.pbsf/"
```

| Field | Type | Description |
|-------|------|-------------|
| `authority_id` | string | Stable identifier for the authority domain |
| `namespace_root` | string | Root namespace used for BPv7 EID construction |
| `eid_scheme` | string | BPv7 EID scheme (e.g., `dtn`, `ipn`) |
| `eid_rules` | object | Deterministic formatting rules for EIDs |

Each rover, and each surface asset that originates bundles, runs its own ION bundle protocol agent node, so `source_format` yields that asset's own node ID, a dtn EID with an empty demux (RFC 9171 Sections 4.2.5.1.1 and 5.2).

### B.4.2 EID Rules (planned)

The `eid_rules` object defines how PBS identifiers are transformed into BPv7 EIDs.

Supported placeholders include:

- `{namespace_root}`
- `{scope}`, from the Authority Context configuration or a PBS-AUTH-01 frame (PBS-ADDR-01 Section 3)
- `{destination}`, from the Authority Context configuration: the destination EID is configured at the gateway (PBS-DTN-MAP-01 Sections 6.1 and 8)
- `{source}`, the envelope Source ID (PBS-DTN-MAP-01 Section 8)

Formatting is purely deterministic and string-based.

---

## B.5 Bundle Section

```yaml
bundle:
  default_lifetime_ms: 60000
```

| Field | Type | Description |
|-------|------|-------------|
| `default_lifetime_ms` | integer, ms, 1 to 4294967295000, and a value whose expiration time the BP agent computes without overflow | No-expiry lifetime: the bundle lifetime for an envelope with TTL 0, and the upper bound of the lifetime otherwise (PBS-DTN-MAP-01 Section 6.1.1; PBS-DTN-MAP-02 Section 4). The remaining PBS TTL bounds the lifetime further (PBS-DTN-MAP-01 Section 6.1; [PBS-BPv7-MAPPING-APPENDIX](PBS-BPv7-MAPPING-APPENDIX.md) Section A.6.2). |

An envelope with TTL 0 never expires (PBS-ENV-01 Section 12.1). PBS-DTN-MAP-01 Section 6.1.1 sets its bundle lifetime to the gateway's no-expiry lifetime unless a PBS-DTN-MAP-02 Section 4 finite limit applies. The adapter applies no such limit and uses `default_lifetime_ms`. Section 6.1.1 requires the value, and the bundle protocol agent for which it was selected, to be documented, and recommends the largest value that meets its conditions: 4294967295000 ms for an agent that holds DTN time and expiration time in 64-bit integers. When the bundle's age exceeds the lifetime, the bundle protocol agent deletes the bundle (RFC 9171 Section 5.5) and the envelope with it; that deletion is not TTL expiry (PBS-DTN-MAP-01 Sections 6.1.1 and 7.3).

`pbs_to_bpv7_bundle_mv` defaults `default_lifetime_ms` to 60 000 ms; the worked example run passes 300 000 ms. Neither value is selected for a particular bundle protocol agent.

---

## B.6 Routing

The configuration has no routing section. Contact plans, route computation and convergence-layer selection are DTN and network-service functions (PBS-DTN-MAP-02 Section 8). They are configured in the bundle protocol agent, not in the adapter.

### B.6.1 Planned Routing Section (in development)

Pale Blue Systems is building a routing section. The adapter applies it as configuration of the bundle protocol agent's routing; contact plans, route computation and path selection remain in the agent (PBS-DTN-MAP-02 Section 8). PBS-ROUTE-01 Section 6 permits gateway routing tables.

```yaml
routing:
  default_lifetime_seconds: 86400
  routes:
    - scope: "telemetry"
      next_hop: "dtn://relay/orbiter"
    - scope: "command"
      next_hop: "dtn://relay/direct"
```

| Field | Type | Description |
|-------|------|-------------|
| `default_lifetime_seconds` | integer | Default BPv7 bundle lifetime: the no-expiry lifetime for TTL 0 and the upper bound otherwise; the remaining TTL bounds each lifetime (PBS-DTN-MAP-01 Sections 6.1 and 6.1.1) |
| `routes` | list | Deterministic routing table |

### B.6.2 Route Entries (planned)

Each route entry has the following structure:

```yaml
- scope: string
  next_hop: string
```

| Field | Type | Description |
|-------|------|-------------|
| `scope` | string | PBS scope identifier, from the Authority Context configuration or a PBS-AUTH-01 frame (the envelope header has no scope field) |
| `next_hop` | string | BPv7 EID or agent-specific next-hop identifier |

Routing resolution is table-driven and does not perform runtime arbitration.

---

## B.7 Interfaces

`interfaces` is reserved for the ingress, egress and bundle protocol agent bindings. This revision specifies no keys under it. The worked example has no ingress, egress or agent interface.

Pale Blue Systems is building the interface bindings below (planned, in development).

### B.7.1 Ingress Interface

```yaml
interfaces:
  ingress:
    type: "udp"
    bind_address: "0.0.0.0"
    port: 4556
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Ingress interface type |
| `bind_address` | string | Local bind address |
| `port` | integer | Local port |

### B.7.2 Egress Interface

```yaml
  egress:
    type: "udp"
    destination_address: "127.0.0.1"
    port: 4557
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Egress interface type |
| `destination_address` | string | Destination address |
| `port` | integer | Destination port |

### B.7.3 BPv7 Bundle Agent Interface

```yaml
  bp_agent:
    type: "ion"
    endpoint: "/var/run/ion/bundle.sock"
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Bundle agent type |
| `endpoint` | string | Injection / delivery interface |

This interface defines the integration boundary with the BPv7 bundle agent.

---

## B.8 Validation

A valid configuration has:

- at least one entry under `authority_contexts`;
- `dest`, `src` and `report_to` in every entry;
- as every `src`, a source node ID that Section B.4 accepts;
- an integer `bundle.default_lifetime_ms` from 1 to 4294967295000 for which the bundle protocol agent computes the expiration time without overflow (PBS-DTN-MAP-01 Section 6.1.1).

The worked example enforces the second and third rules when `AuthorityContextMap` is constructed, and the range of the fourth when it selects a lifetime. It connects to no bundle protocol agent and does not check the overflow condition.

For the planned configuration (in development), a valid configuration must satisfy:

- Exactly one Authority Context
- At least one routing entry
- Fully specified ingress, egress, and BP agent interfaces

Validation is performed prior to adapter activation.

---

## B.9 Determinism

With identical configuration, the same authority context name always yields the same three EIDs, and the same envelope, sequence number and clock reading always yield the same lifetime and bundle bytes. When the caller supplies no sequence number, the adapter's counter gives each bundle created in the same millisecond a different one ([PBS-BPv7-MAPPING-APPENDIX](PBS-BPv7-MAPPING-APPENDIX.md) Section A.6.1).

---

## B.10 Summary

This appendix defines the **minimum viable configuration schema** required to operate a PBS Edge Adapter instance.

The planned schema establishes explicit authority binding, deterministic routing configuration for the bundle protocol agent, and unambiguous integration with BPv7 transport infrastructure.
