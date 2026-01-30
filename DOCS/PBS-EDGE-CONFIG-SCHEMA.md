# Appendix B — PBS Edge Adapter Configuration Schema  
**Document ID:** PBS-EDGE-CONFIG-SCHEMA  
**Status:** Reference Draft  
**Applies To:** PBS-EDGE-ADAPTER-MV  

---

## B.1 Purpose

This appendix defines the **authoritative configuration schema** for the PBS Edge Adapter (Minimum Viable reference).

The schema specifies how an adapter instance is bound to:
- a single Authority Context,
- deterministic routing rules,
- BPv7 endpoint construction parameters, and
- ingress / egress interfaces.

All configuration elements are explicit, local, and inspectable.

---

## B.2 Configuration Model Overview

Configuration is provided as a structured document (e.g., YAML or JSON) and is loaded at adapter initialization time.

The configuration model is composed of four top-level sections:

1. Adapter Identity  
2. Authority Context  
3. Routing Configuration  
4. Interface Bindings  

Each section is described below.

---

## B.3 Top-Level Structure

```yaml
adapter:
  id: string
  version: string

authority_context:
  authority_id: string
  namespace_root: string
  eid_scheme: string
  eid_rules: object

routing:
  default_lifetime_seconds: integer
  routes: list

interfaces:
  ingress: object
  egress: object
  bp_agent: object
```

---

## B.4 Adapter Section

### B.4.1 Adapter Identity

```yaml
adapter:
  id: "pbs-edge-adapter-alpha"
  version: "0.1"
```

| Field | Type | Description |
|-----|-----|-------------|
| `id` | string | Unique identifier for the adapter instance |
| `version` | string | Adapter configuration version label |

The adapter identity is used for observability and diagnostics.

---

## B.5 Authority Context Section

### B.5.1 Authority Context Definition

```yaml
authority_context:
  authority_id: "pbsf-lunar-demo"
  namespace_root: "dtn://pbsf/lunar"
  eid_scheme: "dtn"
  eid_rules:
    destination_format: "{namespace_root}/{scope}/{destination}"
    source_format: "{namespace_root}/{source}"
```

| Field | Type | Description |
|-----|-----|-------------|
| `authority_id` | string | Stable identifier for the authority domain |
| `namespace_root` | string | Root namespace used for BPv7 EID construction |
| `eid_scheme` | string | BPv7 EID scheme (e.g., `dtn`, `ipn`) |
| `eid_rules` | object | Deterministic formatting rules for EIDs |

---

### B.5.2 EID Rules

The `eid_rules` object defines how PBS identifiers are transformed into BPv7 EIDs.

Supported placeholders include:

- `{namespace_root}`
- `{scope}`
- `{destination}`
- `{source}`

Formatting is purely deterministic and string-based.

---

## B.6 Routing Section

### B.6.1 Default Routing Parameters

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
|-----|-----|-------------|
| `default_lifetime_seconds` | integer | Default BPv7 bundle lifetime |
| `routes` | list | Deterministic routing table |

---

### B.6.2 Route Entries

Each route entry has the following structure:

```yaml
- scope: string
  next_hop: string
```

| Field | Type | Description |
|-----|-----|-------------|
| `scope` | string | PBS scope identifier |
| `next_hop` | string | BPv7 EID or agent-specific next-hop identifier |

Routing resolution is table-driven and does not perform runtime arbitration.

---

## B.7 Interface Bindings

### B.7.1 Ingress Interface

```yaml
interfaces:
  ingress:
    type: "udp"
    bind_address: "0.0.0.0"
    port: 4556
```

| Field | Type | Description |
|-----|-----|-------------|
| `type` | string | Ingress interface type |
| `bind_address` | string | Local bind address |
| `port` | integer | Local port |

---

### B.7.2 Egress Interface

```yaml
  egress:
    type: "udp"
    destination_address: "127.0.0.1"
    port: 4557
```

| Field | Type | Description |
|-----|-----|-------------|
| `type` | string | Egress interface type |
| `destination_address` | string | Destination address |
| `port` | integer | Destination port |

---

### B.7.3 BPv7 Bundle Agent Interface

```yaml
  bp_agent:
    type: "ion"
    endpoint: "/var/run/ion/bundle.sock"
```

| Field | Type | Description |
|-----|-----|-------------|
| `type` | string | Bundle agent type |
| `endpoint` | string | Injection / delivery interface |

This interface defines the integration boundary with the BPv7 bundle agent.

---

## B.8 Configuration Determinism

Given identical configuration and identical PBS inputs:

- EID construction is identical
- Routing resolution is identical
- Bundle lifetime selection is identical

This supports reproducible testing and auditability.

---

## B.9 Validation Expectations

A valid configuration must satisfy:

- Exactly one Authority Context
- At least one routing entry
- Fully specified ingress, egress, and BP agent interfaces

Validation is performed prior to adapter activation.

---

## B.10 Summary

This appendix defines the **minimum viable configuration schema** required to operate a PBS Edge Adapter instance.

The schema establishes explicit authority binding, deterministic routing, and unambiguous integration with BPv7 transport infrastructure.
