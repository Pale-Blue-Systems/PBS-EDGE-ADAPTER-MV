"""
Unit tests for pbs_ion_demo that do not need ION.

They verify the parts of the end-to-end demonstration whose behavior can be
fixed exactly without a bundle protocol agent: the BPv7 wire decoder used as
the independent check on ION's bundles, the lifetime and class-of-service
selection of the ION gateway, the inbound envelope checks, the ION
configuration the harness writes, and the link emulator's delay and capture.
Test identifiers (UT-nn) are listed in DOCS/PBS-ION-E2E-TEST-PLAN.md.
"""

import struct
import time

import cbor2
import pytest
from PBS_LINK import PBSCRCError, PBSLink, Priority

from pbs_edge_adapter_worked_example import (
    AuthorityContextMap,
    BPv7PayloadBlock,
    BPv7Primary,
    EnvelopeExpiredError,
    EnvelopeLengthError,
    build_bpv7_bundle,
    crc16_x25,
    eid_dtn,
    eid_ipn,
    pbs_to_bpv7_bundle_mv,
)
from pbs_ion_demo.bpv7_wire import (
    BundleFormatError,
    decode_bundle,
    eid_to_text,
    ion_qos,
    item_end,
    reserved_flags_set,
)
from pbs_ion_demo.ion_gateway import (
    ION_BULK,
    ION_EXPEDITED,
    ION_NO_EXPIRY_LIFETIME_MS,
    ION_STANDARD,
    PBS_PRIORITY_TO_ION_COS,
    EnvelopeRestoreError,
    IonLifetimeGranularityError,
    plan_submission,
    restore_envelope,
)
from pbs_ion_demo.ion_node import Contact, IonNode, allocate_keys, ion_utc, shm_segments
from pbs_ion_demo.link_emulator import (
    EARTH_MOON_OWLT_S,
    LinkChannel,
    free_udp_port,
)

# 2026-01-01T00:00:00Z, the instant the worked-example tests use.
T0_S = 1_767_225_600
T0_US = T0_S * 1_000_000

AC_MAP = AuthorityContextMap(
    table={"luna": {"dest": eid_ipn(2, 2), "src": eid_ipn(1, 0), "report_to": eid_ipn(1, 0)}}
)


def envelope(ttl: int, priority: Priority = Priority.NORMAL, payload: bytes = b"VOLTAGE=120.0") -> bytes:
    """Envelope with Timestamp = T0."""
    return PBSLink(device_id="TEST-ROVER", clock_source=lambda: T0_S).send(priority, payload, ttl=ttl)


def bundle_at(now_us: int, ttl: int = 120) -> bytes:
    return pbs_to_bpv7_bundle_mv(envelope(ttl), "luna", AC_MAP, creation_seq=7, clock_us=lambda: now_us)


# -----------------------------
# UT-01 to UT-09: BPv7 wire decoder (RFC 9171 Sections 4.1, 4.2.1, 4.2.2, 4.3)
# -----------------------------

def test_ut01_decoder_reads_worked_example_bundle():
    env = envelope(120)
    raw = pbs_to_bpv7_bundle_mv(env, "luna", AC_MAP, creation_seq=7, clock_us=lambda: T0_US)
    b = decode_bundle(raw)
    assert eid_to_text(b.destination) == "ipn:2.2"
    assert eid_to_text(b.source) == "ipn:1.0"
    assert eid_to_text(b.report_to) == "ipn:1.0"
    assert b.creation_time_ms == T0_S * 1000 - 946_684_800_000
    assert b.creation_unix_ms == T0_S * 1000
    assert b.creation_seq == 7
    assert b.lifetime_ms == 60_000
    assert b.expiry_unix_ms == T0_S * 1000 + 60_000
    assert b.payload == env
    assert [(x.block_type, x.block_number) for x in b.blocks] == [(1, 1)]


def _primary_span(raw: bytes):
    return 1, item_end(raw, 1)


@pytest.mark.parametrize("offset_from_end", [1, 2, 3, 4, 6, 10])
def test_ut02_decoder_rejects_corrupted_primary_block(offset_from_end):
    raw = bytearray(bundle_at(T0_US))
    _, end = _primary_span(bytes(raw))
    raw[end - offset_from_end] ^= 0x01
    with pytest.raises(BundleFormatError):
        decode_bundle(bytes(raw))


def test_ut03_decoder_checks_crc16_canonical_block():
    """A CRC type 1 block verifies, and fails after one bit of its data changes."""
    data = b"\x01\x02\x03"
    zero = cbor2.dumps([7, 2, 0, 1, data, b"\x00\x00"])
    block = cbor2.dumps([7, 2, 0, 1, data, struct.pack("!H", crc16_x25(zero))])
    raw = bytes(bundle_at(T0_US))
    p_start, p_end = _primary_span(raw)
    bundle = raw[:p_end] + block + raw[p_end:]
    b = decode_bundle(bundle)
    assert [x.block_type for x in b.blocks] == [7, 1]
    bad = bytearray(bundle)
    bad[p_end + block.index(data) + 2] ^= 0x01
    with pytest.raises(BundleFormatError, match="CRC mismatch"):
        decode_bundle(bytes(bad))


def test_ut04_crc16_x25_check_value():
    """CRC-16/X-25 check value for "123456789" is 0x906E (RFC 9171 Section 4.2.1)."""
    assert crc16_x25(b"123456789") == 0x906E


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda r: r[1:], "indefinite-length array"),
        (lambda r: r + b"\x00", "follow the bundle"),
        (lambda r: r[:-1], "break code"),
    ],
)
def test_ut05_decoder_rejects_malformed_framing(mutate, message):
    with pytest.raises(BundleFormatError, match=message):
        decode_bundle(mutate(bundle_at(T0_US)))


def test_ut06_decoder_rejects_fragment_and_wrong_version():
    for version, flags, message in ((6, 0, "version"), (7, 0x01, "fragment")):
        prim = [version, flags, 0, eid_ipn(2, 2), eid_ipn(1, 0), eid_ipn(1, 0), [1, 0], 1000]
        raw = b"\x9f" + cbor2.dumps(prim) + cbor2.dumps([1, 1, 0, 0, b"x"]) + b"\xff"
        with pytest.raises(BundleFormatError, match=message):
            decode_bundle(raw)


def test_ut07_decoder_requires_payload_block_last():
    raw = bundle_at(T0_US)
    _, p_end = _primary_span(raw)
    extra = cbor2.dumps([7, 2, 0, 0, b"\x00"])
    with pytest.raises(BundleFormatError, match="payload block"):
        decode_bundle(raw[:-1] + extra + b"\xff")


def test_ut08_ion_qos_block_decoding():
    """ION QoS block (type 193): [flags, class of service, ordinal, data label]."""
    raw = bundle_at(T0_US)
    _, p_end = _primary_span(raw)
    qos = cbor2.dumps([193, 3, 1, 0, cbor2.dumps([0, 2, 0, 0])])
    b = decode_bundle(raw[:p_end] + qos + raw[p_end:])
    assert ion_qos(b) == {"flags": 0, "class_of_service": 2, "ordinal": 0, "data_label": 0}
    assert ion_qos(decode_bundle(raw)) is None


def test_ut09_reserved_flag_detection_and_eid_text():
    prim = BPv7Primary(eid_ipn(2, 2), eid_ipn(1, 0), eid_ipn(1, 0), 1, 0, 1000, bundle_proc_flags=0x40)
    b = decode_bundle(build_bpv7_bundle(prim, BPv7PayloadBlock(b"x")))
    assert reserved_flags_set(b) == 0
    assert eid_to_text(eid_dtn("none")) == "dtn:none"
    assert eid_to_text(eid_dtn("//a.example/")) == "dtn://a.example/"
    assert eid_to_text([2, [977000, 1, 2]]) == "ipn:977000.1.2"


# -----------------------------
# UT-10 to UT-17: ION gateway lifetime and class of service
# (PBS-DTN-MAP-01 Sections 6.1, 6.1.1, 6.3)
# -----------------------------

def test_ut10_lifetime_uses_clock_plus_submit_latency():
    """
    TTL 120 s, clock at Timestamp, latency bound 2 s: the Section 6.1 bound
    at c_us = clock + 2 s is 118 000 ms, so ION is asked for 118 s.
    """
    p = plan_submission(envelope(120), T0_US, max_submit_latency_us=2_000_000)
    assert p.c_us == T0_US + 2_000_000
    assert p.lifetime_ms_bound == 118_000
    assert p.lifespan_s == 118
    assert p.lifetime_ms == 118_000


def test_ut11_lifetime_is_floored_to_whole_seconds():
    """Bound 117 499 ms (age 0.501 s + 2 s latency) gives 117 s, never 118 s."""
    p = plan_submission(envelope(120), T0_US + 501_000, max_submit_latency_us=2_000_000)
    assert p.lifetime_ms_bound == 117_499
    assert p.lifespan_s == 117


@pytest.mark.parametrize("age_us", [0, 1, 999_999, 30_000_000, 117_000_000])
def test_ut12_ion_lifetime_never_exceeds_envelope_expiry(age_us):
    """
    For any creation time c not later than c_us: c + lifespan_s * 1000 ms is
    not later than Timestamp + TTL (PBS-DTN-MAP-01 Section 6.1).
    """
    latency = 2_000_000
    p = plan_submission(envelope(120), T0_US + age_us, max_submit_latency_us=latency)
    latest_creation_ms = (T0_US + age_us + latency) // 1000
    assert latest_creation_ms + p.lifetime_ms <= T0_S * 1000 + 120_000


def test_ut13_less_than_one_second_left_is_refused():
    with pytest.raises(IonLifetimeGranularityError):
        plan_submission(envelope(3), T0_US + 500_000, max_submit_latency_us=2_000_000)
    # Exactly 1 s left at c_us is accepted.
    assert plan_submission(envelope(3), T0_US, max_submit_latency_us=2_000_000).lifespan_s == 1


def test_ut14_expired_envelope_is_refused():
    with pytest.raises(EnvelopeExpiredError):
        plan_submission(envelope(10), T0_US + 10_000_001, max_submit_latency_us=0)


def test_ut15_ttl_zero_gets_ion_no_expiry_lifetime():
    """
    TTL 0: 2 147 483 647 s = 2^31 - 1, the largest value of bp_send's int
    lifespan; within the 4 294 967 295 000 ms limit of Section 6.1.1. The
    largest TTL is capped to the same value, since bp_send cannot express
    more; smaller TTLs are not capped.
    """
    p = plan_submission(envelope(0), T0_US)
    assert ION_NO_EXPIRY_LIFETIME_MS == (2**31 - 1) * 1000
    assert ION_NO_EXPIRY_LIFETIME_MS <= 4_294_967_295_000
    assert p.lifespan_s == 2**31 - 1
    assert plan_submission(envelope(4_294_967_295), T0_US, max_submit_latency_us=0).lifespan_s == 2**31 - 1
    assert plan_submission(envelope(2**31 - 2), T0_US, max_submit_latency_us=0).lifespan_s == 2**31 - 2


def test_ut16_priority_to_ion_class_follows_section_6_3_table():
    expected = {
        Priority.CRITICAL: ION_EXPEDITED,
        Priority.HIGH: ION_EXPEDITED,
        Priority.NORMAL: ION_STANDARD,
        Priority.LOW: ION_BULK,
        Priority.BULK: ION_BULK,
    }
    assert PBS_PRIORITY_TO_ION_COS == expected
    for prio, cos in expected.items():
        assert plan_submission(envelope(60, prio), T0_US).class_of_service == cos
    # No class is more favorable than that of any higher-priority class.
    order = [PBS_PRIORITY_TO_ION_COS[p] for p in sorted(expected)]
    assert order == sorted(order, reverse=True)


def test_ut17_invalid_envelopes_and_arguments_are_refused():
    env = bytearray(envelope(60))
    env[0x28] ^= 0xFF  # header CRC32 byte
    with pytest.raises(PBSCRCError):
        plan_submission(bytes(env), T0_US)
    with pytest.raises(EnvelopeLengthError):
        plan_submission(envelope(60) + b"\x00", T0_US)
    with pytest.raises(ValueError):
        plan_submission(envelope(60), T0_US, max_submit_latency_us=-1)
    with pytest.raises(ValueError):
        plan_submission(envelope(60), T0_US, no_expiry_lifetime_ms=ION_NO_EXPIRY_LIFETIME_MS + 1)


# -----------------------------
# UT-18, UT-19: inbound envelope checks (PBS-DTN-MAP-01 Sections 7.2, 7.3)
# -----------------------------

def test_ut18_restore_returns_valid_envelope_unmodified():
    env = envelope(60, Priority.CRITICAL, bytes(range(256)))
    restored = restore_envelope(env, T0_US + 60_000_000)
    assert restored.priority == Priority.CRITICAL
    assert restored.payload == bytes(range(256))
    assert restored.ttl == 60


def test_ut19_restore_rejects_expired_or_corrupt_envelope():
    with pytest.raises(EnvelopeRestoreError):
        restore_envelope(envelope(60), T0_US + 60_000_001)
    assert restore_envelope(envelope(0), T0_US + 10**15).ttl == 0  # TTL 0 never expires
    bad = bytearray(envelope(60))
    bad[0x10] ^= 0x01  # Timestamp byte, covered by the header CRC32
    with pytest.raises(PBSCRCError):
        restore_envelope(bytes(bad), T0_US)


# -----------------------------
# UT-20, UT-21: ION configuration written by the harness
# -----------------------------

def test_ut20_ion_utc_format():
    assert ion_utc(T0_S) == "2026/01/01-00:00:00"
    assert ion_utc(T0_S + 3661) == "2026/01/01-01:01:01"


def test_ut21_node_configuration_files(tmp_path):
    keys = {"wmKey": 0x10000001, "sdrWmKey": 0x10000002, "heapKey": 0x10000003, "logKey": 0x10000004}
    node = IonNode(1, tmp_path, 40001, {2: 40003}, keys, "pbsion1")
    contact = Contact(1, 2, T0_S, T0_S + 600, 125_000, 2)
    files = node.render([contact])
    cfg = files["node.ionconfig"].splitlines()
    assert cfg[:2] == [f"wmKey {0x10000001}", "sdrName pbsion1"]
    assert {f"sdrWmKey {0x10000002}", f"heapKey {0x10000003}", f"logKey {0x10000004}"} <= set(cfg)
    assert "a contact 2026/01/01-00:00:00 2026/01/01-00:10:00 1 2 125000" in files["node.ionrc"]
    assert "a range 2026/01/01-00:00:00 2026/01/01-00:10:00 1 2 2" in files["node.ionrc"]
    bprc = files["node.bprc"].splitlines()
    assert bprc[0] == "1" and bprc[-1] == "s"
    assert {"a endpoint ipn:1.0 q", "a endpoint ipn:1.1 q", "a endpoint ipn:1.2 q"} <= set(bprc)
    assert "a induct udp 127.0.0.1:40001 udpcli" in bprc
    assert "a outduct udp 127.0.0.1:40003 udpclo" in bprc
    assert files["node.ipnrc"] == "a plan 2 udp/127.0.0.1:40003\n"


# -----------------------------
# UT-22, UT-23: link emulator
# -----------------------------

def test_ut22_earth_moon_owlt():
    """384 400 km / 299 792 458 m/s = 1.2822 s."""
    assert EARTH_MOON_OWLT_S == pytest.approx(1.28222, abs=1e-5)


def test_ut23_channel_delays_and_captures_in_order():
    import socket

    target = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target.bind(("127.0.0.1", 0))
    target.settimeout(5)
    owlt = 0.25
    ch = LinkChannel("test", free_udp_port(), target.getsockname()[1], owlt).start()
    try:
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        t0 = time.monotonic()
        sender.sendto(b"first", ("127.0.0.1", ch.listen_port))
        sender.sendto(b"second", ("127.0.0.1", ch.listen_port))
        got = [target.recvfrom(100)[0] for _ in range(2)]
        elapsed = time.monotonic() - t0
        ch.inject(b"third")  # after the first two are released, so order is fixed
        got.append(target.recvfrom(100)[0])
        caps = ch.wait_for_captures(3, 5)
    finally:
        ch.stop()
        target.close()
    assert got == [b"first", b"second", b"third"]
    assert elapsed >= owlt
    assert [c.data for c in caps] == got
    assert [c.injected for c in caps] == [False, False, True]
    assert all(c.release_unix_ns - c.arrival_unix_ns >= int(owlt * 1e9) for c in caps)


# -----------------------------
# UT-24: pinned ION release
# -----------------------------

def test_ut24_release_pin_matches_build_script():
    """pbs_ion_demo/ion_release.py and scripts/ion-release.env name the same release."""
    from pathlib import Path

    from pbs_ion_demo import ion_release

    env = dict(
        line.split("=", 1)
        for line in (Path(__file__).resolve().parents[1] / "scripts" / "ion-release.env").read_text().splitlines()
        if line and not line.startswith("#")
    )
    assert env["ION_REPOSITORY"] == ion_release.ION_REPOSITORY
    assert env["ION_RELEASE_TAG"] == ion_release.ION_RELEASE_TAG
    assert env["ION_RELEASE_COMMIT"] == ion_release.ION_RELEASE_COMMIT
    assert len(ion_release.ION_RELEASE_COMMIT) == 40


# -----------------------------
# UT-25: shared-memory keys
# -----------------------------

def test_ut25_allocated_keys_are_distinct_and_unused():
    existing = set(shm_segments())
    exclude = {0x10000000 + i for i in range(1000)}
    keys = allocate_keys(("wmKey", "sdrWmKey", "heapKey", "logKey"), exclude)
    values = list(keys.values())
    assert sorted(keys) == ["heapKey", "logKey", "sdrWmKey", "wmKey"]
    assert len(set(values)) == 4
    assert not (set(values) & (existing | exclude))
    assert all(0x10000000 <= v < 0x70000000 for v in values)
