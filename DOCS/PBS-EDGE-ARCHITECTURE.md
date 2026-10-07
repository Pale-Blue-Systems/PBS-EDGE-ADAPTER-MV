# PBS Edge Adapter — Architecture & Message Flows  
**Document ID:** PBS-EDGE-ARCHITECTURE  
**Status:** Reference Draft  
**Applies To:** PBS-EDGE-ADAPTER-MV  

---

## 1. Purpose

This document describes the reference architecture and message flows of the **PBS Edge Adapter (MV)**: its placement between PBS envelope producers and consumers and a BPv7 bundle protocol agent, its components, and the outbound and inbound flows.

Inside the PBS Edge Adapter, solid outlines mark components that `pbs_edge_adapter_worked_example.py` implements, and dashed outlines mark specified components that it does not implement. Adapter configuration is drawn dashed: the worked example has no configuration loader. PBS producers and consumers, bundle protocol agents and links are external systems.

---

## 2. Placement in a DTN Stack

The adapter sits between PBS-native systems, which emit and receive PBS-ENV-01 v1.3 envelopes, and a bundle protocol agent, which forwards BPv7 bundles. Routing, contact plans and convergence-layer selection remain in the agent (PBS-DTN-MAP-02 Section 8).

Pale Blue Systems is building the planned stages drawn dashed below. The ingress and egress interfaces use UDP, a pipe or local IPC. The deterministic routing stage resolves table-driven next-hop entries and applies them as configuration of the agent's routing; it does not override the agent's route computation (PBS-ROUTE-01 Section 6 permits gateway routing tables).

```mermaid
flowchart LR
  subgraph PBS_Domain["PBS domain (local network, habitat, rover LAN)"]
    P1["PBS producers<br/>(rover systems, habitat services, instruments)"]
    C1["PBS consumers<br/>(operations, autonomy services, logs)"]
    IN["Ingress interface<br/>(UDP / Pipe / Local IPC)"]
    OUT["Egress interface<br/>(UDP / Pipe / Local IPC)"]
  end

  subgraph EDGE["PBS Edge Adapter (MV)"]
    VAL["Envelope validation<br/>(magic, CRC32, priority, length, TTL)"]
    AC["Authority Context map<br/>(dest, src node ID, report-to)"]
    ENC["Encapsulation<br/>(primary block + payload block)"]
    EXT["Extraction<br/>(payload block to envelope)"]
    RT["Deterministic routing<br/>(table-driven next-hop,<br/>applied as agent routing configuration)"]
    IO["Bundle agent interface<br/>(inject / deliver)"]
  end

  subgraph DTN["DTN transport domain"]
    BA["BPv7 bundle protocol agent<br/>(e.g., ION)"]
    NET["Disrupted / delayed links<br/>(relays, ground stations, crosslinks)"]
    BA2["BPv7 bundle protocol agent<br/>(peer)"]
  end

  P1 --> IN --> VAL --> ENC
  AC --> ENC
  ENC --> RT
  RT --> IO
  IO --> BA --> NET --> BA2
  BA2 --> NET --> BA
  BA --> IO
  IO --> EXT --> OUT --> C1

  classDef planned stroke-dasharray: 5 5
  class IN,OUT,EXT,RT,IO planned
```

---

## 3. Functional Component Model

```mermaid
flowchart TB
  subgraph ADAPTER["PBS Edge Adapter (MV) components"]
    VAL["Envelope validation<br/>- PBS_LINK.parse_envelope: magic, CRC32, priority, payload length<br/>- input length = 44 + Size<br/>- TTL expiry (PBS-ENV-01 Section 12.2)"]
    AC["Authority Context map<br/>- named entries<br/>- dest, src node ID, report-to EIDs"]
    RT["Routing Resolver<br/>- resolve next-hop<br/>- select destination EID mapping<br/>- applied as agent routing configuration"]
    subgraph MAP["Mapping Engine"]
    ENC["Encapsulation<br/>- build BPv7 primary + payload blocks<br/>- creation time in DTN ms<br/>- sequence number from the adapter counter<br/>- lifetime bounded by remaining TTL<br/>- no reserved processing control flag<br/>- primary block CRC32C<br/>- payload block = envelope bytes"]
    EXT["Extraction<br/>- restore PBS envelope from bundle<br/>- payload block bytes to envelope, verbatim"]
    end
    IO["Bundle agent interface<br/>- inject bundle<br/>- receive bundle<br/>- deliver to mapping engine"]
    OBS["Observability<br/>- structured events<br/>- counters<br/>- traces (optional)"]
  end

  VAL --> ENC
  AC --> ENC
  AC --> RT
  RT --> MAP
  ENC --> IO
  IO --> EXT
  EXT --> VAL
  VAL --> OBS
  ENC --> OBS
  IO --> OBS

  classDef planned stroke-dasharray: 5 5
  class EXT,RT,IO,OBS planned
```

The Mapping Engine comprises encapsulation and extraction. The Routing Resolver is planned (in development); the adapter applies its next-hop result as configuration of the agent's routing, and route computation remains in the agent (PBS-DTN-MAP-02 Section 8).

| Component | Implementation in the worked example |
|-----------|--------------------------------------|
| Envelope validation | `PBS_LINK.parse_envelope`, the length check and `bundle_lifetime_ms` |
| Authority Context map | `AuthorityContextMap` |
| Encapsulation | `pbs_to_bpv7_bundle_mv`, `build_bpv7_bundle` |
| Extraction, Routing Resolver, bundle agent interface, observability | Not implemented |

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
  A->>A: Check TTL, select lifetime (PBS-DTN-MAP-01 Sections 6.1, 6.1.1)
  A->>A: Build primary block (creation timestamp, CRC32C)
  A->>A: Payload block carries the envelope bytes unmodified
  A->>B: Inject bundle
```

### Outbound Transformation Summary

- The Authority Context map supplies the destination EID, source node ID and report-to EID. No envelope field enters an EID.
- The bundle lifetime is the configured no-expiry lifetime for TTL 0 (PBS-DTN-MAP-01 Section 6.1.1; PBS-DTN-MAP-02 Section 4) and min(no-expiry lifetime, remaining TTL) otherwise (PBS-DTN-MAP-01 Section 6.1).
- The creation timestamp is the DTN time of the clock reading and a sequence number from the adapter's counter or the caller; no envelope field enters it (PBS-DTN-MAP-01 Section 6.1).
- No primary block field or processing control flag carries priority (PBS-DTN-MAP-01 Section 6.3).
- The complete envelope, 44-byte header and payload, becomes the payload block data. TTL and the header CRC32 are not modified (PBS-ENV-01 Sections 12.3 and 15).

### Planned Outbound Flow (in development)

```mermaid
sequenceDiagram
  autonumber
  participant P as PBS Producer
  participant A as PBS Edge Adapter (MV)
  participant AC as Authority Context (configured)
  participant R as Routing Resolver
  participant M as Mapping Engine
  participant B as BPv7 Bundle Agent

  P->>A: Submit PBS Envelope (ingress)
  A->>AC: Bind envelope to active Authority Context
  A->>R: Resolve route + destination mapping
  R-->>A: Route decision (next-hop as agent routing configuration + EID inputs)
  A->>M: Build BPv7 bundle structure
  M-->>A: BPv7 bundle (primary + payload)
  A->>B: Inject BPv7 bundle
  B-->>A: Accepted for forwarding
```

Planned outbound transformation summary:

- PBS identifiers are interpreted under the active Authority Context.
- BPv7 Destination and Source EIDs are constructed deterministically.
- PBS envelope bytes (44-byte header and payload) become the BPv7 Payload Block bytes.

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

### Planned Inbound Flow (in development)

```mermaid
sequenceDiagram
  autonumber
  participant B as BPv7 Bundle Agent
  participant A as PBS Edge Adapter (MV)
  participant AC as Authority Context (configured)
  participant M as Mapping Engine
  participant C as PBS Consumer

  B->>A: Deliver received BPv7 bundle
  A->>AC: Interpret EIDs under active Authority Context
  A->>M: Restore PBS envelope verbatim from the payload block
  M-->>A: PBS Envelope (header + payload)
  A->>C: Deliver PBS Envelope (egress)
```

Planned inbound transformation summary:

- BPv7 Source/Destination EIDs are parsed relative to the active Authority Context.
- Payload Block bytes become the PBS envelope bytes (44-byte header and payload), unmodified.
- The PBS envelope is restored verbatim (PBS-DTN-MAP-01 Section 7.2) and delivered to local consumers.

---

## 6. Configuration as an Architectural Boundary

Configuration defines the Authority Context map, the default bundle lifetime, and (in a later revision) the interface bindings. The `interfaces` key is reserved (Appendix B, Section B.7). [PBS-EDGE-CONFIG-SCHEMA](PBS-EDGE-CONFIG-SCHEMA.md) specifies the configuration. The worked example takes the equivalent values as Python arguments.

The planned configuration (in development) also defines:

- routing resolution tables for deterministic next-hop selection, applied as configuration of the bundle protocol agent's routing (PBS-DTN-MAP-02 Section 8; PBS-ROUTE-01 Section 6),
- ingress/egress interface endpoints.

```mermaid
flowchart LR
  CONF["Adapter configuration<br/>- authority_contexts<br/>- bundle.default_lifetime_ms<br/>- interfaces (reserved)<br/>- EID scheme + rules (planned)<br/>- routing table (planned)"]
  AC["Authority Context map"]
  RT["Routing Resolver"]
  ENC["Encapsulation"]
  IO["Bundle agent interface"]

  CONF --> AC
  CONF --> RT
  CONF --> ENC
  CONF --> IO

  classDef planned stroke-dasharray: 5 5
  class CONF,RT,IO planned
```

---

## 7. Integration Boundary with the Bundle Protocol Agent

The adapter and the bundle protocol agent interact only through bundle injection and delivery. The agent provides forwarding, storage, routing and other DTN services.

Pale Blue Systems is building the routing stage of Section 2, which adds one interaction: the adapter supplies its routing table to the agent as routing configuration, and the agent's route computation is unchanged (PBS-DTN-MAP-02 Section 8).

```mermaid
flowchart LR
  A["PBS Edge Adapter (MV)<br/>validation + encapsulation (implemented)<br/>extraction (not implemented)<br/>mapping + routing configuration (planned)"]
  I["Bundle injection / delivery boundary"]
  B["BPv7 bundle protocol agent<br/>forwarding + storage + routing + DTN services"]

  A <--> I <--> B

  classDef planned stroke-dasharray: 5 5
  class I planned
```

---

## 8. Architecture Outputs

- PBS to BPv7 encapsulation per [PBS-BPv7-MAPPING-APPENDIX](PBS-BPv7-MAPPING-APPENDIX.md), implemented and tested in the worked example.
- BPv7 to PBS extraction per PBS-DTN-MAP-01 Section 7, specified and not implemented.
- Planned (in development): deterministic BPv7 → PBS restoration, verbatim, aligned with the Authority Context model.
- A placement model for DTN interoperability review.
