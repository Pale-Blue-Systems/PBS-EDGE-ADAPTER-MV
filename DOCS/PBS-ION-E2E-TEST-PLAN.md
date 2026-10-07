# PBS-ION-E2E-TEST-PLAN: Test Plan, Procedures and Report Format for the ION End-to-End Demonstration

**Item under test:** `pbs_ion_demo` (PBS gateway functions, link emulator, BPv7 wire decoder) with NASA/JPL ION `ion-open-source-4.2.0`, commit `568df887cb9f18aa8ec013b1a566d83215e499ae`.
**Test code:** `TESTS/test_ion_demo_units.py` (UT-01 to UT-25) and `TESTS/ion/test_ion_end_to_end.py` (IT-01 to IT-13).
**Related documents:** [PBS-ION-E2E-DEMO.md](PBS-ION-E2E-DEMO.md) (demonstration), [PBS-ION-MAPPING-PROFILE.md](PBS-ION-MAPPING-PROFILE.md) (mapping profile).

This document combines a software test plan, the test procedures and the test report format. Its content follows the NASA Software Engineering Handbook (NASA-HDBK-2203) topics 5.10 *Software Test Plan*, 5.14 *Software Test Procedures* and 5.11 *Software Test Report* [N4]. Each test case lists its requirements and verification method, and the matrix in Section 5 traces both ways between requirements and test cases, as NPR 7150.2D SWE-052 requires for requirements and tests [N1]. The test code is the executable procedure. Each test function's docstring repeats the requirement, method, procedure and pass criteria given here. Pale Blue Systems is not a NASA project and claims no compliance with NPR 7150.2D. The NASA documents are cited as the model the plan follows.

---

## 1. Scope and objectives

The tests verify that PBS-ENV-01 envelopes cross a two-node ION 4.2.0 network over an emulated Earth–Moon link as PBS-DTN-MAP-01 v1.5 and PBS-DTN-MAP-02 v1.5 require. They also verify that the bundles ION puts on the link conform to RFC 9171 where the demonstration depends on it. The objectives are:

1. Delivery: each envelope is carried in one bundle and delivered byte-identical, with its header CRC32 intact.
2. Lifetime: the bundle expires no later than the envelope, and ION deletes a bundle whose lifetime ends before it can be forwarded.
3. Priority: ION's class of service follows the PBS-DTN-MAP-01 Section 6.3 table, and no reserved bundle flag carries priority.
4. Disruption: a bundle is stored while no contact is planned and forwarded when the contact opens.
5. Interoperability: ION accepts bundles encoded by the worked example (`pbs_edge_adapter_worked_example.py`) and discards one with a corrupted CRC.
6. Configuration and isolation: the results apply to the pinned ION release, and a test run leaves no ION process or shared-memory segment behind.

Out of scope: BPSec, LTP and other convergence layers, custody transfer, multi-hop routing, PBS-native routing and sequence tracking, timing performance, and load. Section 8 lists these.

## 2. Test items and configuration

| Item | Identification | Configuration control |
|------|----------------|------------------------|
| ION | `ion-open-source-4.2.0`, commit `568df887cb9f18aa8ec013b1a566d83215e499ae` | `scripts/ion-release.env`, `pbs_ion_demo/ion_release.py`; `scripts/build_ion.sh` refuses any other commit; IT-11 checks the running version (SWE-187 [N1]) |
| PBS_LINK | `pbs-link` 0.1.4, commit `c377e0b966c626ebb7dbeab12be884c3f1cebf25` | `requirements-ion-demo.txt` |
| cbor2, pytest | 6.1.5, 9.1.1 | `requirements-ion-demo.txt` |
| `pbs_ion_demo`, tests | this repository, at the commit under test | git |

## 3. Test environment

- **Host:** Linux x86-64 (LP64), Python 3.10 or later, C toolchain with autoconf, automake and libtool to build ION. CI uses GitHub-hosted `ubuntu-latest` runners.
- **Network under test:** two ION nodes on one host. Node 1 (`ipn:1`) is the lunar surface gateway and node 2 (`ipn:2`) the Earth operations gateway. Each node runs in its own directory with its own shared-memory key and SDR, with `ION_NODE_LIST_DIR` set, as in ION's own multi-node tests. Both use the UDP convergence layer. Each node sends on `ipn:N.1` and receives on `ipn:N.2`.
- **Link:** `pbs_ion_demo.link_emulator` relays each UDP datagram after a one-way light time (OWLT) of 384 400 km / 299 792 458 m/s = 1.2822 s. This is the Moon's mean distance [R12] at the exact speed of light [R13]. The emulator records the bytes and host clock times of each datagram. ION's contact plan has a range of ⌈OWLT⌉ = 2 s and a rate of 125 000 bytes/s in each direction.
- **Clock:** one host clock serves ION, the gateways and the emulator.

## 4. Requirements under test

| ID | Requirement | Source |
|----|-------------|--------|
| R-01 | Each envelope maps to exactly one bundle. | PBS-DTN-MAP-01 §5.1 |
| R-02 | The whole envelope is placed in one payload block, unmodified, and extracted verbatim at the receiving gateway. | PBS-DTN-MAP-01 §6.2, §6.4, §7.2 |
| R-03 | The header CRC32 verifies end to end. | PBS-DTN-MAP-01 §6.4; PBS-ENV-01 §15; PBS-SEC-A-01 §5.1 |
| R-04 | For TTL > 0 the bundle lifetime does not exceed the time remaining until the envelope expires at bundle creation. An envelope with less than 1 ms (here: 1 s, ION's granularity) left is not encapsulated. | PBS-DTN-MAP-01 §6.1; PBS-DTN-MAP-02 §4 |
| R-05 | For TTL 0 the lifetime is the documented no-expiry lifetime, which is no less than any lifetime assigned to a TTL > 0 envelope. | PBS-DTN-MAP-01 §6.1.1; PBS-DTN-MAP-02 §4 |
| R-06 | The creation timestamp is assigned by the gateway's bundle protocol agent. | PBS-DTN-MAP-01 §6.1; RFC 9171 §4.2.7 |
| R-07 | Requested DTN classes follow the Section 6.3 table. No reserved or unassigned processing control flag (including bits 7 and 8) carries priority. The Priority byte is preserved. | PBS-DTN-MAP-01 §6.3; PBS-DTN-MAP-02 §5; RFC 9171 §4.2.3 |
| R-08 | Bundles are well-formed BPv7 with valid CRCs. | RFC 9171 §4.1, §4.2.1, §4.2.2, §4.3.1, §4.3.2 |
| R-09 | Invalid bundles are discarded before PBS processing. | PBS-DTN-MAP-01 §7.1 |
| R-10 | Envelopes are stored until contact is available. | PBS-DTN-MAP-01 §9; RFC 4838 §3 |
| R-11 | DTN lifetime expiration results in discard, and the envelope is not delivered. | PBS-DTN-MAP-01 §7.3; RFC 9171 §5.5 |
| R-12 | The receiving gateway rejects an envelope whose TTL has expired (age > TTL, time in the DTN domain counted). | PBS-ENV-01 §12.2; PBS-DTN-MAP-01 §7.3 |
| R-13 | The worked example's bundles are accepted by an independent BPv7 implementation. | RFC 9171 §4 |
| R-14 | Tests run against the pinned ION release. | NPR 7150.2D SWE-187 [N1] |
| R-15 | A stopped network leaves no ION process and no shared-memory segment, so each run starts from the same state. | NPR 7150.2D SWE-191 [N1] (repeatable regression) |

## 5. Verification cross-reference matrix

Methods are those of NASA/SP-2016-6105 Rev 2 §5.3 [N3]: **T** test, **D** demonstration, **I** inspection, **A** analysis. "UT" cases run without ION in every CI job, and "IT" cases run against ION in the `ion-e2e` CI job.

| Req. | Test cases | Method |
|------|------------|--------|
| R-01 | IT-01, IT-02, IT-03 | T |
| R-02 | IT-01, IT-02, IT-04, IT-05, UT-18 | T |
| R-03 | IT-01, IT-05, UT-17, UT-19 | T |
| R-04 | IT-02, IT-08, UT-10, UT-11, UT-12, UT-13, UT-14 | T, A (UT-12 bounds every creation time up to `c_us`) |
| R-05 | IT-12, UT-15; [mapping profile §3](PBS-ION-MAPPING-PROFILE.md) | T, A |
| R-06 | IT-02 | T |
| R-07 | IT-02, IT-03, IT-05, UT-16 | T |
| R-08 | IT-02 (each captured bundle; the decoder is itself verified by UT-01 to UT-09) | T |
| R-09 | IT-07 | T |
| R-10 | IT-09 | D |
| R-11 | IT-10 | T |
| R-12 | UT-19 | T |
| R-13 | IT-06 | T |
| R-14 | IT-11, UT-24 | I |
| R-15 | IT-13, UT-25 | T |

Reverse trace (test case → requirements): IT-01 R-01–R-03; IT-02 R-01, R-02, R-04, R-06–R-08; IT-03 R-01, R-07; IT-04 R-02; IT-05 R-02, R-03, R-07; IT-06 R-13; IT-07 R-09; IT-08 R-04; IT-09 R-10; IT-10 R-11; IT-11 R-14; IT-12 R-05; IT-13 R-15. UT-01–UT-09 verify the wire decoder that IT-02, IT-03 and IT-05 use as their measuring instrument. UT-20–UT-23 verify the generated ION configuration and the link emulator.

## 6. Test cases

Unless stated otherwise, IT preconditions are: the ION release of Section 2 is installed, and the network of Section 3 is running with both directions planned open (`open_net` fixture). Envelopes are built with PBS_LINK at the time of the test.

| ID | Objective | Procedure (summary) | Pass criteria |
|----|-----------|---------------------|---------------|
| IT-01 | Downlink delivery | Submit a NORMAL telemetry envelope, TTL 120 s, at node 1 to `ipn:2.2`. | One delivery, byte-identical; every header field equal; one bundle on link 1→2; bundle held ≥ 1 OWLT; delivery after release |
| IT-02 | ION bundle conformance and lifetime | Submit a TTL 60 s envelope; decode the captured bundle. | Decodes with all CRCs valid; source `ipn:1.1`, destination `ipn:2.2`; no reserved flag; creation time between clock reading and `c_us`; lifetime = ⌊(TTL·10⁶ − (`c_us` − Timestamp))/10⁶⌋ s; bundle expiry ≤ envelope expiry; one payload block equal to the envelope |
| IT-03 | Priority mapping | Submit one envelope of each Priority 0–4. | ION QoS block class = {2,2,1,0,0} (expected values written in the test, independent of the gateway); bits 7–8 clear; Priority byte preserved; all delivered |
| IT-04 | Payload integrity | Payloads of 256 and 8192 bytes holding every byte value. | Delivered byte-identical |
| IT-05 | Uplink delivery | CRITICAL command, TTL 300 s, from node 2 to `ipn:1.2`. | Delivered byte-identical; one bundle on link 2→1 from `ipn:2.1`, ION class 2 |
| IT-06 | Interoperability | Inject a bundle encoded by `pbs_to_bpv7_bundle_mv` on link 1→2. | Delivered byte-identical; node 2 `rcv` and `dlv` tallies +1 |
| IT-07 | Corrupted bundle discarded | Inject a bundle with one CRC32C byte inverted, then an intact control bundle. | Only the control is delivered; node 2 logs one "CRC check failed for primary block" |
| IT-08 | Refusal at the gateway | Submit a TTL 3 s envelope with Timestamp 0.1 s in the past, so 0 to 0.9 s of TTL remain at `c_us`. | `IonLifetimeGranularityError`; no spool file; `bpsendfile` not run (no new log line); node 1 `src` tally unchanged |
| IT-09 | Store-and-forward | Contact planned from now + 20 s. Submit a TTL 120 s envelope before it opens. | Bundle created before contact start; crossed the link once, at or after contact start; delivered byte-identical ≥ 1 OWLT after contact start |
| IT-10 | Expiry in storage | In the same gap, submit a TTL 6 s envelope (ION lifetime ≈ 3 s). | Never on the link; never delivered; node 1 `exp` tally ≥ 1 |
| IT-11 | Release under test | Ask `ionadmin` for its version. | `ION-OPEN-SOURCE-4.2.0` |
| IT-12 | TTL 0 through ION | Submit a TTL 0 envelope. | Bundle lifetime 2 147 483 647 000 ms; delivered byte-identical; node 1 `exp` tally unchanged |
| IT-13 | Clean stop | Start and stop a network; inspect `/proc`. | While running, each node's processes and segments exist; after stop, no process in a node directory and no segment with a node's key |

| ID | Objective |
|----|-----------|
| UT-01 | Decoder reads a worked-example bundle: EIDs, creation timestamp, lifetime, payload |
| UT-02 | Decoder rejects a primary block with one corrupted byte (six positions) |
| UT-03 | Decoder verifies a CRC-16 canonical block and rejects it after a one-bit change |
| UT-04 | CRC-16/X-25 check value 0x906E for "123456789" |
| UT-05 | Decoder rejects a missing array head, trailing bytes and a missing break code |
| UT-06 | Decoder rejects version 6 and fragments |
| UT-07 | Decoder requires the payload block last |
| UT-08 | ION QoS block (type 193) decoding |
| UT-09 | Reserved-flag detection; EID text forms, including the 3-element ipn form (RFC 9758) |
| UT-10 | Lifetime computed at `c_us` = clock + latency bound: exact value 118 s |
| UT-11 | Lifetime floored to whole seconds: bound 117 499 ms gives 117 s |
| UT-12 | For five ages, the latest possible creation time + lifetime ≤ Timestamp + TTL |
| UT-13 | Under 1 s left refused, exactly 1 s accepted |
| UT-14 | Expired envelope refused |
| UT-15 | TTL 0 gives 2 147 483 647 s (2^31 − 1, bp_send's int limit, within 4 294 967 295 000 ms); the largest TTL is capped to it, a smaller TTL is not |
| UT-16 | Priority → ION class table, and its monotonicity |
| UT-17 | Bad header CRC32, trailing bytes, invalid arguments refused |
| UT-18 | Restored envelope returned unmodified |
| UT-19 | Restore rejects an expired or corrupted envelope; TTL 0 never expires |
| UT-20 | ION absolute UTC time format |
| UT-21 | Generated ionconfig, ionrc, bprc and ipnrc contents |
| UT-22 | Earth–Moon OWLT value |
| UT-23 | Emulator delays by the OWLT, preserves order and records each datagram |
| UT-24 | Release pin identical in the build script and the Python package |
| UT-25 | Shared-memory keys distinct, unused by any existing segment, and in the harness's range |

### 6.1 Measurement independence

The checks do not rely on the code under test reporting its own success:

- Delivery is observed through files written by ION's `bprecvfile`, not through a gateway return value.
- Bundle conformance is checked on the bytes captured from the link. The decoder computes each CRC over the received bytes with the CRC field zeroed (RFC 9171 §4.2.2) and does not re-encode the bundle. The decoder is verified separately against known vectors (UT-02 to UT-04).
- IT-02 and IT-03 compute their expected values from the envelope and from the specification table, not from the gateway's plan or mapping table.
- Absence is checked with a positive control or with ION's own records. IT-07 requires the control envelope to be delivered. IT-08 requires that `bpsendfile` left no log line and that node 1's `src` tally is unchanged. IT-10 requires ION's `exp` tally. Bytes a test injects onto the link are marked as injected and are excluded when bundles from ION are inspected. Every bundle a node sends must decode.

### 6.2 Mutation check of the tests

Before release, the following faults were each introduced into the code under test, and the suite was run against ION 4.2.0. Each fault made at least one test fail:

| Fault introduced | Tests that failed (full suite against ION 4.2.0) |
|------------------|--------------------------------------------------|
| PBS LOW mapped to ION standard (1) instead of bulk (0) | UT-16, IT-03 |
| Lifetime rounded up by 1 s | UT-10, UT-11, UT-12, UT-13, UT-15, IT-02, IT-08, IT-12 |
| `c_us` set to the clock reading, without the latency bound | UT-10, UT-11, UT-12, UT-13, IT-02, IT-08 |
| Decoder CRC check skipped | UT-02, UT-03 |

Each test waits for its own envelope (`deliveries_of`), so an envelope that a faulty gateway lets through in one test cannot be taken for another test's delivery. A delivery from IT-08 under the third fault showed that this was needed.

IT-02 and IT-03 were strengthened after the first round of this check. In that round IT-03 passed with the first fault present, because it compared ION's class with the gateway's own table. IT-02 passed with the second and third faults present, because the 2 s latency bound absorbed the error. Both now compute their expected values independently (Section 6.1).

## 7. Execution, evaluation and records

**Procedure.**

```bash
scripts/build_ion.sh                 # builds the pinned ION into .ion/install
export ION_PREFIX="$PWD/.ion/install"
python -m pip install -r requirements-ion-demo.txt
PBS_ION_REQUIRED=1 pytest -v --junitxml=ion-test-results/junit.xml
```

- **Pass/fail.** A test case passes when every pass criterion holds. The run passes when every UT and IT case passes. A skipped IT case counts as a failure when `PBS_ION_REQUIRED=1`, which the `ion-e2e` CI job sets.
- **Records (SWE-068 [N1]).** Each run writes `ion-test-results/as-run-<UTC>.json` with the ION version, release tag and commit, host, Python version, start and end times, and for each IT case its outcome, duration and measured values: bundle bytes in hex, block list, flags, creation time, lifetime, expiry margin, link delay and tallies. The `runs-<UTC>/` directory beside it keeps each node's generated configuration, `ion.log`, spool and inbox. CI uploads the directory and the JUnit XML as an artifact of each run.
- **Anomalies.** A failed case is analyzed from these records before any change to the code or the test. A test's pass criteria are not relaxed to make it pass.
- **Regression (SWE-191 [N1]).** All UT and IT cases run on every push and pull request.
- **Timing margins.** Delivery waits up to 30 s for an event expected within about 3 s. The IT-07 absence check waits 6 s, more than two OWLTs plus ION's 1 s clock cycle. A loaded runner can lengthen delays but cannot make an absence check pass falsely: IT-07 needs its control delivered, and IT-10 needs ION's `exp` tally.

## 8. Limitations

- One host: the nodes share a clock, so the tests do not exercise clock offset between nodes. ION's creation time and the gateway's clock reading are consistent by construction.
- UDP convergence layer only: no LTP (RFC 5326), so no segmentation or retransmission. Bundles are limited to 65 507 bytes over IPv4; ION's own check allows 65 535.
- No BPSec (RFC 9172), custody transfer, fragmentation, or multi-hop contact graph routing [S3][S4].
- Priority scheduling between classes under contention is described in the mapping profile §4.3 from ION's source and is not measured.
- The tests verify the demonstration gateway and ION's behavior in this configuration. They do not qualify ION or the gateway for flight use.

## 9. References

**NASA documents**

- [N1] NASA, *NASA Software Engineering Requirements*, NPR 7150.2D, 8 March 2022: SWE-052 (§3.12.1), SWE-065 (§4.5.2), SWE-066 (§4.5.3), SWE-068 (§4.5.5), SWE-187 (§4.5.4), SWE-191 (§4.5.11). <https://nodis3.gsfc.nasa.gov/displayDir.cfm?t=NPR&c=7150&s=2D>
- [N2] NASA, *Software Assurance and Software Safety Standard*, NASA-STD-8739.8B, 8 September 2022. <https://standards.nasa.gov/standard/NASA/NASA-STD-87398>
- [N3] NASA, *NASA Systems Engineering Handbook*, NASA/SP-2016-6105 Rev 2, 2017, §5.3 Product Verification. <https://ntrs.nasa.gov/citations/20170001761>
- [N4] NASA, *NASA Software Engineering Handbook*, NASA-HDBK-2203: [5.10 Software Test Plan](https://swehb.nasa.gov/spaces/SWEHBVD/pages/102695671/5.10+-+STP+-+Software+Test+Plan), [5.14 Software Test Procedures](https://swehb.nasa.gov/spaces/SWEHBVD/pages/102695675/5.14+-+Test+-+Software+Test+Procedures), [5.11 Software Test Report](https://swehb.nasa.gov/spaces/SWEHBVD/pages/102695672/5.11+-+STR+-+Software+Test+Report).
- [N5] ISO/IEC/IEEE 29119-3:2021, *Software testing — Part 3: Test documentation*. <https://www.iso.org/standard/79429.html>

**Protocol specifications**

- [R1] S. Burleigh, K. Fall, E. Birrane, *Bundle Protocol Version 7*, RFC 9171, January 2022. <https://www.rfc-editor.org/rfc/rfc9171>
- [R2] E. Birrane, K. McKeever, *Bundle Protocol Security (BPSec)*, RFC 9172, January 2022. <https://www.rfc-editor.org/rfc/rfc9172>
- [R3] V. Cerf et al., *Delay-Tolerant Networking Architecture*, RFC 4838, April 2007 (§3.5 Priority Classes). <https://www.rfc-editor.org/rfc/rfc4838>
- [R4] R. Taylor, E. Birrane, *Updates to the 'ipn' URI Scheme*, RFC 9758, May 2025. <https://www.rfc-editor.org/rfc/rfc9758>
- [R5] M. Ramadas, S. Burleigh, S. Farrell, *Licklider Transmission Protocol – Specification*, RFC 5326, September 2008. <https://www.rfc-editor.org/rfc/rfc5326>
- [R6] K. Scott, S. Burleigh, *Bundle Protocol Specification*, RFC 5050, November 2007. <https://www.rfc-editor.org/rfc/rfc5050>
- [R7] PBS-ENV-01, PBS-DTN-MAP-01, PBS-DTN-MAP-02, PBS-PRIO-01 and PBS-SEC-A-01, v1.5 (PBS v1.5.0). <https://github.com/Pale-Blue-Systems/PBS-PROTOCOL-OPEN/tree/main/PBS-RFC-LIB>
- [R8] NASA/JPL, *Interplanetary Overlay Network (ION)*, release ion-open-source-4.2.0. <https://github.com/nasa-jpl/ION-DTN/tree/ion-open-source-4.2.0>
- [R12] NASA NSSDCA, *Moon Fact Sheet* (semimajor axis 384 400 km). <https://nssdc.gsfc.nasa.gov/planetary/factsheet/moonfact.html>
- [R13] BIPM, *The International System of Units (SI Brochure)*, 9th ed., 2019 (c = 299 792 458 m/s, exact). <https://www.bipm.org/en/publications/si-brochure>

**Scholarly sources**

- [S1] S. Burleigh, "Interplanetary Overlay Network: An Implementation of the DTN Bundle Protocol," *4th IEEE Consumer Communications and Networking Conference (CCNC)*, 2007, pp. 222–226. doi:[10.1109/CCNC.2007.51](https://doi.org/10.1109/CCNC.2007.51)
- [S2] S. Burleigh, A. Hooke, L. Torgerson, K. Fall, V. Cerf, B. Durst, K. Scott, H. Weiss, "Delay-tolerant networking: an approach to interplanetary Internet," *IEEE Communications Magazine*, 41(6):128–136, 2003. doi:[10.1109/MCOM.2003.1204759](https://doi.org/10.1109/MCOM.2003.1204759)
- [S3] G. Araniti et al., "Contact graph routing in DTN space networks: overview, enhancements and performance," *IEEE Communications Magazine*, 53(3):38–46, 2015. doi:[10.1109/MCOM.2015.7060480](https://doi.org/10.1109/MCOM.2015.7060480)
- [S4] J. A. Fraire, O. De Jonckère, S. C. Burleigh, "Routing in the Space Internet: A contact graph routing tutorial," *Journal of Network and Computer Applications*, 174:102884, 2021. doi:[10.1016/j.jnca.2020.102884](https://doi.org/10.1016/j.jnca.2020.102884)
- [S5] J. Wyatt, S. Burleigh, R. Jones, L. Torgerson, S. Wissler, "Disruption Tolerant Networking Flight Validation Experiment on NASA's EPOXI Mission," *First International Conference on Advances in Satellite and Space Communications (SPACOMM)*, 2009, pp. 187–196. doi:[10.1109/SPACOMM.2009.39](https://doi.org/10.1109/SPACOMM.2009.39)
- [S6] A. Schlesinger, B. M. Willman, L. Pitts, S. R. Davidson, W. A. Pohlchuck, "Delay/Disruption Tolerant Networking for the International Space Station (ISS)," *2017 IEEE Aerospace Conference*, pp. 1–14. doi:[10.1109/AERO.2017.7943857](https://doi.org/10.1109/AERO.2017.7943857)
- [S7] G. J. Holzmann, "The Power of 10: Rules for Developing Safety-Critical Code," *Computer*, 39(6):95–97, 2006. doi:[10.1109/MC.2006.212](https://doi.org/10.1109/MC.2006.212)
