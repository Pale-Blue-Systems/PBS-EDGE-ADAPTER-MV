"""
Validation tests for pbs_edge_adapter_worked_example.py.

Envelopes are built by PBS_LINK with the Timestamp fixed at T0
(2026-01-01T00:00:00Z) and the adapter clock is injected, so every
creation time and lifetime below is an exact value.
"""

import calendar
import struct

import cbor2
import pytest
from PBS_LINK import (
    HEADER_SIZE,
    PBSCRCError,
    PBSLink,
    PBSValidationError,
    Priority,
    build_envelope,
)

from pbs_edge_adapter_worked_example import (
    DTN_EPOCH_UNIX_MS,
    AuthorityContextMap,
    BPv7PayloadBlock,
    BPv7Primary,
    EnvelopeExpiredError,
    EnvelopeLengthError,
    build_bpv7_bundle,
    crc32c,
    eid_dtn,
    eid_ipn,
    is_source_node_id,
    pbs_to_bpv7_bundle_mv,
    unix_us_to_dtn_ms,
)

# 2026-01-01T00:00:00Z in Unix time (the instant PBS-ENV-01 Section 13.2 uses).
T0_S = 1_767_225_600
T0_US = T0_S * 1_000_000

DEFAULT_LIFETIME_MS = 60_000

AC_MAP = AuthorityContextMap(
    table={
        "pbsf.luna.ops": {
            "dest": eid_dtn("//pbsf.example/luna/ops"),
            "src": eid_dtn("//edge-17.pbsf.example/"),
            "report_to": eid_dtn("//pbsf.example/ops/reports"),
        }
    }
)


def make_envelope(ttl: int, payload: bytes = b"VOLTAGE=120.0") -> bytes:
    """PBS-ENV-01 v1.3 envelope from PBS_LINK with Timestamp = T0_US."""
    link = PBSLink(device_id="TEST-ROVER", clock_source=lambda: T0_S)
    return link.send(Priority.NORMAL, payload, ttl=ttl)


def encapsulate(
    envelope_bytes: bytes,
    now_us: int,
    creation_seq: int = 42,
    default_lifetime_ms: int = DEFAULT_LIFETIME_MS,
) -> bytes:
    return pbs_to_bpv7_bundle_mv(
        envelope_bytes,
        "pbsf.luna.ops",
        AC_MAP,
        default_lifetime_ms=default_lifetime_ms,
        creation_seq=creation_seq,
        clock_us=lambda: now_us,
    )


def _recompute_primary_crc32c(primary_list) -> bytes:
    """
    Recompute CRC32C for a BPv7 primary block CBOR array (RFC 9171 Section
    4.3.1), assuming crc_type == 2 and a 4-byte CRC field.
    """
    assert primary_list[2] == 2, "Test expects CRC32C primary block (crc_type=2)"
    assert isinstance(primary_list[-1], (bytes, bytearray)) and len(primary_list[-1]) == 4

    prim_zero = list(primary_list)
    prim_zero[-1] = b"\x00\x00\x00\x00"
    return struct.pack("!I", crc32c(cbor2.dumps(prim_zero)))


# -----------------------------
# Bundle structure (RFC 9171 Sections 4.1, 4.3.1, 4.3.2)
# -----------------------------

def test_bpv7_bundle_primary_crc_and_payload_roundtrip():
    dest, src, rpt = AC_MAP.resolve("pbsf.luna.ops")

    pbs_binary_envelope = build_envelope(
        source_id="TEST-ROVER",
        priority=2,
        payload="VOLTAGE=120.0",
        ttl=120,
        sequence=1,
    )

    primary = BPv7Primary(
        destination=dest,
        source=src,
        report_to=rpt,
        creation_time_dtn=123456,   # fixed
        creation_seq=42,            # fixed
        lifetime_ms=120_000,
        bundle_proc_flags=0,
        crc_type=2,                 # CRC32C
    )
    payload_block = BPv7PayloadBlock(payload=pbs_binary_envelope, crc_type=0)

    bundle_bytes = build_bpv7_bundle(primary, payload_block)

    # Bundle: CBOR indefinite-length array, primary block first, payload block last.
    assert bundle_bytes[0] == 0x9F and bundle_bytes[-1] == 0xFF
    decoded = cbor2.loads(bundle_bytes)
    assert isinstance(decoded, list)
    assert len(decoded) >= 2, "Bundle must contain at least primary block and payload block"

    primary_block = decoded[0]
    payload_block_decoded = decoded[-1]

    # Primary block: 9 items for a non-fragment bundle with a CRC:
    # [version, flags, crc_type, dest, src, rpt, creation_ts, lifetime, crc]
    assert isinstance(primary_block, list)
    assert len(primary_block) == 9

    version, flags, crc_type, dest_eid, src_eid, rpt_eid, creation_ts, lifetime_ms, crc_field = primary_block

    assert version == 7
    assert isinstance(flags, int)
    assert crc_type == 2
    assert dest_eid == dest
    assert src_eid == src
    assert rpt_eid == rpt
    assert isinstance(creation_ts, list) and creation_ts == [123456, 42]
    assert lifetime_ms == 120_000
    assert isinstance(crc_field, (bytes, bytearray)) and len(crc_field) == 4

    # Primary block CRC32C is correct.
    assert bytes(crc_field) == _recompute_primary_crc32c(primary_block)

    # Payload block: [block_type=1, block_number=1, block_flags, crc_type=0, payload]
    assert isinstance(payload_block_decoded, list)
    assert len(payload_block_decoded) == 5
    assert payload_block_decoded[0] == 1  # payload block type
    assert payload_block_decoded[1] == 1  # block number
    assert isinstance(payload_block_decoded[2], int)  # block flags
    assert payload_block_decoded[3] == 0  # payload block CRC type
    assert payload_block_decoded[4] == pbs_binary_envelope


@pytest.mark.parametrize(
    "data, crc_lsb_first",
    [
        (bytes(32), "aa36918a"),
        (b"\xff" * 32, "43aba862"),
        (bytes(range(32)), "4e79dd46"),
        (bytes(range(31, -1, -1)), "5cdb3f11"),
        # iSCSI SCSI Read (10) Command PDU, 48 bytes.
        (
            bytes.fromhex(
                "01c00000" + "00" * 12 + "14000000" + "00000400" + "00000014"
                + "00000018" + "28000000" + "00" * 4 + "02000000" + "00" * 4
            ),
            "563a96d9",
        ),
    ],
)
def test_crc32c_matches_rfc7143_examples(data, crc_lsb_first):
    # RFC 9171 Section 4.2.1 refers to RFC 7143 Appendix A.4 for CRC32C
    # examples; this list holds all five. RFC 7143 lists each CRC least
    # significant byte first.
    assert crc32c(data).to_bytes(4, "little") == bytes.fromhex(crc_lsb_first)


def test_converted_bundle_primary_block_and_crc():
    envelope = make_envelope(ttl=0)
    primary_block = cbor2.loads(encapsulate(envelope, now_us=T0_US + 1_000_000))[0]

    dest, src, rpt = AC_MAP.resolve("pbsf.luna.ops")
    assert primary_block[:6] == [7, 0, 2, dest, src, rpt]
    assert bytes(primary_block[8]) == _recompute_primary_crc32c(primary_block)


# -----------------------------
# Creation time: DTN milliseconds (RFC 9171 Sections 4.2.6, 4.2.7)
# -----------------------------

def test_dtn_epoch_offset():
    assert calendar.timegm((2000, 1, 1, 0, 0, 0, 0, 0, 0)) * 1000 == DTN_EPOCH_UNIX_MS
    assert DTN_EPOCH_UNIX_MS == 946_684_800_000


def test_creation_time_is_dtn_milliseconds():
    # Clock: 2026-01-01T00:00:01.234567Z. DTN time truncates to whole ms:
    # 1_767_225_601_234 ms Unix - 946_684_800_000 ms = 820_540_801_234 ms.
    bundle = encapsulate(make_envelope(ttl=0), now_us=T0_US + 1_234_567, creation_seq=42)
    assert cbor2.loads(bundle)[0][6] == [820_540_801_234, 42]


def test_negative_creation_seq_is_rejected():
    # RFC 9171 Section 4.2.7: the sequence number is a CBOR unsigned integer.
    with pytest.raises(ValueError):
        encapsulate(make_envelope(ttl=0), now_us=T0_US, creation_seq=-1)
    assert cbor2.loads(encapsulate(make_envelope(ttl=0), now_us=T0_US, creation_seq=0))[0][6][1] == 0


def test_clock_at_or_before_dtn_epoch_is_rejected():
    with pytest.raises(ValueError):
        unix_us_to_dtn_ms(DTN_EPOCH_UNIX_MS * 1000)
    assert unix_us_to_dtn_ms(DTN_EPOCH_UNIX_MS * 1000 + 1000) == 1


# -----------------------------
# Lifetime (PBS-DTN-MAP-01 Sections 6.1 and 6.1.1; PBS-DTN-MAP-02 Section 4;
# PBS-ENV-01 Section 12)
# -----------------------------

def lifetime_of(ttl: int, age_us: int, default_lifetime_ms: int = DEFAULT_LIFETIME_MS) -> int:
    bundle = encapsulate(
        make_envelope(ttl), now_us=T0_US + age_us, default_lifetime_ms=default_lifetime_ms
    )
    return cbor2.loads(bundle)[0][7]


def test_ttl_zero_uses_configured_default():
    # TTL 0 never expires (PBS-ENV-01 Section 12.1), even ten days after creation.
    assert lifetime_of(ttl=0, age_us=10 * 86_400 * 1_000_000) == DEFAULT_LIFETIME_MS


def test_ttl_shorter_than_default_bounds_lifetime():
    assert lifetime_of(ttl=30, age_us=0) == 30_000


def test_default_shorter_than_ttl_bounds_lifetime():
    assert lifetime_of(ttl=3600, age_us=0) == DEFAULT_LIFETIME_MS


def test_partially_aged_envelope_gets_remaining_ttl():
    # Age 12.5005 s rounds up to 12 501 ms; 30 000 - 12 501 = 17 499 ms.
    assert lifetime_of(ttl=30, age_us=12_500_500) == 17_499
    assert lifetime_of(ttl=30, age_us=29_999_000) == 1


@pytest.mark.parametrize(
    "age_us",
    [
        30_000_001,     # age > TTL: expired (PBS-ENV-01 Section 12.2)
        3_600_000_000,  # long expired
        30_000_000,     # age == TTL: 0 ms remain
        29_999_001,     # 999 us remain: less than 1 ms
    ],
)
def test_expired_envelope_is_rejected(age_us):
    with pytest.raises(EnvelopeExpiredError):
        encapsulate(make_envelope(ttl=30), now_us=T0_US + age_us)


def test_timestamp_ahead_of_adapter_clock_gives_age_zero():
    # Source clock 1 h ahead of the adapter clock: the age is taken as 0, so
    # the lifetime is the TTL, not TTL + 1 h.
    assert lifetime_of(ttl=30, age_us=-3_600_000_000) == 30_000


@pytest.mark.parametrize("default_lifetime_ms", [0, -1])
def test_non_positive_default_lifetime_is_rejected(default_lifetime_ms):
    with pytest.raises(ValueError):
        pbs_to_bpv7_bundle_mv(
            make_envelope(ttl=30),
            "pbsf.luna.ops",
            AC_MAP,
            default_lifetime_ms=default_lifetime_ms,
            clock_us=lambda: T0_US,
        )


def test_no_expiry_lifetime_is_at_most_4294967295000_ms():
    # PBS-DTN-MAP-01 Section 6.1.1 and PBS-DTN-MAP-02 Section 4: the
    # no-expiry lifetime does not exceed 4 294 967 295 000 ms, the largest
    # TTL (4 294 967 295 s) in milliseconds.
    assert lifetime_of(ttl=0, age_us=0, default_lifetime_ms=4_294_967_295_000) == 4_294_967_295_000
    for ttl in (0, 30):
        with pytest.raises(ValueError):
            lifetime_of(ttl, age_us=0, default_lifetime_ms=4_294_967_296_000)


@pytest.mark.parametrize("default_lifetime_ms", [1, DEFAULT_LIFETIME_MS, 4_294_967_295_000])
def test_ttl_zero_lifetime_is_not_less_than_any_finite_ttl_lifetime(default_lifetime_ms):
    # PBS-DTN-MAP-01 Section 6.1.1: the no-expiry lifetime is not less than
    # the lifetime the gateway assigns to any envelope with TTL > 0.
    ttl_zero_lifetime = lifetime_of(ttl=0, age_us=0, default_lifetime_ms=default_lifetime_ms)
    for ttl in (1, 30, 3600, 86_400, 4_294_967_295):
        for age_us in (-3_600_000_000, 0, 500_000):
            assert lifetime_of(ttl, age_us, default_lifetime_ms) <= ttl_zero_lifetime


@pytest.mark.parametrize("age_us", [0, 1, 999, 1_000, 12_500_500, 29_000_001, 29_999_000])
def test_bundle_expiry_never_exceeds_pbs_expiry(age_us):
    ttl = 30
    primary_block = cbor2.loads(encapsulate(make_envelope(ttl), now_us=T0_US + age_us))[0]
    creation_ms, _ = primary_block[6]
    bundle_expiry_dtn_ms = creation_ms + primary_block[7]
    pbs_expiry_dtn_ms = (T0_US + ttl * 1_000_000) // 1000 - DTN_EPOCH_UNIX_MS
    assert bundle_expiry_dtn_ms <= pbs_expiry_dtn_ms
    assert pbs_expiry_dtn_ms - bundle_expiry_dtn_ms <= 1


# -----------------------------
# Envelope validation (PBS-ENV-01 Sections 4, 13, 14)
# -----------------------------

@pytest.mark.parametrize(
    "offset",
    [
        0x08,  # Source ID
        0x18,  # Timestamp
        0x24,  # TTL
        0x28,  # CRC32 field
    ],
)
def test_corrupted_header_crc_is_rejected(offset):
    corrupted = bytearray(make_envelope(ttl=30))
    corrupted[offset] ^= 0x01
    with pytest.raises(PBSCRCError):
        encapsulate(bytes(corrupted), now_us=T0_US)


def test_trailing_bytes_are_rejected():
    with pytest.raises(EnvelopeLengthError):
        encapsulate(make_envelope(ttl=30) + b"\x00", now_us=T0_US)


def test_truncated_envelope_is_rejected():
    with pytest.raises(PBSValidationError):
        encapsulate(make_envelope(ttl=30)[:-1], now_us=T0_US)


# -----------------------------
# Payload block carries the envelope (PBS-DTN-MAP-01 Section 6.2)
# -----------------------------

def test_payload_block_bytes_equal_envelope_bytes():
    envelope = make_envelope(ttl=30, payload=bytes(range(256)))
    assert len(envelope) == HEADER_SIZE + 256
    payload_block = cbor2.loads(encapsulate(envelope, now_us=T0_US + 5_000_000))[-1]
    assert payload_block[:4] == [1, 1, 0, 0]
    assert payload_block[4] == envelope


def test_identical_inputs_give_identical_bundles():
    envelope = make_envelope(ttl=30)
    assert encapsulate(envelope, now_us=T0_US + 7) == encapsulate(envelope, now_us=T0_US + 7)


# -----------------------------
# Authority Context map and source node ID (RFC 9171 Sections 4.2.3,
# 4.2.5.1.1, 4.3.1; RFC 9758 Sections 3.4.1, 5.2, 5.3)
# -----------------------------

def test_unknown_authority_context_is_rejected():
    with pytest.raises(KeyError):
        pbs_to_bpv7_bundle_mv(
            make_envelope(ttl=30), "pbsf.unknown", AC_MAP, clock_us=lambda: T0_US
        )


@pytest.mark.parametrize(
    "eid, expected",
    [
        (eid_dtn("//edge-17.pbsf.example/"), True),        # empty demux (RFC 9171 Section 4.2.5.1.1)
        (eid_ipn(4017, 0), True),                           # administrative endpoint
        (eid_ipn(4001, 99), True),                          # any ipn EID (RFC 9758 Section 5.3)
        (eid_dtn("none"), True),                            # null endpoint
        (eid_ipn(0, 0), True),                              # null endpoint (RFC 9758 Section 5.2)
        (eid_dtn("//pbsf.example/edge/node-17"), False),   # non-empty demux (RFC 9171 Section 4.2.5.1.1)
        (eid_dtn("//pbsf.example/~ops"), False),            # non-empty demux, non-singleton endpoint
        (eid_dtn("//edge-17.pbsf.example"), False),         # no name delimiter
        (eid_ipn(0, 5), False),                             # RFC 9758 Section 3.4.1
        (eid_ipn(0xFFFFFFFF, 1), False),                    # LocalNode (RFC 9758 Section 5.4)
        (eid_ipn(2**32, 0), False),                         # invalid node number (RFC 9758 Section 9.2)
        ([2, [4001]], False),                               # malformed ipn SSP
    ],
)
def test_source_node_id_rule(eid, expected):
    assert is_source_node_id(eid) is expected


@pytest.mark.parametrize("bad_src", ["//pbsf.example/edge/node-17", "//pbsf.example/~ops"])
def test_map_rejects_dtn_source_with_non_empty_demux(bad_src):
    with pytest.raises(ValueError):
        AuthorityContextMap(
            table={
                "bad": {
                    "dest": eid_dtn("//pbsf.example/luna/ops"),
                    "src": eid_dtn(bad_src),
                    "report_to": eid_dtn("//pbsf.example/ops/reports"),
                }
            }
        )


def test_map_accepts_pbs_dtn_map_01_example_source_eid():
    # PBS-DTN-MAP-01 Section 8 maps "Rover-Alpha" to ipn:99.1.
    ac_map = AuthorityContextMap(
        table={"a": {"dest": eid_ipn(1, 1), "src": eid_ipn(99, 1), "report_to": eid_ipn(99, 1)}}
    )
    assert ac_map.resolve("a")[1] == [2, [99, 1]]


@pytest.mark.parametrize("null_src", [eid_dtn("none"), eid_ipn(0, 0)])
def test_null_source_sets_must_not_fragment_flag(null_src):
    # RFC 9171 Section 4.2.3: with a null source, "Bundle must not be
    # fragmented" (0x04) MUST be 1 and every status report request flag 0.
    ac_map = AuthorityContextMap(
        table={"anon": {"dest": eid_ipn(4001, 10), "src": null_src, "report_to": eid_dtn("none")}}
    )
    bundle = pbs_to_bpv7_bundle_mv(
        make_envelope(ttl=30), "anon", ac_map, clock_us=lambda: T0_US
    )
    primary_block = cbor2.loads(bundle)[0]
    assert primary_block[1] == 0x04
    assert primary_block[4] == null_src
