"""
ION end-to-end integration tests, IT-01 to IT-11.

Each test is one test case of DOCS/PBS-ION-E2E-TEST-PLAN.md. The docstring
of each test gives the requirement it verifies, the verification method
(T test, D demonstration, I inspection; NASA/SP-2016-6105 Rev 2 Section
5.3), the procedure and the pass criteria; the test code is the executable
procedure. Every check is made on observed data: bytes delivered by ION's
bprecvfile, bundles captured on the emulated link and decoded by
pbs_ion_demo.bpv7_wire, and ION's own bpstats tallies and log messages.

Network: node 1 (ipn:1, lunar PBS gateway) and node 2 (ipn:2, Earth PBS
gateway), ION 4.2.0, UDP convergence layer, link emulator adding the
Earth-Moon one-way light time (1.2822 s) in each direction.
"""

from __future__ import annotations

import time

import pytest
from PBS_LINK import PBSLink, Priority

from pbs_edge_adapter_worked_example import (
    BPF_ASSIGNED_MASK,
    DTN_EPOCH_UNIX_MS,
    AuthorityContextMap,
    CreationTimestampCounter,
    eid_ipn,
    pbs_to_bpv7_bundle_mv,
)
from pbs_ion_demo.bpv7_wire import (
    BLOCK_TYPE_ION_QOS,
    BLOCK_TYPE_PAYLOAD,
    decode_bundle,
    eid_to_text,
    ion_qos,
    item_end,
    reserved_flags_set,
)
from pbs_ion_demo.ion_gateway import ION_NO_EXPIRY_LIFETIME_MS, IonLifetimeGranularityError
from pbs_ion_demo.ion_node import shm_segments
from pbs_ion_demo.ion_release import ION_VERSION_STRING
from pbs_ion_demo.scenario import ContactWindow, LunarEarthNetwork, always_open

pytestmark = pytest.mark.ion

DELIVERY_TIMEOUT_S = 30
# Time to wait before concluding that a bundle will not arrive: two one-way
# light times plus ION's 1 s bpclock cycle, with margin.
ABSENCE_WAIT_S = 6
# Bundle processing control flag bits 7 and 8: class of service in BPv6
# (RFC 5050 Section 4.2), reserved in BPv7 (RFC 9171 Section 4.2.3).
BPV6_COS_BITS = 0x000180

# PBS-DTN-MAP-01 Section 6.3 table, written out here independently of
# pbs_ion_demo.ion_gateway, in ION class-of-service codes (ION bp.h:
# 0 bulk, 1 standard, 2 expedited).
SECTION_6_3_ION_CLASS = {
    Priority.CRITICAL: 2,
    Priority.HIGH: 2,
    Priority.NORMAL: 1,
    Priority.LOW: 0,
    Priority.BULK: 0,
}


def rover_link() -> PBSLink:
    return PBSLink(device_id="Rover-Alpha")


def captures_of(channel, envelope_bytes: bytes, expected: int = 1, timeout_s: float = DELIVERY_TIMEOUT_S):
    """
    (capture, decoded bundle) pairs, for bundles a node put on the link,
    whose payload is envelope_bytes. Every such capture must decode: a
    malformed bundle from ION fails the test. Bytes a test injected itself
    (IT-06, IT-07) are not considered.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        found = []
        for c in channel.captures():
            if c.injected:
                continue
            b = decode_bundle(c.data)
            if b.payload == envelope_bytes:
                found.append((c, b))
        if len(found) >= expected or time.monotonic() >= deadline:
            return found
        time.sleep(0.05)


def deliveries_of(gateway, envelopes, timeout_s: float = DELIVERY_TIMEOUT_S):
    """
    Deliveries at gateway of the given envelopes, collected until each has
    arrived or timeout_s has passed. A delivery of any other envelope (for
    example one left by an earlier failed test) is collected and ignored,
    so one test's failure cannot pass or fail another.
    """
    wanted = set(envelopes)
    got = []
    deadline = time.monotonic() + timeout_s
    while not wanted <= {d.envelope_bytes for d in got}:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        got += [d for d in gateway.receive(1, min(remaining, 1.0)) if d.envelope_bytes in wanted]
    return got


@pytest.fixture(scope="module")
def open_net(ion_toolchain, run_root):
    """Both directions planned open for the whole module."""
    net = LunarEarthNetwork(ion_toolchain, run_root / "open-link", always_open(3600))
    net.start()
    net.earth.start_receiver(0)   # 0: no limit on the number of files
    net.lunar.start_receiver(0)
    try:
        yield net
    finally:
        net.stop()


# -----------------------------------------------------------------------
# IT-01  Downlink delivery, lunar gateway -> Earth gateway
# -----------------------------------------------------------------------

def test_it01_downlink_envelope_delivered_verbatim(open_net, evidence):
    """
    Requirements: PBS-DTN-MAP-01 Sections 5.1 (one envelope, one bundle),
    6.2 and 6.4 (envelope unmodified, CRC32 preserved), 7.2 (extracted
    verbatim); PBS-ENV-01 Section 15 (header CRC32 verifies end to end).
    Method: T.
    Preconditions: open_net running; contact open in both directions.
    Procedure: build a NORMAL-priority telemetry envelope, TTL 120 s, with
      PBS_LINK; submit it at node 1 to ipn:2.2; wait for delivery at node 2.
    Pass criteria:
      1. exactly one payload delivered at ipn:2.2, byte-identical to the
         envelope submitted;
      2. PBS_LINK.parse_envelope accepts it (magic, header CRC32, length)
         and every header field equals the submitted value;
      3. exactly one bundle carrying it crossed the link;
      4. the bundle spent at least one OWLT on the link, and delivery
         followed its release.
    """
    net = open_net
    env = rover_link().send(Priority.NORMAL, b"VOLTAGE=119.7,CURRENT=18.2,TEMP=-41.5", ttl=120)
    sub = net.lunar.submit(env, net.earth.receive_eid)
    deliveries = deliveries_of(net.earth, [env])
    caps = captures_of(net.emulator["1->2"], env)

    assert len(deliveries) == 1
    d = deliveries[0]
    assert d.envelope_bytes == env
    sent = sub.plan.envelope
    for f in ("magic", "priority", "source_id", "timestamp", "ttl", "sequence", "size", "crc32", "payload"):
        assert getattr(d.envelope, f) == getattr(sent, f), f
    assert len(caps) == 1
    cap, _ = caps[0]
    assert cap.release_unix_ns - cap.arrival_unix_ns >= int(net.owlt_s * 1e9)
    assert d.restored_unix_us * 1000 >= cap.release_unix_ns

    evidence.update({
        "envelope_hex": env.hex(),
        "delivered_file": str(d.file_path),
        "link_delay_s": (cap.release_unix_ns - cap.arrival_unix_ns) / 1e9,
        "submit_to_delivery_s": (d.restored_unix_us - sub.plan.clock_us) / 1e6,
    })


# -----------------------------------------------------------------------
# IT-02  The bundle ION puts on the link
# -----------------------------------------------------------------------

def test_it02_ion_bundle_conforms_and_respects_envelope_ttl(open_net, evidence):
    """
    Requirements: RFC 9171 Sections 4.1, 4.2.1-4.2.3, 4.3.1, 4.3.2 (bundle
    format, CRCs, flags); PBS-DTN-MAP-01 Section 6.1 (lifetime bound,
    creation timestamp assigned by the gateway's BPA), Section 6.2
    (whole envelope in the payload block), Section 6.3 (no reserved flag).
    Method: T.
    Procedure: submit a TTL 60 s envelope; capture the bundle on link
      1->2 and decode it with the independent decoder.
    Pass criteria:
      1. the bundle decodes: CBOR indefinite array, version 7, every block
         CRC verifies over the bytes as received, payload block last;
      2. source ipn:1.1, destination ipn:2.2;
      3. no reserved or unassigned processing control flag is set,
         including bits 7 and 8;
      4. creation time lies between the gateway's clock reading and
         c_us = clock reading + maximum submission latency (ION assigned it
         during the request);
      5. c_us is the clock reading plus the configured latency bound; the
         lifetime is floor((TTL x 10^6 - (c_us - Timestamp)) / 10^6) s,
         computed here from the envelope, in whole seconds as ION's bp_send
         takes it; creation time + lifetime is not later than the
         envelope's Timestamp + TTL;
      6. one payload block, whose data is the envelope.
    """
    net = open_net
    env = rover_link().send(Priority.NORMAL, b"BUS=28.1V", ttl=60)
    sub = net.lunar.submit(env, net.earth.receive_eid)
    caps = captures_of(net.emulator["1->2"], env)
    deliveries_of(net.earth, [env])  # drain; IT-01 verifies delivery

    assert len(caps) == 1
    _, b = caps[0]
    assert eid_to_text(b.source) == net.lunar.send_eid == "ipn:1.1"
    assert eid_to_text(b.destination) == net.earth.receive_eid == "ipn:2.2"
    assert reserved_flags_set(b) == 0
    assert b.bundle_proc_flags & BPV6_COS_BITS == 0
    assert b.bundle_proc_flags & ~BPF_ASSIGNED_MASK == 0
    plan = sub.plan
    assert plan.clock_us // 1000 - DTN_EPOCH_UNIX_MS <= b.creation_time_ms <= plan.c_us // 1000 - DTN_EPOCH_UNIX_MS
    assert plan.c_us == plan.clock_us + net.lunar.max_submit_latency_us
    age_at_c_us = max(0, plan.c_us - plan.envelope.timestamp)
    expected_lifetime_s = (60 * 1_000_000 - age_at_c_us) // 1_000_000
    assert b.lifetime_ms == expected_lifetime_s * 1000
    assert b.expiry_unix_ms <= plan.envelope_expiry_unix_ms
    assert [x.block_type for x in b.blocks].count(BLOCK_TYPE_PAYLOAD) == 1
    assert b.payload == env

    evidence.update({
        "bundle_hex": b.raw.hex(),
        "blocks": [(x.block_type, x.block_number, x.block_proc_flags, x.crc_type) for x in b.blocks],
        "bundle_proc_flags": hex(b.bundle_proc_flags),
        "primary_crc_type": b.primary_crc_type,
        "creation_time_ms": b.creation_time_ms,
        "creation_seq": b.creation_seq,
        "lifetime_ms": b.lifetime_ms,
        "bundle_expiry_unix_ms": b.expiry_unix_ms,
        "envelope_expiry_unix_ms": plan.envelope_expiry_unix_ms,
        "margin_ms": plan.envelope_expiry_unix_ms - b.expiry_unix_ms,
    })


# -----------------------------------------------------------------------
# IT-03  Priority classes
# -----------------------------------------------------------------------

def test_it03_priority_maps_to_ion_class_and_is_preserved(open_net, evidence):
    """
    Requirements: PBS-DTN-MAP-01 Section 6.3 (table: CRITICAL, HIGH ->
    Expedited; NORMAL -> Normal; LOW, BULK -> Bulk; no reserved flag);
    PBS-PRIO-01 (Priority preserved end to end); PBS-DTN-MAP-02 Section 5
    (mapping profile, DOCS/PBS-ION-MAPPING-PROFILE.md).
    Method: T.
    Procedure: submit one envelope of each Priority 0-4; capture each
      bundle; collect the deliveries.
    Pass criteria:
      1. each bundle's ION QoS block (type 193) carries the ION class the
         table gives (2 expedited, 1 standard, 0 bulk);
      2. no bundle sets processing control flag bits 7 or 8;
      3. each delivered envelope is byte-identical to the one submitted and
         keeps its Priority byte.
    """
    net = open_net
    link = rover_link()
    sent = {p: link.send(p, f"PRIORITY-{int(p)}".encode(), ttl=120) for p in Priority}
    for env in sent.values():
        net.lunar.submit(env, net.earth.receive_eid)
    deliveries = deliveries_of(net.earth, sent.values())
    delivered = {d.envelope_bytes for d in deliveries}

    observed = {}
    for prio, env in sent.items():
        caps = captures_of(net.emulator["1->2"], env)
        assert len(caps) == 1, prio
        _, b = caps[0]
        qos = ion_qos(b)
        assert qos is not None, f"{prio.name}: no ION QoS block (type {BLOCK_TYPE_ION_QOS})"
        assert qos["class_of_service"] == SECTION_6_3_ION_CLASS[prio], prio
        assert b.bundle_proc_flags & BPV6_COS_BITS == 0
        assert env in delivered
        assert env[0x01] == int(prio)
        observed[prio.name] = qos["class_of_service"]
    assert len(deliveries) == len(sent)
    evidence["ion_class_by_priority"] = observed


# -----------------------------------------------------------------------
# IT-04  Payload integrity
# -----------------------------------------------------------------------

@pytest.mark.parametrize("size", [256, 8192])
def test_it04_every_byte_value_survives(open_net, evidence, size):
    """
    Requirements: PBS-DTN-MAP-01 Sections 6.2, 6.4, 7.2 (envelope not
    interpreted or altered by the DTN layer).
    Method: T.
    Procedure: submit envelopes whose payload holds every byte value 0x00-
      0xFF, repeated to 256 and 8192 bytes.
    Pass criteria: the delivered payload is byte-identical to the envelope.
    """
    net = open_net
    payload = bytes(i % 256 for i in range(size))
    env = rover_link().send(Priority.LOW, payload, ttl=120)
    net.lunar.submit(env, net.earth.receive_eid)
    deliveries = deliveries_of(net.earth, [env])
    assert len(deliveries) == 1
    assert deliveries[0].envelope_bytes == env
    assert deliveries[0].envelope.payload == payload
    evidence["envelope_bytes"] = len(env)


# -----------------------------------------------------------------------
# IT-05  Uplink, Earth gateway -> lunar gateway
# -----------------------------------------------------------------------

def test_it05_uplink_critical_command_delivered(open_net, evidence):
    """
    Requirements: as IT-01, in the other direction; PBS-DTN-MAP-01
    Section 6.3 for CRITICAL (Expedited).
    Method: T.
    Procedure: build a CRITICAL command envelope from "Earth-Ops", TTL
      300 s; submit at node 2 to ipn:1.2.
    Pass criteria: delivered at ipn:1.2 byte-identical; one bundle crossed
      link 2->1, from ipn:2.1, with ION class expedited (2).
    """
    net = open_net
    env = PBSLink(device_id="Earth-Ops").send(Priority.CRITICAL, b"CMD=SAFE_MODE", ttl=300)
    net.earth.submit(env, net.lunar.receive_eid)
    deliveries = deliveries_of(net.lunar, [env])
    caps = captures_of(net.emulator["2->1"], env)
    assert len(deliveries) == 1 and deliveries[0].envelope_bytes == env
    assert deliveries[0].envelope.priority == Priority.CRITICAL
    assert len(caps) == 1
    _, b = caps[0]
    assert eid_to_text(b.source) == "ipn:2.1"
    assert ion_qos(b)["class_of_service"] == 2
    evidence["bundle_hex"] = b.raw.hex()


# -----------------------------------------------------------------------
# IT-06, IT-07  Bundles encoded by the worked example, received by ION
# -----------------------------------------------------------------------

WORKED_EXAMPLE_MAP = AuthorityContextMap(
    table={"luna": {"dest": eid_ipn(2, 2), "src": eid_ipn(1, 0), "report_to": eid_ipn(1, 0)}}
)


def test_it06_ion_accepts_worked_example_bundle(open_net, evidence):
    """
    Requirements: RFC 9171 Sections 4.1-4.3 (bundle format): the worked
    example's encoder interoperates with an independent BPv7 implementation.
    Method: T.
    Procedure: encode an envelope with pbs_to_bpv7_bundle_mv (source
      ipn:1.0, destination ipn:2.2); send the bytes over link 1->2 to node 2.
    Pass criteria: ION delivers the payload at ipn:2.2, byte-identical to
      the envelope; ION's rcv and dlv tallies at node 2 each rise by 1.
    """
    net = open_net
    before = net.earth_node.bp_tallies()
    env = rover_link().send(Priority.CRITICAL, b"ENCODED-BY-WORKED-EXAMPLE", ttl=60)
    raw = pbs_to_bpv7_bundle_mv(env, "luna", WORKED_EXAMPLE_MAP, sequence_counter=CreationTimestampCounter())
    net.emulator["1->2"].inject(raw)
    deliveries = deliveries_of(net.earth, [env])
    after = net.earth_node.bp_tallies()
    assert len(deliveries) == 1 and deliveries[0].envelope_bytes == env
    assert after["rcv"] == before["rcv"] + 1
    assert after["dlv"] == before["dlv"] + 1
    evidence.update({"bundle_hex": raw.hex(), "tallies_before": before, "tallies_after": after})


def test_it07_ion_discards_bundle_with_bad_primary_crc(open_net, evidence):
    """
    Requirements: PBS-DTN-MAP-01 Section 7.1 (DTN-layer validation first;
    invalid bundles discarded before PBS processing); RFC 9171 Section
    4.2.1 (CRC).
    Method: T.
    Procedure: encode two envelopes with the worked example; in the first,
      invert one byte of the primary block's CRC32C value; send the corrupt
      bundle, then the intact one as a positive control.
    Pass criteria: only the control envelope is delivered; node 2's ion.log
      gains one "CRC check failed for primary block" message.
    """
    net = open_net
    marker = "CRC check failed for primary block"
    count_before = net.earth_node.ion_log().count(marker)
    link = rover_link()
    bad_env = link.send(Priority.HIGH, b"CORRUPTED-IN-TRANSIT", ttl=60)
    control = link.send(Priority.HIGH, b"POSITIVE-CONTROL", ttl=60)
    counter = CreationTimestampCounter()
    bad = bytearray(pbs_to_bpv7_bundle_mv(bad_env, "luna", WORKED_EXAMPLE_MAP, sequence_counter=counter))
    primary_end = item_end(bytes(bad), 1)
    bad[primary_end - 1] ^= 0xFF  # last byte of the CRC32C value
    good = pbs_to_bpv7_bundle_mv(control, "luna", WORKED_EXAMPLE_MAP, sequence_counter=counter)

    net.emulator["1->2"].inject(bytes(bad))
    net.emulator["1->2"].inject(good)
    deliveries = deliveries_of(net.earth, [control, bad_env], ABSENCE_WAIT_S)
    assert [d.envelope_bytes for d in deliveries] == [control]
    assert net.earth_node.ion_log().count(marker) == count_before + 1
    evidence["corrupt_bundle_hex"] = bytes(bad).hex()


# -----------------------------------------------------------------------
# IT-08  Gateway refusal
# -----------------------------------------------------------------------

def test_it08_envelope_without_a_whole_second_left_is_not_submitted(open_net, evidence):
    """
    Requirements: PBS-DTN-MAP-01 Section 6.1 (an envelope whose lifetime
    bound is under 1 ms SHALL NOT be encapsulated), applied at ION
    bp_send's whole-second granularity (DOCS/PBS-ION-MAPPING-PROFILE.md
    Section 2).
    Method: T.
    Procedure: build a TTL 3 s envelope whose Timestamp is 0.1 s in the
      past; submit it with the default 2 s submission-latency bound, so at
      c_us between 0 and 0.9 s of TTL remain: unexpired, but less than one
      whole second.
    Pass criteria: submit raises IonLifetimeGranularityError; no spool file
      is written; bpsendfile is not run (node 1's ion.log gains no
      bpsendfile line); node 1's src tally does not change.
    """
    net = open_net
    before = net.lunar_node.bp_tallies()
    spooled = sorted(net.lunar.spool.iterdir())
    sends_before = net.lunar_node.ion_log().count("bpsendfile is running")
    env = PBSLink(device_id="Rover-Alpha", clock_source=lambda: time.time() - 0.1).send(
        Priority.NORMAL, b"UNDER-ONE-SECOND-LEFT", ttl=3
    )
    with pytest.raises(IonLifetimeGranularityError) as info:
        net.lunar.submit(env, net.earth.receive_eid)
    assert sorted(net.lunar.spool.iterdir()) == spooled
    assert net.lunar_node.ion_log().count("bpsendfile is running") == sends_before
    assert net.lunar_node.bp_tallies()["src"] == before["src"]
    evidence["refusal"] = f"{type(info.value).__name__}: {info.value}"


# -----------------------------------------------------------------------
# IT-12  TTL 0 through ION
# -----------------------------------------------------------------------

def test_it12_ttl_zero_envelope_gets_no_expiry_lifetime(open_net, evidence):
    """
    Requirements: PBS-DTN-MAP-01 Section 6.1.1 and PBS-DTN-MAP-02 Section 4
    (TTL 0: the documented no-expiry lifetime, accepted by the bundle
    protocol agent without overflow of creation time + lifetime).
    Method: T.
    Procedure: submit a TTL 0 envelope; capture its bundle; wait for
      delivery.
    Pass criteria: the bundle's lifetime is 2 147 483 647 000 ms (2^31 - 1
      s); ION delivers the envelope byte-identical; node 1's exp tally does
      not rise (ION did not compute an expiration time in the past).
    """
    net = open_net
    exp_before = net.lunar_node.bp_tallies().get("exp", 0)
    env = rover_link().send(Priority.BULK, b"NEVER-EXPIRES", ttl=0)
    net.lunar.submit(env, net.earth.receive_eid)
    deliveries = deliveries_of(net.earth, [env])
    caps = captures_of(net.emulator["1->2"], env)
    assert len(caps) == 1
    _, b = caps[0]
    assert b.lifetime_ms == ION_NO_EXPIRY_LIFETIME_MS == (2**31 - 1) * 1000
    assert len(deliveries) == 1 and deliveries[0].envelope_bytes == env
    assert net.lunar_node.bp_tallies().get("exp", 0) == exp_before
    evidence.update({"lifetime_ms": b.lifetime_ms, "bundle_hex": b.raw.hex()})


# -----------------------------------------------------------------------
# IT-09, IT-10  Contact gap: store-and-forward and expiry in storage
# -----------------------------------------------------------------------

GAP_S = 20


@pytest.fixture(scope="module")
def gap_run(ion_toolchain, run_root):
    """
    Contact planned from start = now + GAP_S for 600 s. Two envelopes are
    submitted at node 1 before start: HELD (TTL 120 s) and SHORT (TTL 6 s,
    which leaves ION a lifetime of about 3 s).
    """
    start = int(time.time()) + GAP_S
    net = LunarEarthNetwork(ion_toolchain, run_root / "contact-gap", [ContactWindow(start, start + 600)])
    net.start()
    try:
        net.earth.start_receiver(0)
        link = rover_link()
        held = link.send(Priority.NORMAL, b"HELD-UNTIL-CONTACT", ttl=120)
        short = link.send(Priority.NORMAL, b"EXPIRES-IN-STORAGE", ttl=6)
        sub_held = net.lunar.submit(held, net.earth.receive_eid)
        sub_short = net.lunar.submit(short, net.earth.receive_eid)
        submitted_before_start = time.time() < start
        deliveries = deliveries_of(net.earth, [held], GAP_S + DELIVERY_TIMEOUT_S)
        deliveries += deliveries_of(net.earth, [short], ABSENCE_WAIT_S)  # must not arrive
        result = {
            "net": net, "start": start, "held": held, "short": short,
            "sub_held": sub_held, "sub_short": sub_short,
            "submitted_before_start": submitted_before_start,
            "deliveries": deliveries,
            "held_caps": captures_of(net.emulator["1->2"], held, timeout_s=0),
            "short_caps": captures_of(net.emulator["1->2"], short, timeout_s=0),
            "lunar_tallies": net.lunar_node.bp_tallies(),
        }
        yield result
    finally:
        net.stop()


def test_it09_bundle_is_stored_until_contact_then_forwarded(gap_run, evidence):
    """
    Requirements: PBS-DTN-MAP-01 Section 9 (store-and-forward: envelopes
    may be stored until DTN contact is available); RFC 4838 Section 3.
    Method: D (demonstration with measured evidence).
    Procedure: with no contact planned for GAP_S seconds, submit a TTL
      120 s envelope; record when its bundle crosses the link.
    Pass criteria:
      1. the envelope was submitted, and its bundle created, before the
         contact start;
      2. the bundle crossed the link at or after the contact start, once;
      3. the envelope was delivered byte-identical, at least one OWLT after
         the contact start.
    """
    r = gap_run
    start_ns = r["start"] * 1_000_000_000
    assert r["submitted_before_start"]
    assert len(r["held_caps"]) == 1
    cap, b = r["held_caps"][0]
    assert b.creation_unix_ms < r["start"] * 1000
    assert cap.arrival_unix_ns >= start_ns
    held = [d for d in r["deliveries"] if d.envelope_bytes == r["held"]]
    assert len(held) == 1
    assert held[0].restored_unix_us * 1000 >= start_ns + int(r["net"].owlt_s * 1e9)
    evidence.update({
        "contact_start_unix_s": r["start"],
        "bundle_created_s_before_start": r["start"] - b.creation_unix_ms / 1000,
        "crossed_link_s_after_start": (cap.arrival_unix_ns - start_ns) / 1e9,
        "delivered_s_after_start": held[0].restored_unix_us / 1e6 - r["start"],
    })


def test_it10_bundle_expires_in_storage_and_is_never_delivered(gap_run, evidence):
    """
    Requirements: PBS-DTN-MAP-01 Section 7.3 (DTN lifetime expiration
    results in envelope discard); RFC 9171 Section 5.5 (bundle deleted
    when its lifetime ends); PBS-ENV-01 Section 12 (expired envelopes are
    not delivered).
    Method: T.
    Procedure: in the same contact gap, submit a TTL 6 s envelope, whose
      bundle lifetime ends before the contact starts.
    Pass criteria: its bundle never crosses the link; it is never
      delivered; node 1's exp tally is at least 1.
    """
    r = gap_run
    assert r["sub_short"].plan.lifespan_s * 1000 < GAP_S * 1000
    assert r["short_caps"] == []
    assert all(d.envelope_bytes != r["short"] for d in r["deliveries"])
    assert r["lunar_tallies"].get("exp", 0) >= 1
    evidence.update({
        "short_lifespan_s": r["sub_short"].plan.lifespan_s,
        "lunar_tallies": r["lunar_tallies"],
    })


# -----------------------------------------------------------------------
# IT-11  Configuration of the item under test
# -----------------------------------------------------------------------

def test_it11_ion_under_test_is_the_pinned_release(ion_toolchain, evidence):
    """
    Requirement: NPR 7150.2D SWE-187 (software under configuration
    management before testing): the results apply to the pinned release.
    Method: I.
    Pass criteria: ionadmin reports ION_VERSION_STRING.
    """
    version = ion_toolchain.version()
    assert version == ION_VERSION_STRING
    evidence["ion_version"] = version


# -----------------------------------------------------------------------
# IT-13  Node lifecycle leaves nothing behind
# -----------------------------------------------------------------------

def test_it13_stopped_network_leaves_no_processes_or_shared_memory(ion_toolchain, run_root, evidence):
    """
    Requirement: test isolation and repeatability (NPR 7150.2D SWE-191,
    regression testing): a stopped network leaves no ION process and no
    shared-memory segment that a later network could attach to.
    Method: T.
    Procedure: start and stop a network; inspect /proc.
    Pass criteria: while running, every node's four segments (wmKey,
      sdrWmKey, heapKey, logKey as used) exist and its daemons run in its
      directory; after stop, no process runs in a node directory and no
      segment with a node's key remains.
    """
    net = LunarEarthNetwork(ion_toolchain, run_root / "lifecycle", always_open(60))
    net.start()
    nodes = list(net.ion.nodes.values())
    try:
        running = {n.number: len(n.processes()) for n in nodes}
        present = {n.number: sorted(k for k in n.keys.values() if k in shm_segments()) for n in nodes}
    finally:
        net.stop()
    assert all(count > 0 for count in running.values())
    assert all(len(keys) >= 2 for keys in present.values())  # at least wm and SDR heap
    assert all(n.processes() == [] for n in nodes)
    remaining = set(shm_segments())
    assert all(k not in remaining for n in nodes for k in n.keys.values())
    evidence.update({"processes_while_running": running, "segments_while_running": present})
