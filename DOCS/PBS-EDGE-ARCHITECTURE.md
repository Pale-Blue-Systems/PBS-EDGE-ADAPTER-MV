# PBS Edge Adapter — Architecture & Message Flows  
**Document ID:** PBS-EDGE-ARCHITECTURE  
**Status:** Reference Draft  
**Applies To:** PBS-EDGE-ADAPTER-MV  

---

## 1. Purpose

This document describes the reference architecture and message flows for the **PBS Edge Adapter (MV)**, including its placement between PBS envelope producers/consumers and a **BPv7 bundle agent**.

---

## 2. Reference Placement in a DTN Stack

The PBS Edge Adapter occupies a boundary position between:

- PBS-native systems that emit or receive PBS envelopes, and
- DTN systems that forward data using BPv7.

```mermaid
flowchart LR
  subgraph PBS_Domain["PBS Domain (Local Network / Habitat / Rover LAN)"]
    P1["PBS Producer(s)\n(rover systems, habitat services, instruments)"]
    C1["PBS Consumer(s)\n(ops apps, autonomy services, logs)"]
    IN["Ingress Interface\n(UDP / Pipe / Local IPC)"]
    OUT["Egress Interface\n(UDP / Pipe / Local IPC)"]
  end

  subgraph EDGE["PBS Edge Adapter (MV)"]
    AC["Authority Context\n(binding + namespace root)"]
    ENV["PBS Envelope Handler\n(parse + validate)"]
    MAP["Mapping Engine\n(PBS ↔ BPv7)"]
    RT["Deterministic Routing\n(table-driven next-hop)"]
    IO["Bundle I/O Boundary\n(inject / receive)"]
  end

  subgraph DTN["DTN Transport Domain"]
    BA["BPv7 Bundle Agent\n(e.g., ION)"]
    NET["Disrupted / Delayed Links\n(relays, ground stations, crosslinks)"]
    BA2["BPv7 Bundle Agent\n(peer)"]
  end

  P1 --> IN --> ENV
  ENV --> AC
  ENV --> MAP
  MAP --> RT
  RT --> IO
  IO --> BA
  BA --> NET --> BA2

  BA2 --> NET --> BA
  BA --> IO --> MAP --> OUT --> C1
```

---

## 3. Functional Component Model

The MV architecture is composed of a small set of deterministic components.

```mermaid
flowchart TB
  subgraph ADAPTER["PBS Edge Adapter (MV) Components"]
    AC["Authority Context\n- authority identifier\n- namespace root\n- EID construction rules"]
    ENV["PBS Envelope Handler\n- parse\n- validate\n- normalize envelope model"]
    RT["Routing Resolver\n- resolve next-hop\n- select destination EID mapping"]
    MAP["Mapping Engine\n- build BPv7 primary + payload blocks\n- reconstruct PBS envelope from bundle"]
    IO["BP Agent Interface\n- inject bundle\n- receive bundle\n- deliver to mapping engine"]
    OBS["Observability\n- structured events\n- counters\n- traces (optional)"]
  end

  AC --> ENV
  AC --> RT
  ENV --> MAP
  RT --> MAP
  MAP --> IO
  ENV --> OBS
  MAP --> OBS
  IO --> OBS
```

---

## 4. Message Flow — Outbound (PBS → BPv7)

This flow begins when a PBS producer submits an envelope to the adapter ingress.

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
  R-->>A: Route decision (next-hop + EID inputs)
  A->>M: Build BPv7 bundle structure
  M-->>A: BPv7 bundle (primary + payload)
  A->>B: Inject BPv7 bundle
  B-->>A: Accepted for forwarding
```

### Outbound Transformation Summary

- PBS identifiers are interpreted under the active Authority Context.
- BPv7 Destination and Source EIDs are constructed deterministically.
- PBS payload bytes become the BPv7 Payload Block bytes.

---

## 5. Message Flow — Inbound (BPv7 → PBS)

This flow begins when a BPv7 bundle is delivered from the bundle agent to the adapter.

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
  A->>M: Reconstruct PBS envelope model
  M-->>A: PBS Envelope (header + payload)
  A->>C: Deliver PBS Envelope (egress)
```

### Inbound Transformation Summary

- BPv7 Source/Destination EIDs are parsed relative to the active Authority Context.
- Payload Block bytes become the PBS payload bytes.
- A PBS envelope is reconstructed and delivered to local consumers.

---

## 6. Configuration as an Architectural Boundary

Configuration defines:

- the active Authority Context,
- the EID construction rules used by the mapping engine,
- routing resolution tables for deterministic next-hop selection,
- ingress/egress interface endpoints.

```mermaid
flowchart LR
  CONF["Adapter Configuration\n- authority context\n- EID scheme + rules\n- routing table\n- defaults (lifetime, etc.)"]
  AC["Authority Context"]
  RT["Routing Resolver"]
  MAP["Mapping Engine"]
  IO["BP Agent Interface"]

  CONF --> AC
  CONF --> RT
  CONF --> MAP
  CONF --> IO
```

---

## 7. Integration Boundary with the BPv7 Bundle Agent

The adapter and the bundle agent interact through a clear injection/delivery boundary:

```mermaid
flowchart LR
  A["PBS Edge Adapter (MV)\nMapping + Routing"]
  I["Bundle Injection / Delivery Boundary"]
  B["BPv7 Bundle Agent\nForwarding + Storage + DTN Services"]

  A <--> I <--> B
```

---

## 8. Architecture Outputs

The reference architecture produces:

- Deterministic PBS → BPv7 encapsulation aligned with the mapping appendix
- Deterministic BPv7 → PBS reconstruction aligned with the Authority Context model
- A clear placement model suitable for DTN interoperability review

---
