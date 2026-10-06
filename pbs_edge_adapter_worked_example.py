"""
PBS-EDGE-ADAPTER-MV worked example: PBS envelope to BPv7 bundle.

pbs_to_bpv7_bundle_mv() converts one PBS-ENV-01 v1.3 envelope into one
Bundle Protocol Version 7 bundle (IETF RFC 9171):

  1. Parse the envelope with PBS_LINK.parse_envelope, which rejects a magic
     byte other than 0x10, a header CRC32 mismatch, a reserved priority
     (5-255) and a payload shorter than the Size field (PBS-ENV-01 Sections
     13 and 14). Reject input longer than 44 + Size bytes.
  2. Reject an envelope whose TTL has expired or has less than 1 ms left.
     Bound the bundle lifetime by the TTL that remains; for TTL 0 use the
     configured no-expiry lifetime (PBS-ENV-01 Section 12; PBS-DTN-MAP-01
     Sections 6.1 and 6.1.1; PBS-DTN-MAP-02 Section 4).
  3. Take the destination EID, source node ID and report-to EID from the
     Authority Context map entry named by the caller.
  4. Build the primary block (RFC 9171 Section 4.3.1): creation time in DTN
     milliseconds (Sections 4.2.6, 4.2.7) and a CRC32C (Sections 4.2.1,
     4.2.2).
  5. Place the complete envelope, header and payload, unmodified in the
     payload block (RFC 9171 Section 4.3.2; PBS-DTN-MAP-01 Section 6.2).

Dependencies: cbor2 and PBS_LINK (pip distribution "pbs-link"; import
package "PBS_LINK").
"""

from __future__ import annotations

import datetime
import struct
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Tuple, Union

import cbor2
from PBS_LINK import HEADER_SIZE, PBSEnvelope, Priority, build_envelope, parse_envelope


# -----------------------------
# CRC utilities (RFC 9171 Section 4.2.1)
# -----------------------------

def _crc32c_table() -> list[int]:
    """
    CRC32C (Castagnoli) reflected table using polynomial 0x82F63B78.
    Produces CRC-32C with init=0xFFFFFFFF, xorout=0xFFFFFFFF, refin/refout=True.
    """
    poly = 0x82F63B78
    table: list[int] = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ poly if (crc & 1) else (crc >> 1)
        table.append(crc & 0xFFFFFFFF)
    return table


_CRC32C_TABLE = _crc32c_table()


def crc32c(data: bytes) -> int:
    """Return the CRC32C of data as an unsigned 32-bit integer."""
    crc = 0xFFFFFFFF
    for b in data:
        crc = _CRC32C_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF


def crc16_x25(data: bytes) -> int:
    """
    CRC-16/X-25, the "standard X-25 CRC-16" of RFC 9171 Section 4.2.1:
      poly=0x1021 (reflected 0x8408), init=0xFFFF, refin/refout=True, xorout=0xFFFF.
    Returns the CRC as an unsigned 16-bit integer.
    """
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if (crc & 0x0001) else (crc >> 1)
    crc ^= 0xFFFF
    return crc & 0xFFFF


# -----------------------------
# BPv7 EID encoding (RFC 9171 Sections 4.2.5.1, 9.6)
# -----------------------------

EID = list[Union[int, str, list[int]]]


def eid_dtn(ssp: str) -> EID:
    """
    Encode a dtn-scheme EID as [1, SSP] (URI scheme code 1, RFC 9171 Section 9.6).

    ssp is the scheme-specific part, without "dtn:". The SSP is a CBOR text
    string, except that "none" (the null endpoint) is the unsigned integer 0
    (RFC 9171 Section 4.2.5.1.1).
    """
    if ssp == "none":
        return [1, 0]
    return [1, ssp]


def eid_ipn(node_num: int, service_num: int) -> EID:
    """
    Encode an ipn-scheme EID as [2, [node_num, service_num]]
    (URI scheme code 2, RFC 9171 Sections 4.2.5.1.2 and 9.6).
    """
    return [2, [int(node_num), int(service_num)]]


def is_null_endpoint(eid: EID) -> bool:
    """
    Return True for the null endpoint: dtn:none, encoded [1, 0] (RFC 9171
    Section 4.2.5.1.1), or ipn:0.0, encoded [2, [0, 0]] (RFC 9758 Section 5.2).
    """
    return eid == [1, 0] or eid == [2, [0, 0]]


def is_source_node_id(eid: EID) -> bool:
    """
    Return True if eid may occupy the primary block's Source node ID field.

    Accepted:
      - the null endpoint, dtn:none or ipn:0.0 (RFC 9171 Section 4.3.1;
        RFC 9758 Section 5.2);
      - a dtn EID "dtn://node-name/" with a non-empty node-name and an
        empty demux (RFC 9171 Section 4.2.5.1.1);
      - an ipn EID [2, [node, service]] of non-negative integers with a node
        number below 0xFFFFFFFF (RFC 9758 Section 5.3).
    Rejected: a dtn EID with a non-empty demux (RFC 9171 Section 4.2.5.1.1:
    "No dtn-scheme endpoint ID for which the demux is of non-zero length
    may do so"), a dtn EID without the "/" after node-name, ipn:0.N with N
    non-zero (RFC 9758 Section 3.4.1: MUST NOT be composed), the LocalNode
    node number 0xFFFFFFFF (RFC 9758 Section 5.4: a bundle with a LocalNode
    source MUST NOT leave the local node), a node number of 2^32 or more
    (invalid for the default allocator, RFC 9758 Section 9.2), and anything
    else.

    RFC 9758 Section 5.3, which updates RFC 9171, allows any ipn EID of the
    node as the source node ID of bundles the node creates.
    """
    if not isinstance(eid, list) or len(eid) != 2:
        return False
    scheme, ssp = eid
    if scheme == 1:
        if ssp == 0:
            return True
        if not isinstance(ssp, str) or not ssp.startswith("//"):
            return False
        node_name, delim, demux = ssp[2:].partition("/")
        return bool(node_name) and delim == "/" and demux == ""
    if scheme == 2:
        if not (isinstance(ssp, list) and len(ssp) == 2):
            return False
        node, service = ssp
        if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in ssp):
            return False
        if node >= 0xFFFFFFFF:
            return False
        return node != 0 or service == 0
    return False


# -----------------------------
# Authority Context map -> BPv7 addressing
# -----------------------------

@dataclass(frozen=True)
class AuthorityContextMap:
    """
    Adapter configuration: authority context name -> {dest, src, report_to}.

    Each row holds the destination EID, the source node ID and the report-to
    EID, already encoded as BPv7 EIDs. The PBS-ENV-01 v1.3 header has no
    destination, authority or scope field, so no envelope field contributes
    to these values. The caller names the context for each envelope.
    """
    table: Dict[str, Dict[str, EID]]

    def __post_init__(self) -> None:
        for name, row in self.table.items():
            missing = {"dest", "src", "report_to"} - set(row)
            if missing:
                raise ValueError(f"Authority context {name!r} lacks {sorted(missing)}")
            if not is_source_node_id(row["src"]):
                raise ValueError(
                    f"Authority context {name!r}: src {row['src']!r} is not the null "
                    "endpoint, a dtn EID with an empty demux or an ipn EID "
                    "(RFC 9171 Section 4.2.5.1.1; RFC 9758 Sections 3.4.1, 5.3)"
                )

    def resolve(self, authority_context: str) -> Tuple[EID, EID, EID]:
        """Return (destination EID, source node ID, report-to EID)."""
        try:
            row = self.table[authority_context]
        except KeyError as e:
            raise KeyError(f"Unknown authority context: {authority_context}") from e
        return row["dest"], row["src"], row["report_to"]


# -----------------------------
# BPv7 bundle construction (RFC 9171 Sections 4.1, 4.3.1, 4.3.2)
# -----------------------------

# Bundle processing control flag bit 2 (RFC 9171 Section 4.2.3). A bundle
# whose source is the null endpoint MUST set it and MUST set no status
# report request flag.
BPF_MUST_NOT_FRAGMENT = 0x000004


@dataclass(frozen=True)
class BPv7Primary:
    """
    Primary block of a bundle that is not a fragment (RFC 9171 Section 4.3.1).
    Field order on the wire:
      [version, bundle_proc_flags, crc_type, dest_eid, src_node_id,
       report_to_eid, [creation_time, sequence], lifetime, crc]
    """
    destination: EID
    source: EID
    report_to: EID
    creation_time_dtn: int         # DTN time, milliseconds (RFC 9171 Section 4.2.6)
    creation_seq: int              # creation timestamp sequence number (Section 4.2.7)
    lifetime_ms: int               # milliseconds past the creation time (Section 4.3.1)
    bundle_proc_flags: int = 0     # bit field of RFC 9171 Section 4.2.3; 0 = no flag set
    crc_type: int = 2              # 2 = CRC32C (RFC 9171 Section 4.2.1)

    def to_cbor_with_crc_placeholder(self) -> list[Any]:
        if self.crc_type == 0:
            raise ValueError(
                "Primary block CRC type must be non-zero unless a BPSec BIB targets "
                "the primary block (RFC 9171 Section 4.3.1); this example builds no BIB."
            )
        if self.crc_type == 1:
            crc_placeholder = b"\x00\x00"
        elif self.crc_type == 2:
            crc_placeholder = b"\x00\x00\x00\x00"
        else:
            raise ValueError("Invalid CRC type; RFC 9171 Section 4.2.1 defines only 0, 1 and 2.")
        return [
            7,                               # version (BPv7)
            int(self.bundle_proc_flags),     # bundle processing control flags
            int(self.crc_type),              # primary block CRC type
            self.destination,                # destination EID
            self.source,                     # source node ID
            self.report_to,                  # report-to EID
            [int(self.creation_time_dtn), int(self.creation_seq)],  # creation timestamp
            int(self.lifetime_ms),           # lifetime, milliseconds
            crc_placeholder,                 # CRC field, zero while the CRC is computed
        ]


@dataclass(frozen=True)
class BPv7PayloadBlock:
    """
    Payload block in canonical block format (RFC 9171 Section 4.3.2):
      [block_type=1, block_number=1, block_ctrl_flags, crc_type, payload]
    This example uses CRC type 0 (no CRC), which Section 4.3.2 permits for
    canonical blocks.
    """
    payload: bytes
    block_ctrl_flags: int = 0
    crc_type: int = 0

    def to_cbor(self) -> list[Any]:
        if self.crc_type != 0:
            raise NotImplementedError("This example builds payload blocks with CRC type 0 only.")
        return [
            1,                      # block type code: payload
            1,                      # block number: 1
            int(self.block_ctrl_flags),
            int(self.crc_type),
            bytes(self.payload),    # definite-length CBOR byte string
        ]


def _encode_primary_with_crc(primary: BPv7Primary) -> bytes:
    """
    Encode the primary block with its CRC (RFC 9171 Sections 4.2.2, 4.3.1):
      - compute the CRC over the encoded block with the CRC field set to zeros;
      - store the CRC as a 2- or 4-byte CBOR byte string in network byte order.
    """
    prim_list = primary.to_cbor_with_crc_placeholder()
    prim_bytes_zero = cbor2.dumps(prim_list)

    if primary.crc_type == 1:
        crc_bstr = struct.pack("!H", crc16_x25(prim_bytes_zero))
    elif primary.crc_type == 2:
        crc_bstr = struct.pack("!I", crc32c(prim_bytes_zero))
    else:
        raise ValueError("Invalid primary CRC type.")

    prim_list[-1] = crc_bstr
    return cbor2.dumps(prim_list)


def build_bpv7_bundle(primary: BPv7Primary, payload_block: BPv7PayloadBlock) -> bytes:
    """
    Encode a bundle as a CBOR indefinite-length array (RFC 9171 Section 4.1):
    0x9F, the primary block, the payload block, then the break code 0xFF.
    """
    primary_bytes = _encode_primary_with_crc(primary)
    payload_bytes = cbor2.dumps(payload_block.to_cbor())
    return b"\x9f" + primary_bytes + payload_bytes + b"\xff"


# -----------------------------
# Time (RFC 9171 Section 4.2.6)
# -----------------------------

# RFC 9171 Section 4.2.6: DTN time is the number of milliseconds elapsed
# since the DTN epoch, 2000-01-01 00:00:00 +0000 (UTC), and is not affected
# by leap seconds. RFC 9171 defines no conversion from Unix time. This
# example uses DTN ms = Unix ms - 946 684 800 000 (the DTN epoch in Unix
# time), the offset ION bpv7 uses (EPOCH_2000_SEC = 946684800 in
# bpv7/library/bpP.h). Unix time omits the 5 leap seconds inserted since
# 2000-01-01 (IERS Leap_Second.dat: TAI-UTC 32 s from 1999-01-01, 37 s from
# 2017-01-01), so this value is 5000 ms less than a count of elapsed SI
# milliseconds.
DTN_EPOCH_UNIX_MS = 946_684_800_000


def unix_time_us() -> int:
    """Return the host clock as integer Unix time in microseconds."""
    return time.time_ns() // 1_000


def unix_us_to_dtn_ms(unix_us: int) -> int:
    """
    Convert Unix time in microseconds to DTN time in milliseconds, truncated.

    Raises ValueError at or before the DTN epoch: DTN time is an unsigned
    integer and the value 0 means "time unknown" (RFC 9171 Section 4.2.6).
    """
    dtn_ms = unix_us // 1_000 - DTN_EPOCH_UNIX_MS
    if dtn_ms <= 0:
        raise ValueError(f"Clock reads {unix_us} us Unix time, not after the DTN epoch")
    return dtn_ms


# -----------------------------
# Lifetime (PBS-DTN-MAP-01 Sections 6.1 and 6.1.1; PBS-DTN-MAP-02 Section 4;
# PBS-ENV-01 Section 12)
# -----------------------------

# Largest no-expiry lifetime PBS-DTN-MAP-01 Section 6.1.1 and PBS-DTN-MAP-02
# Section 4 permit: 4 294 967 295 000 ms, the largest TTL (2^32 - 1 s) in
# milliseconds.
MAX_NO_EXPIRY_LIFETIME_MS = 4_294_967_295_000

class EdgeAdapterError(Exception):
    """An envelope this example refuses to encapsulate."""


class EnvelopeExpiredError(EdgeAdapterError):
    """
    The envelope's TTL leaves no whole millisecond of bundle lifetime.

    Raised when the envelope has expired (age > TTL, PBS-ENV-01 Section
    12.2), which gateways MUST discard (Sections 12.1 and 15), and when less
    than 1 ms of the TTL remains, which PBS-DTN-MAP-01 Section 6.1 forbids
    encapsulating.
    """


class EnvelopeLengthError(EdgeAdapterError):
    """The input is longer than the 44-byte header plus the Size field."""


def bundle_lifetime_ms(envelope: PBSEnvelope, now_us: int, default_lifetime_ms: int) -> int:
    """
    Select the bundle lifetime (PBS-DTN-MAP-01 Sections 6.1 and 6.1.1;
    PBS-DTN-MAP-02 Section 4).

    default_lifetime_ms is the no-expiry lifetime: an integer from 1 to
    4_294_967_295_000 ms (PBS-DTN-MAP-01 Section 6.1.1). A deployment also
    selects a value that its bundle protocol agent accepts and for which
    the agent computes creation time + lifetime without overflow (Section
    6.1.1); this example connects to no agent and does not check that.

    TTL 0: the envelope never expires (PBS-ENV-01 Section 12.1). This
    example reads no Service Intent frame and no mission expiry policy, so
    no PBS-DTN-MAP-02 Section 4 finite limit applies; return
    default_lifetime_ms (PBS-DTN-MAP-01 Section 6.1.1). When the bundle's
    age exceeds it, the BP agent deletes the bundle (RFC 9171 Section 5.5)
    and the envelope with it. That deletion is not TTL expiry
    (PBS-DTN-MAP-01 Sections 6.1.1 and 7.3).

    TTL > 0: the envelope expires at Timestamp + TTL (PBS-ENV-01 Section
    12.2). Return min(default_lifetime_ms, remaining_ms), where
      remaining_ms = (TTL * 1_000_000 - age_us) // 1000
      age_us       = max(0, now_us - Timestamp)
    This is the PBS-DTN-MAP-01 Section 6.1 bound computed with now_us in
    place of the creation time: the creation time is now_us truncated to
    whole milliseconds, so it is not later than now_us and the bundle
    expires no later than the envelope. A Timestamp later than now_us
    gives age 0, so the lifetime never exceeds TTL * 1000. The result never
    exceeds default_lifetime_ms, the TTL 0 lifetime (Section 6.1.1).

    Raises EnvelopeExpiredError if remaining_ms < 1 (PBS-DTN-MAP-01
    Section 6.1), and ValueError if default_lifetime_ms is outside
    1..4_294_967_295_000.
    """
    if not 1 <= default_lifetime_ms <= MAX_NO_EXPIRY_LIFETIME_MS:
        raise ValueError(
            f"default_lifetime_ms must be 1 to {MAX_NO_EXPIRY_LIFETIME_MS} ms "
            "(PBS-DTN-MAP-01 Section 6.1.1)"
        )
    if envelope.ttl == 0:
        return default_lifetime_ms

    ttl_us = envelope.ttl * 1_000_000
    age_us = max(0, now_us - envelope.timestamp)
    remaining_ms = (ttl_us - age_us) // 1_000
    if age_us > ttl_us:
        raise EnvelopeExpiredError(
            f"Envelope expired: age {age_us} us exceeds TTL {envelope.ttl} s (PBS-ENV-01 Section 12.2)"
        )
    if remaining_ms <= 0:
        raise EnvelopeExpiredError(
            f"Envelope has {ttl_us - age_us} us of TTL left, less than 1 ms of bundle lifetime"
        )
    return min(default_lifetime_ms, remaining_ms)


# -----------------------------
# PBS envelope -> BPv7 bundle
# -----------------------------

def pbs_to_bpv7_bundle_mv(
    pbs_envelope_bytes: bytes,
    authority_context: str,
    authority_map: AuthorityContextMap,
    default_lifetime_ms: int = 60_000,
    creation_seq: int = 1,
    clock_us: Callable[[], int] = unix_time_us,
) -> bytes:
    """
    Encapsulate one PBS-ENV-01 v1.3 envelope in one BPv7 bundle.

    pbs_envelope_bytes   complete envelope: 44-byte header + Size payload bytes
    authority_context    name of the Authority Context map entry to use
    authority_map        Authority Context map (adapter configuration)
    default_lifetime_ms  no-expiry lifetime, 1 to 4_294_967_295_000 ms: the
                         bundle lifetime when TTL is 0 and the upper bound
                         otherwise (PBS-DTN-MAP-01 Section 6.1.1)
    creation_seq         creation timestamp sequence number, a non-negative
                         integer (RFC 9171 Section 4.2.7); a BP agent supplies
                         it from its own counter
    clock_us             returns Unix time in microseconds; read once, for both
                         the creation time and the envelope age

    The bundle processing control flags are 0, or 0x04 ("bundle must not be
    fragmented") when the source is the null endpoint (RFC 9171 Section 4.2.3).

    Raises PBS_LINK.PBSValidationError or a subclass (PBSMagicError,
    PBSCRCError, PBSPriorityError) for an invalid or truncated envelope,
    EnvelopeLengthError for trailing bytes, EnvelopeExpiredError, KeyError
    for an unknown authority context, and ValueError for a negative
    creation_seq, a default_lifetime_ms outside 1..4_294_967_295_000, or a
    clock reading at or before the DTN epoch.
    """
    if creation_seq < 0:
        raise ValueError("creation_seq must be a non-negative integer (RFC 9171 Section 4.2.7)")

    envelope = parse_envelope(pbs_envelope_bytes)
    expected_len = HEADER_SIZE + envelope.size
    if len(pbs_envelope_bytes) != expected_len:
        raise EnvelopeLengthError(
            f"Input is {len(pbs_envelope_bytes)} bytes; header Size gives {expected_len}"
        )

    dest, src, rpt = authority_map.resolve(authority_context)

    now_us = clock_us()
    lifetime_ms = bundle_lifetime_ms(envelope, now_us, default_lifetime_ms)

    primary = BPv7Primary(
        destination=dest,
        source=src,
        report_to=rpt,
        creation_time_dtn=unix_us_to_dtn_ms(now_us),
        creation_seq=creation_seq,
        lifetime_ms=lifetime_ms,
        bundle_proc_flags=BPF_MUST_NOT_FRAGMENT if is_null_endpoint(src) else 0,
        crc_type=2,  # CRC32C
    )

    # The envelope is opaque to the bundle layer: its bytes become the
    # payload block's byte string as received, header CRC32 included
    # (PBS-DTN-MAP-01 Sections 6.2 and 6.4).
    payload_block = BPv7PayloadBlock(payload=bytes(pbs_envelope_bytes), crc_type=0)

    return build_bpv7_bundle(primary, payload_block)


# -----------------------------
# Worked example run
# -----------------------------

if __name__ == "__main__":
    # 1) Authority Context map. Both EID schemes are shown; the run uses the
    #    dtn-scheme entry. Each src is the administrative endpoint of the
    #    adapter's BP node: a dtn EID with an empty demux or an ipn EID with
    #    service number 0 (RFC 9171 Sections 4.2.5.1.1, 4.2.5.1.2).
    ac_map = AuthorityContextMap(
        table={
            "pbsf.luna.ops": {
                "dest": eid_dtn("//pbsf.example/luna/ops"),
                "src": eid_dtn("//edge-17.pbsf.example/"),
                "report_to": eid_dtn("//pbsf.example/ops/reports"),
            },
            "pbsf.mars.science": {
                "dest": eid_ipn(4001, 10),     # ipn:4001.10
                "src": eid_ipn(4017, 0),       # ipn:4017.0
                "report_to": eid_ipn(4001, 11),  # ipn:4001.11
            },
        }
    )

    # 2) PBS-ENV-01 v1.3 envelope built by the PBS_LINK reference SDK.
    print("Building a PBS-ENV-01 v1.3 envelope with PBS_LINK.build_envelope.")
    envelope_bytes = build_envelope(
        source_id="Rover-Alpha",
        priority=Priority.NORMAL,
        payload="VOLTAGE=119.7, CURRENT=18.2",
        ttl=120,
        require_ack=False,
    )
    envelope = parse_envelope(envelope_bytes)
    print(
        f"Envelope: {len(envelope_bytes)} bytes "
        f"({HEADER_SIZE}-byte header + {envelope.size}-byte payload), TTL {envelope.ttl} s"
    )
    print(f"Envelope header (hex): {envelope_bytes[:HEADER_SIZE].hex()}")

    # 3) Encapsulate. The configured default (300 000 ms) exceeds the
    #    envelope's 120 s TTL, so the remaining TTL sets the lifetime.
    default_lifetime_ms = 300_000
    bundle_bytes = pbs_to_bpv7_bundle_mv(
        pbs_envelope_bytes=envelope_bytes,
        authority_context="pbsf.luna.ops",
        authority_map=ac_map,
        default_lifetime_ms=default_lifetime_ms,
        creation_seq=42,
    )

    print("\nBPv7 bundle (hex):")
    print(bundle_bytes.hex())

    # 4) Decode the bundle with cbor2 and report the primary block fields.
    decoded = cbor2.loads(bundle_bytes)
    primary_block = decoded[0]
    payload_block = decoded[-1]
    creation_ms, sequence = primary_block[6]
    dtn_epoch = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
    creation_utc = dtn_epoch + datetime.timedelta(milliseconds=creation_ms)

    print("\nPrimary block:")
    print(primary_block)
    print(f"Creation time: {creation_ms} ms DTN time ({creation_utc.isoformat()}), sequence {sequence}")
    print(
        f"Lifetime: {primary_block[7]} ms "
        f"(configured default {default_lifetime_ms} ms, bounded by remaining TTL)"
    )

    print("\nPayload block header [type, number, flags, CRC type]:")
    print(payload_block[:4])
    if payload_block[4] != envelope_bytes:
        raise SystemExit("Payload block bytes differ from the envelope bytes.")
    print(f"Payload block bytes equal the envelope bytes ({len(payload_block[4])} bytes).")
