# PBS Edge Adapter — Minimum Viable Reference  
**Document ID:** PBS-EDGE-ADAPTER-MV  
**Status:** Reference Draft  
**Steward:** Pale Blue Systems Foundation  

---

## 1. Purpose

This document defines the **Minimum Viable (MV) reference design** for the **PBS Edge Adapter**.

The PBS Edge Adapter is a boundary component that enables **Pale Blue Systems (PBS) envelopes** to be mapped into **Bundle Protocol Version 7 (BPv7)** transport environments in a deterministic and authority-aware manner.

The intent of this document is to provide a clear, inspectable description of edge adapter behavior suitable for technical review, interoperability analysis, and standards discussion.

---

## 2. Role of the Edge Adapter

Within a Delay/Disruption-Tolerant Networking (DTN) architecture, the PBS Edge Adapter operates at the **protocol boundary** between:

- Systems that generate or consume **PBS envelopes**, and  
- Systems that provide **BPv7 bundle transport**.

The adapter performs **translation and binding**, not transport itself. It relies on existing BPv7 bundle agents to provide forwarding, storage, and custody services.

---

## 3. Functional Overview

At a high level, the PBS Edge Adapter performs the following functions:

1. Accepts PBS envelopes from a local ingress interface  
2. Binds each envelope to a configured **Authority Context**  
3. Maps PBS routing and scope identifiers to BPv7 endpoint identifiers  
4. Encapsulates the PBS payload as an opaque BPv7 payload block  
5. Emits a BPv7 bundle suitable for injection into a bundle agent  

The reverse process applies for inbound bundles.

---

## 4. Authority Context

### 4.1 Definition

An **Authority Context** represents the administrative and routing namespace within which the edge adapter operates.

Each adapter instance is configured with exactly one active Authority Context at a time.

### 4.2 Usage

The Authority Context is used to:

- Interpret PBS scope and routing identifiers  
- Construct BPv7 Endpoint Identifiers (EIDs)  
- Ensure deterministic namespace separation across shared transport infrastructure  

Authority Context handling is explicit and deterministic.

---

## 5. PBS Envelope Handling

### 5.1 Envelope Acceptance

The adapter accepts PBS envelopes that conform to the PBS envelope specification in effect at the time of deployment.

Each envelope is processed as a discrete, atomic unit.

### 5.2 Payload Treatment

The PBS payload is treated as **opaque data** by the adapter.

The adapter does not inspect, modify, or interpret payload contents.

---

## 6. PBS → BPv7 Mapping

### 6.1 Endpoint Identification

PBS routing identifiers are mapped to BPv7 Endpoint Identifiers (EIDs) using a deterministic mapping rule derived from:

- Authority Context  
- PBS destination scope  
- Local routing configuration  

The resulting EID uniquely identifies the BPv7 destination within the active authority namespace.

### 6.2 Bundle Construction

For each PBS envelope, the adapter constructs a BPv7 bundle consisting of:

- A **Primary Block** populated with:
  - Destination EID
  - Source EID
  - Creation timestamp
  - Lifetime (from configuration defaults)
- A **Payload Block** containing the PBS payload bytes verbatim

No additional extension blocks are required for the minimum viable reference.

---

## 7. BPv7 → PBS Mapping

When receiving BPv7 bundles from a bundle agent, the adapter:

1. Extracts the Payload Block  
2. Reconstructs a PBS envelope using:
   - The active Authority Context
   - Source and destination information derived from BPv7 EIDs  
3. Delivers the reconstructed PBS envelope to the local egress interface  

This process preserves payload integrity and routing identity.

---

## 8. Deterministic Behavior

The PBS Edge Adapter operates deterministically:

- Given the same input envelope and configuration, the resulting BPv7 bundle is identical
- No policy arbitration, trust scoring, or dynamic decision-making is performed
- Routing resolution is table-driven and explicit

Determinism supports debugging, auditability, and interoperability testing.

---

## 9. Transport Integration

The adapter is designed to integrate with existing BPv7 bundle agents through well-defined injection and reception interfaces.

The reference design assumes the presence of a conformant BPv7 agent capable of:

- Accepting bundles for forwarding  
- Delivering received bundles to the adapter  

The adapter itself does not implement bundle forwarding or custody mechanisms.

---

## 10. Reference Logic

Minimal reference logic is provided to illustrate:

- PBS envelope parsing  
- Authority Context binding  
- BPv7 bundle structure construction  

This logic is expressed in a high-level language for clarity and accessibility and is intended to support verification of the mapping rules described in this document.

---

## 11. Applicability

The PBS Edge Adapter reference design applies to environments including:

- Space and lunar communication systems  
- Planetary surface networks  
- Disrupted or intermittently connected terrestrial networks  
- Multi-authority DTN deployments  

The design is transport-agnostic beyond its alignment with BPv7.

---

## 12. Status

This document defines a **minimum viable reference** for the PBS Edge Adapter.

It is expected to evolve as PBS specifications mature and as feedback is incorporated from technical review and interoperability exercises.
