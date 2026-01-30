# Why Now — Context for the PBS Edge Adapter Reference

The PBS Edge Adapter reference exists to address a foreseeable architectural challenge in future space communication environments: **explicit handling of authority boundaries at the network edge**.

This work does not respond to a present operational failure.  
It anticipates a future in which multiple independent authorities operate concurrently over shared transport infrastructure.

---

## The Future Authority Landscape

Future off-Earth operations are expected to include:

- multiple national space agencies,
- commercial operators and service providers,
- private missions and tourism activities,
- shared relays, shared spectrum, and shared routing infrastructure.

In such an environment, authority is **inherently distributed**, even when coordination exists.

---

## The Architectural Risk

When authority boundaries are left implicit:

- namespace collisions emerge,
- routing semantics become ambiguous,
- governance concerns bleed into transport layers,
- corrective measures become difficult once infrastructure is deployed.

Historically, these issues become architectural debt rather than design choices.

---

## Why the Edge Is the Right Place

The network edge provides a location where:

- authority interpretation can be made explicit,
- transport protocols can remain unchanged,
- deterministic behavior can be enforced,
- future evolution remains possible.

Addressing authority separation at the edge minimizes disruption while preserving interoperability.

---

## Purpose of Publishing Now

This repository exists to:

1. Make future authority-related risks explicit and inspectable.
2. Provide a minimal, deterministic reference for discussion and review.
3. Enable early collaboration before large-scale infrastructure hardens.

---

## Summary

The PBS Edge Adapter reference is published now because future space communication environments are expected to be **multi-authority by default**.

Early, minimal exploration of authority-aware edge behavior helps ensure that future systems remain interoperable without becoming brittle.
