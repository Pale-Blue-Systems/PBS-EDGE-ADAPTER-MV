# PBS-ION-MAPPING-PROFILE: PBS to BPv7 Mapping Profile for ION 4.2.0

**Applies to:** `pbs_ion_demo/ion_gateway.py`, the PBS gateway function of the end-to-end demonstration ([PBS-ION-E2E-DEMO.md](PBS-ION-E2E-DEMO.md)).
**Bundle protocol agent:** NASA/JPL Interplanetary Overlay Network, release `ion-open-source-4.2.0`, commit `568df887cb9f18aa8ec013b1a566d83215e499ae` (<https://github.com/nasa-jpl/ION-DTN>), built with its default configuration on 64-bit (LP64) Linux.
**Specifications:** PBS-DTN-MAP-01 v1.5 Sections 6.1, 6.1.1 and 6.3; PBS-DTN-MAP-02 v1.5 Sections 4 and 5.

PBS-DTN-MAP-01 Section 6.1.1 and PBS-DTN-MAP-02 Section 4 require a gateway to document its no-expiry lifetime and the bundle protocol agent for which it was selected. PBS-DTN-MAP-01 Section 6.3 and PBS-DTN-MAP-02 Section 5 require a gateway that requests network treatment on the basis of PBS priority to document the mapping in a mapping profile. This document is both records for the demonstration gateway. Every statement about ION below cites the ION 4.2.0 source file it was read from.

---

## 1. Interface to the bundle protocol agent

The gateway hands each envelope to ION with ION's `bpsendfile` program:

```
bpsendfile ipn:N.1 <destination EID> <spool file> 0.<class of service> <lifetime in seconds>
```

`bpsendfile` calls `bp_send()` (`bpv7/utils/bpsendfile.c`). ION's bundle protocol agent creates the bundle and assigns its creation timestamp (PBS-DTN-MAP-01 Section 6.1, "Gateway BPA"). The payload is the spool file's bytes, the envelope as received; ION reads the file when it transmits the bundle (`zco_create_file_ref`), so the gateway keeps the file until the network stops.

The gateway accepts a submission only when ION's log records `bpsendfile sent '<spool file>', size <n>.`, which `bpsendfile` writes after `bp_send()` succeeds. The exit status alone is not used: `bpsendfile` exits 0 when it cannot create the payload object.

## 2. Bundle lifetime (PBS-DTN-MAP-01 Section 6.1)

ION assigns the creation time after the gateway computes the lifetime. Section 6.1 provides for this case: the gateway "meets this bound by using for `c_us` a time not earlier than that creation time, such as its clock reading plus the maximum latency of the transmission request."

| Item | Value |
|------|-------|
| `c_us` | gateway clock reading + `max_submit_latency_us` (default 2 000 000 µs) |
| Bound for TTL > 0 | ⌊(TTL × 1 000 000 − max(0, `c_us` − Timestamp)) / 1000⌋ ms, the Section 6.1 formula at `c_us` (computed by the worked example's `bundle_lifetime_ms`) |
| Lifetime requested from ION | ⌊bound / 1000⌋ s, because `bp_send()` takes whole seconds and multiplies by 1000 (`bpv7/library/libbp.c`, `bp_send`: "lifespan must be converted from seconds to milliseconds") |
| Refusal | An envelope that has expired at `c_us`, or for which the bound is under 1000 ms, is not submitted (`EnvelopeExpiredError`, `IonLifetimeGranularityError`) |
| Latency check | After `bpsendfile` exits, the gateway checks that no more than `max_submit_latency_us` has passed since its clock reading, and raises `SubmitLatencyExceeded` otherwise. `bp_send()` creates the bundle before `bpsendfile` exits, so the creation time is not later than `c_us` |

ION computes DTN time as Unix time minus `EPOCH_2000_SEC` (946 684 800 s) in milliseconds (`bpv7/library/libbpP.c`, `getCurrentDtnTime`; `bpv7/library/bpP.h`), the same conversion that the PBS-DTN-MAP-01 Section 6.1 formula uses for `c_us`. Its creation time and the gateway's clock reading come from the same host clock.

Rounding down to whole seconds keeps the bundle's expiry no later than the envelope's. Test IT-02 measures the difference on every run.

## 3. No-expiry lifetime (PBS-DTN-MAP-01 Section 6.1.1; PBS-DTN-MAP-02 Section 4)

**No-expiry lifetime: 2 147 483 647 000 ms (2 147 483 647 s), selected for ION 4.2.0 on 64-bit Linux.**

- `bp_send()` declares the lifetime as `int` seconds, so 2 147 483 647 s (`INT_MAX`) is the largest lifetime ION accepts through it. This is less than the 4 294 967 295 000 ms upper limit of the specifications.
- ION computes the expiration time as creation time + lifetime in 64-bit unsigned integers (`uvast`) and stores it as a `time_t` count of seconds (`bpv7/library/bpP.h`, `Bundle.expirationTime`; `libbpP.c`, `computeExpirationTime`). On LP64 Linux `time_t` is 64 bits wide, so the computation does not overflow. A platform with a 32-bit `time_t` would overflow, and this value is not selected for one.
- The gateway assigns min(no-expiry lifetime, Section 6.1 bound) to every envelope with TTL > 0, so no assigned lifetime exceeds the no-expiry lifetime (Section 6.1.1, second condition). Unit test UT-15 checks this, including at the largest TTL, 4 294 967 295 s.
- The gateway reads no Service Intent frame and applies no mission expiry policy, so no PBS-DTN-MAP-02 Section 4 finite limit applies to a TTL 0 envelope.

## 4. Priority and network treatment (PBS-DTN-MAP-01 Section 6.3; PBS-DTN-MAP-02 Section 5)

### 4.1 Mechanism

ION provides the three priority classes of the DTN architecture (RFC 4838 Section 3.5) through the class-of-service argument of `bp_send()`: `BP_BULK_PRIORITY` 0, `BP_STD_PRIORITY` 1, `BP_EXPEDITED_PRIORITY` 2 (`bpv7/include/bp.h`). The gateway passes it in the `bpsendfile` class-of-service string `0.<class>` (no custody requested; `BP_PARSE_QUALITY_OF_SERVICE_USAGE`).

ION carries the class in its Quality of Service extension block, block type 193 (`bpv7/include/bp.h`, `QualityOfServiceBlk`), whose data is the CBOR array [flags, class of service, ordinal, data label] (`bpv7/library/ext/bpq/bpq.c`, `qos_serialize`). RFC 9171 does not define this block. Block types 192 to 255 are reserved for private or experimental use (RFC 9171 Section 9.1), and PBS-DTN-MAP-01 Section 6.3 permits treatment "through a bundle protocol agent interface or an extension block that RFC 9171 does not define". A BPv7 agent other than ION that receives the block treats it as an unknown block type (RFC 9171 Section 4.3.2 and its block processing control flags).

No bundle processing control flag carries priority. ION set flags 0x40 ("status time requested in reports") in every bundle captured in the tests, and set no reserved or unassigned flag, including bits 7 and 8 (tests IT-02, IT-03).

### 4.2 Mapping (the PBS-DTN-MAP-01 Section 6.3 table)

| PBS Priority (PBS-PRIO-01 Section 4) | DTN class (RFC 4838 Section 3.5) | ION class of service |
|---|---|---|
| CRITICAL (0) | Expedited | 2 |
| HIGH (1) | Expedited | 2 |
| NORMAL (2) | Normal | 1 |
| LOW (3) | Bulk | 0 |
| BULK (4) | Bulk | 0 |

The envelope is not modified; the receiving PBS node reads all five classes from the Priority byte. The gateway requests no ordinal (ancillary priority within the expedited class) and no other treatment.

### 4.3 Queue and scheduling treatment

ION keeps three transmission queues for each neighbor ("egress plan"): bulk, standard and urgent (`libbpP.c`, plan creation). A bundle of class 2 goes to the urgent queue, ordered by ordinal (`libbpP.c`, `enqueueUrgentBundle`). The plan's convergence-layer manager `bpclm` selects bundles in strict priority: urgent, then standard, then bulk (`bpv7/daemon/bpclm.c`, `selectNextBundleForTransmission`, "Strict priority, which is the default"). A build that defines `ION_BANDWIDTH_RESERVED` instead shares the link between the standard and bulk queues in a 2:1 ratio, and urgent traffic still goes first. The demonstration uses the default build.

### 4.4 Behavior under congestion

- **Transmission rate.** `bpclm` sends no faster than the rate of the current contact in the contact plan, and sends nothing while no contact is in effect (`bpclm.c`, rate control; `ionadmin` contact plan). Bundles wait in the queues of Section 4.3. Under strict priority, a sustained flow of expedited bundles can delay standard and bulk bundles until their lifetimes end.
- **Storage.** A bundle waits in ION's storage (SDR) until it is transmitted or its lifetime ends, and is then deleted (RFC 9171 Section 5.5). Tests IT-09 and IT-10 demonstrate both outcomes.
- **Admission.** When ION lacks the space to hold the payload, `bpsendfile` cannot create the payload object and `bp_send()` is not called. The gateway does not find ION's acceptance record, raises `IonError` and keeps no record of the bundle (Section 1). The PBS source decides whether to retry.

### 4.5 Behavior when the requested treatment is unavailable

ION 4.2.0 always offers all three classes. Expedited treatment cannot speed up a link that has no contact. The bundle waits for the next contact in the contact plan, whatever its class, and is deleted if its lifetime ends first. The gateway does not change the class it requested and does not modify the envelope.

## 5. Limits of this profile

- **Bundle size.** ION's UDP convergence layer sends each bundle in one datagram and refuses a bundle longer than 65 535 bytes (`bpv7/udp/udpcla.h`, `UDPCLA_BUFSZ`; `libudpcla.c`, `sendBundleByUDP`). PBS_LINK accepts payloads up to 65 536 bytes (`MAX_PAYLOAD_SIZE_DEFAULT`). A deployment carrying envelopes near that size uses a convergence layer without this limit, such as LTP (RFC 5326) or TCP.
- **Security.** No BPSec block is added (PBS-DTN-MAP-02 Section 7; RFC 9172). The header CRC32 covers the 44-byte header only (PBS-ENV-01 Section 16.2). ION's payload-block CRC (CRC-16, observed in every captured bundle) detects corruption on the link but gives no authentication.
- **Inbound.** The receiving gateway checks the restored envelope (magic, header CRC32, length, and TTL expiry counted from Timestamp, PBS-ENV-01 Section 12.2). It does not implement PBS sequence tracking or PBS-native routing (PBS-DTN-MAP-01 Section 7.2).
