# PBS Edge Adapter — Architecture & Message Flows  
**Document ID:** PBS-EDGE-ARCHITECTURE  
**Status:** Reference Draft  
**Applies To:** PBS-EDGE-ADAPTER-MV  

---

## 1. Purpose

This document describes the reference architecture and message flows of the **PBS Edge Adapter (MV)**: its placement between PBS envelope producers and consumers and a BPv7 bundle protocol agent, its components, and the outbound and inbound flows.

In the diagrams, solid outlines mark components that `pbs_edge_adapter_worked_example.py` implements. Dashed outlines mark specified components that are not implemented.

---

## 2. Placement in a DTN Stack

The adapter sits between PBS-native systems, which emit and receive PBS-ENV-01 v1.3 envelopes, and a bundle protocol agent, which forwards BPv7 bundles. Routing, contact plans and convergence-layer selection remain in the agent (PBS-DTN-MAP-02 Section 8).

```mermaid
flowchart LR
  subgraph PBS_Domain["PBS domain (local network, habitat, rover LAN)"]
    P1["PBS producers<br/>(rover systems, habitat services, instruments)"]
    C1["PBS consumers<br/>(operations, autonomy services, logs)"]
    IN["Ingress interface"]
    OUT["Egress interface"]
  end

  subgraph EDGE["PBS Edge Adapter (MV)"]
    VAL["Envelope validation<br/>(magic, CRC32, priority, length, TTL)"]
    AC["Authority Context map<br/>(dest, src node ID, report-to)"]
    ENC["Encapsulation<br/>(primary block + payload block)"]
    EXT["Extraction<br/>(payload block to envelope)"]
    IO["Bundle agent interface<br/>(inject / deliver)"]
  end

  subgraph DTN["DTN transport domain"]
    BA["BPv7 bundle protocol agent<br/>(e.g., ION)"]
    NET["Disrupted / delayed links<br/>(relays, ground stations, crosslinks)"]
    BA2["BPv7 bundle protocol agent<br/>(peer)"]
  end

  P1 --> IN --> VAL --> ENC
  AC --> ENC
  ENC --> IO --> BA --> NET --> BA2
  BA2 --> NET
  BA --> IO
  IO --> EXT --> OUT --> C1

  classDef planned stroke-dasharray: 5 5
  class IN,OUT,EXT,IO planned
```

---

## 3. Functional Component Model

```mermaid
flowchart TB
  subgraph ADAPTER["PBS Edge Adapter (MV) components"]
    VAL["Envelope validation<br/>- PBS_LINK.parse_envelope: magic, CRC32, priority, payload length<br/>- input length = 44 + Size<br/>- TTL expiry (PBS-ENV-01 Section 12.2)"]
    AC["Authority Context map<br/>- named entries<br/>- dest, src node ID, report-to EIDs"]
    ENC["Encapsulation<br/>- creation time in DTN ms<br/>- lifetime bounded by remaining TTL<br/>- primary block CRC32C<br/>- payload block = envelope bytes"]
    EXT["Extraction<br/>- payload block bytes to envelope, verbatim"]
    IO["Bundle agent interface<br/>- inject bundle<br/>- receive bundle"]
    OBS["Observability<br/>- events and counters"]
  end

  VAL --> ENC
  AC --> ENC
  ENC --> IO
  IO --> EXT
  EXT --> VAL
  VAL --> OBS
  ENC --> OBS
  IO --> OBS

  classDef planned stroke-dasharray: 5 5
  class EXT,IO,OBS planned
```

| Component | Implementation in the worked example |
|-----------|--------------------------------------|
| Envelope validation | `PBS_LINK.parse_envelope`, the length check and `bundle_lifetime_ms` |
| Authority Context map | `AuthorityContextMap` |
| Encapsulation | `pbs_to_bpv7_bundle_mv`, `build_bpv7_bundle` |
| Extraction, bundle agent interface, observability | Not implemented |

---

## 4. Message Flow — Outbound (PBS to BPv7)

The flow begins when a PBS producer submits an envelope to the adapter ingress. Steps 2 to 7 are implemented in the worked example.

```mermaid
sequenceDiagram
  autonumber
  participant P as PBS producer
  participant A as PBS Edge Adapter (MV)
  participant AC as Authority Context map
  participant B as BPv7 bundle protocol agent

  P->>A: PBS envelope (ingress)
  A->>A: Validate magic, CRC32, priority, length
  A->>AC: Resolve the named authority context
  AC-->>A: dest, src node ID, report-to
  A->>A: Check TTL, select lifetime (PBS-DTN-MAP-02 Section 4)
  A->>A: Build primary block (DTN ms creation time, CRC32C)
  A->>A: Payload block carries the envelope bytes unmodified
  A->>B: Inject bundle
```

### Outbound Transformation Summary

- The Authority Context map supplies the destination EID, source node ID and report-to EID. No envelope field enters an EID.
- The bundle lifetime is the configured default for TTL 0 and min(default, remaining TTL) otherwise.
- The complete envelope, 44-byte header and payload, becomes the payload block data.

---

## 5. Message Flow — Inbound (BPv7 to PBS)

The flow begins when the bundle protocol agent delivers a bundle to the adapter. The worked example does not implement it.

```mermaid
sequenceDiagram
  autonumber
  participant B as BPv7 bundle protocol agent
  participant A as PBS Edge Adapter (MV)
  participant C as PBS consumer

  B->>A: Deliver bundle (validated by the agent)
  A->>A: Extract payload block bytes as the envelope
  A->>A: Validate magic, CRC32, priority, TTL (PBS-ENV-01 Section 14)
  A->>C: Deliver envelope unmodified (egress)
```

### Inbound Transformation Summary

- The bundle protocol agent validates the bundle before PBS processing (PBS-DTN-MAP-01 Section 7.1).
- The payload block bytes are the original envelope, extracted verbatim (PBS-DTN-MAP-01 Section 7.2).
- No envelope field is derived from bundle EIDs.

---

## 6. Configuration as an Architectural Boundary

Configuration defines the Authority Context map, the default bundle lifetime, and (in a later revision) the interface bindings. [PBS-EDGE-CONFIG-SCHEMA](PBS-EDGE-CONFIG-SCHEMA.md) specifies it.

```mermaid
flowchart LR
  CONF["Adapter configuration<br/>- authority_contexts<br/>- bundle.default_lifetime_ms<br/>- interfaces (reserved)"]
  AC["Authority Context map"]
  ENC["Encapsulation"]
  IO["Bundle agent interface"]

  CONF --> AC
  CONF --> ENC
  CONF --> IO

  classDef planned stroke-dasharray: 5 5
  class IO planned
```

---

## 7. Integration Boundary with the Bundle Protocol Agent

The adapter and the bundle protocol agent interact only through bundle injection and delivery. The agent provides forwarding, storage, routing and other DTN services.

```mermaid
flowchart LR
  A["PBS Edge Adapter (MV)<br/>validation + encapsulation + extraction"]
  I["Bundle injection / delivery boundary"]
  B["BPv7 bundle protocol agent<br/>forwarding + storage + routing"]

  A <--> I <--> B
```

---

## 8. Architecture Outputs

- PBS to BPv7 encapsulation per [PBS-BPv7-MAPPING-APPENDIX](PBS-BPv7-MAPPING-APPENDIX.md), implemented and tested in the worked example.
- BPv7 to PBS extraction per PBS-DTN-MAP-01 Section 7, specified and not implemented.
- A placement model for DTN interoperability review.
