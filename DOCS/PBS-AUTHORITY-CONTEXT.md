# Authority Context Specification  
**Document ID:** PBS-AUTHORITY-CONTEXT  
**Status:** Reference Draft  
**Applies To:** PBS-EDGE-ADAPTER-MV  
**Steward:** Pale Blue Systems Foundation  

---

## 1. Purpose

This document defines the **Authority Context** used by the Pale Blue Systems (PBS) Edge Adapter.

The Authority Context establishes the **administrative and routing namespace** within which PBS envelopes are interpreted and mapped into Bundle Protocol Version 7 (BPv7) transport environments.

This specification provides a deterministic and inspectable mechanism for namespace separation across shared transport infrastructure.

---

## 2. Conceptual Overview

An **Authority Context** represents a single, coherent authority domain under which:

- PBS identifiers are interpreted
- Routing namespaces are resolved
- BPv7 Endpoint Identifiers (EIDs) are constructed

Each PBS Edge Adapter instance operates under **exactly one active Authority Context** at any given time.

---

## 3. Motivation

Distributed communication environments frequently involve:

- Multiple organizations
- Multiple missions or programs
- Shared physical or logical transport infrastructure

The Authority Context provides a means to ensure that PBS envelopes originating from different authorities remain **logically distinct**, even when they traverse common DTN links.

---

## 4. Authority Context Definition

An Authority Context consists of the following components:

| Component | Description |
|---------|-------------|
| Authority Identifier | A unique identifier representing the administrative authority |
| Namespace Root | The root namespace used when constructing BPv7 EIDs |
| Routing Scope Rules | Deterministic rules for interpreting PBS scope identifiers |
| Adapter Configuration Binding | Static binding between the adapter instance and the authority |

All components are defined through explicit configuration.

---

## 5. Authority Identifier

The **Authority Identifier** uniquely names the authority domain.

Characteristics:

- Stable across time
- Unique within the deployment environment
- Opaque to the adapter beyond equality comparison

The Authority Identifier is not transmitted within the PBS payload.

---

## 6. Namespace Root

The **Namespace Root** defines the top-level namespace used when constructing BPv7 Endpoint Identifiers.

Examples include, but are not limited to:

- A domain-style namespace
- A numeric namespace
- A structured hierarchical identifier

The Namespace Root is combined with PBS routing identifiers to form complete BPv7 EIDs.

---

## 7. Binding and Configuration

### 7.1 Adapter Binding

Each PBS Edge Adapter instance is bound to one Authority Context via configuration at initialization time.

The binding is static for the lifetime of the adapter instance.

---

### 7.2 Configuration Inputs

Authority Context configuration includes:

- Authority Identifier
- Namespace Root
- EID construction rules
- Default routing parameters

Configuration is explicit and local to the adapter instance.

---

## 8. Use in PBS → BPv7 Mapping

When processing a PBS envelope, the adapter uses the active Authority Context to:

1. Interpret PBS source and destination identifiers
2. Resolve scope identifiers within the authority namespace
3. Construct BPv7 Source and Destination EIDs
4. Ensure deterministic namespace separation

No cross-authority inference is performed.

---

## 9. Use in BPv7 → PBS Mapping

When receiving a BPv7 bundle, the adapter:

1. Parses the Source and Destination EIDs
2. Interprets them relative to the active Authority Context
3. Reconstructs PBS source and destination identifiers
4. Emits a PBS envelope within the same authority domain

Bundles whose EIDs do not align with the active Authority Context are not reconstructed.

---

## 10. Deterministic Behavior

Authority Context handling is deterministic:

- Identical inputs and configuration produce identical results
- No dynamic authority selection is performed
- No runtime arbitration between authorities occurs

Determinism ensures predictable behavior and simplifies interoperability testing.

---

## 11. Authority Isolation

Authority Contexts provide **logical isolation** through:

- Namespace separation
- Deterministic routing resolution
- Explicit configuration boundaries

Isolation is achieved without requiring separate transport infrastructure.

---

## 12. Applicability

The Authority Context model applies to environments including:

- Multi-mission space systems
- Joint civil, commercial, and scientific networks
- Federated DTN deployments
- Intermittently connected and delay-tolerant networks

---

## 13. Extensibility

This specification defines the **minimum viable Authority Context**.

Future extensions may introduce:

- Multi-context adapters
- Dynamic context selection
- Federation-aware context resolution

Such extensions do not alter the correctness of the model defined herein.

---

## 14. Summary

The Authority Context establishes a clear and deterministic foundation for authority-aware routing at the network edge.

By explicitly binding PBS Edge Adapters to a single authority namespace, the model enables safe coexistence of multiple authorities over shared BPv7 transport environments.
