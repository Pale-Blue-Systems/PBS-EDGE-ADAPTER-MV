"""
Independent BPv7 wire decoder for bundles captured on the demonstration link.

decode_bundle() splits a serialized bundle (RFC 9171 Section 4.1) into its
blocks, checks every block CRC over the bytes as received, and returns the
decoded fields. It does not re-encode anything: each CRC is computed over the
block's own bytes with the CRC value replaced by zeros (RFC 9171 Section
4.2.2), so a bundle encoded by another implementation (here ION) is checked
exactly as that implementation wrote it.

The decoder implements only what the demonstration checks; it is not a
general bundle protocol agent. It rejects:
  - a bundle that is not a CBOR indefinite-length array (Section 4.1);
  - a primary block that is not version 7, has an unknown CRC type, or is a
    fragment (the demonstration never fragments; Section 4.3.1);
  - a block whose CRC does not verify (Section 4.2.1);
  - a bundle with no payload block, or a payload block that is not the last
    block (Section 4.1).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

import cbor2

from pbs_edge_adapter_worked_example import (
    BPF_ASSIGNED_MASK,
    DTN_EPOCH_UNIX_MS,
    crc16_x25,
    crc32c,
)

# RFC 9171 Section 4.2.3: bundle processing control flag "bundle is a fragment".
BPF_IS_FRAGMENT = 0x000001

# Block type codes (RFC 9171 Sections 4.3.2-4.4.3 and 9.1). 193 is in the
# range 192-255 that Section 9.1 reserves for private and experimental use;
# ION 4.2.0 uses it for its Quality of Service block (bpv7/include/bp.h,
# QualityOfServiceBlk = 193; bpv7/library/ext/bpq/bpq.c).
BLOCK_TYPE_PAYLOAD = 1
BLOCK_TYPE_PREVIOUS_NODE = 6
BLOCK_TYPE_BUNDLE_AGE = 7
BLOCK_TYPE_HOP_COUNT = 10
BLOCK_TYPE_ION_QOS = 193


class BundleFormatError(ValueError):
    """The captured bytes are not a well-formed, CRC-valid BPv7 bundle."""


# -----------------------------
# Minimal CBOR item scanner (RFC 8949 Section 3)
# -----------------------------

def _head(buf: bytes, i: int) -> Tuple[int, int, Optional[int], int]:
    """
    Read the head of the CBOR data item at buf[i].

    Returns (major type, additional info, argument or None for indefinite
    length, index of the first byte after the head).
    """
    if i >= len(buf):
        raise BundleFormatError("CBOR item truncated")
    ib = buf[i]
    major, ai = ib >> 5, ib & 0x1F
    i += 1
    if ai < 24:
        return major, ai, ai, i
    if ai in (24, 25, 26, 27):
        n = 1 << (ai - 24)
        if i + n > len(buf):
            raise BundleFormatError("CBOR head truncated")
        return major, ai, int.from_bytes(buf[i:i + n], "big"), i + n
    if ai == 31 and major in (2, 3, 4, 5, 7):
        return major, ai, None, i
    raise BundleFormatError(f"Unsupported CBOR additional information {ai} at offset {i - 1}")


def item_end(buf: bytes, i: int) -> int:
    """Return the index just past the CBOR data item that starts at buf[i]."""
    major, ai, arg, i = _head(buf, i)
    if major in (0, 1):
        return i
    if major in (2, 3):
        if arg is None:  # indefinite-length string: chunks until break
            while True:
                if i >= len(buf):
                    raise BundleFormatError("Indefinite string lacks break")
                if buf[i] == 0xFF:
                    return i + 1
                i = item_end(buf, i)
        if i + arg > len(buf):
            raise BundleFormatError("CBOR string truncated")
        return i + arg
    if major in (4, 5):
        count_per_entry = 1 if major == 4 else 2
        if arg is None:
            while True:
                if i >= len(buf):
                    raise BundleFormatError("Indefinite container lacks break")
                if buf[i] == 0xFF:
                    return i + 1
                i = item_end(buf, i)
        for _ in range(arg * count_per_entry):
            i = item_end(buf, i)
        return i
    if major == 6:
        return item_end(buf, i)
    # major 7: simple values and floats; the head carried everything except
    # the break code, which item_end never consumes on its own.
    if ai == 31:
        raise BundleFormatError("Unexpected break code")
    return i


# -----------------------------
# Decoded structures
# -----------------------------

@dataclass(frozen=True)
class Block:
    """One canonical block (RFC 9171 Section 4.3.2) as received."""
    block_type: int
    block_number: int
    block_proc_flags: int
    crc_type: int
    data: bytes
    raw: bytes


@dataclass(frozen=True)
class Bundle:
    """A decoded, CRC-verified bundle that is not a fragment."""
    raw: bytes
    bundle_proc_flags: int
    primary_crc_type: int
    destination: Any
    source: Any
    report_to: Any
    creation_time_ms: int
    creation_seq: int
    lifetime_ms: int
    blocks: List[Block] = field(default_factory=list)

    @property
    def payload(self) -> bytes:
        return self.blocks[-1].data

    def blocks_of_type(self, block_type: int) -> List[Block]:
        return [b for b in self.blocks if b.block_type == block_type]

    @property
    def creation_unix_ms(self) -> int:
        """Creation time as Unix time in ms, by ION's offset (RFC 9171 Section 4.2.6)."""
        return self.creation_time_ms + DTN_EPOCH_UNIX_MS

    @property
    def expiry_unix_ms(self) -> int:
        """Creation time + lifetime as Unix time in ms (RFC 9171 Sections 4.3.1, 5.5)."""
        return self.creation_unix_ms + self.lifetime_ms


def eid_to_text(eid: Any) -> str:
    """Render an encoded EID as text: ipn:N.S, dtn:none or dtn:<ssp>."""
    scheme, ssp = eid
    if scheme == 2:
        if len(ssp) == 2:
            return f"ipn:{ssp[0]}.{ssp[1]}"
        return f"ipn:{ssp[0]}.{ssp[1]}.{ssp[2]}"  # 3-element form, RFC 9758
    if scheme == 1:
        return "dtn:none" if ssp == 0 else f"dtn:{ssp}"
    raise BundleFormatError(f"Unknown EID scheme {scheme}")


def _check_crc(raw_block: bytes, crc_type: int, what: str) -> None:
    """
    Verify a block CRC over the block's bytes with the CRC value zeroed
    (RFC 9171 Section 4.2.2). The CRC is the block's last item, a byte
    string of 2 (CRC-16/X-25) or 4 (CRC32C) bytes, so its value is the last
    2 or 4 bytes of the block.
    """
    if crc_type == 0:
        return
    if crc_type == 1:
        n, fn, fmt = 2, crc16_x25, "!H"
    elif crc_type == 2:
        n, fn, fmt = 4, crc32c, "!I"
    else:
        raise BundleFormatError(f"{what}: unknown CRC type {crc_type}")
    received = raw_block[-n:]
    computed = struct.pack(fmt, fn(raw_block[:-n] + b"\x00" * n))
    if received != computed:
        raise BundleFormatError(
            f"{what}: CRC mismatch, received {received.hex()}, computed {computed.hex()}"
        )


def decode_bundle(raw: bytes) -> Bundle:
    """Decode and CRC-check one serialized bundle; raise BundleFormatError."""
    raw = bytes(raw)
    if not raw or raw[0] != 0x9F:
        raise BundleFormatError("Bundle is not a CBOR indefinite-length array (RFC 9171 Section 4.1)")

    spans: List[Tuple[int, int]] = []
    i = 1
    while True:
        if i >= len(raw):
            raise BundleFormatError("Bundle lacks the CBOR break code")
        if raw[i] == 0xFF:
            if i + 1 != len(raw):
                raise BundleFormatError(f"{len(raw) - i - 1} bytes follow the bundle")
            break
        end = item_end(raw, i)
        spans.append((i, end))
        i = end
    if len(spans) < 2:
        raise BundleFormatError("Bundle has no canonical block")

    p_start, p_end = spans[0]
    primary_raw = raw[p_start:p_end]
    primary = cbor2.loads(primary_raw)
    if not isinstance(primary, list) or len(primary) not in (8, 9, 10, 11):
        raise BundleFormatError("Primary block is not an array of 8 to 11 items")
    version, flags, crc_type = primary[0], primary[1], primary[2]
    if version != 7:
        raise BundleFormatError(f"Primary block version {version}, not 7")
    if flags & BPF_IS_FRAGMENT:
        raise BundleFormatError("Bundle is a fragment; the demonstration never fragments")
    expected_len = {0: 8, 1: 9, 2: 9}.get(crc_type)
    if expected_len is None:
        raise BundleFormatError(f"Primary block CRC type {crc_type} is not 0, 1 or 2")
    if len(primary) != expected_len:
        raise BundleFormatError(f"Primary block has {len(primary)} items, expected {expected_len}")
    _check_crc(primary_raw, crc_type, "Primary block")

    blocks: List[Block] = []
    for start, end in spans[1:]:
        block_raw = raw[start:end]
        b = cbor2.loads(block_raw)
        if not isinstance(b, list) or len(b) not in (5, 6):
            raise BundleFormatError("Canonical block is not an array of 5 or 6 items")
        b_type, b_num, b_flags, b_crc_type, b_data = b[:5]
        if (b_crc_type == 0) != (len(b) == 5):
            raise BundleFormatError(f"Block {b_num}: CRC type {b_crc_type} with {len(b)} items")
        if not isinstance(b_data, bytes):
            raise BundleFormatError(f"Block {b_num}: block-type-specific data is not a byte string")
        _check_crc(block_raw, b_crc_type, f"Block {b_num} (type {b_type})")
        blocks.append(Block(b_type, b_num, b_flags, b_crc_type, b_data, block_raw))

    if blocks[-1].block_type != BLOCK_TYPE_PAYLOAD or blocks[-1].block_number != 1:
        raise BundleFormatError("The last block is not the payload block, number 1 (RFC 9171 Section 4.1)")
    if sum(1 for b in blocks if b.block_type == BLOCK_TYPE_PAYLOAD) != 1:
        raise BundleFormatError("Bundle has more than one payload block")

    creation_time_ms, creation_seq = primary[6]
    return Bundle(
        raw=raw,
        bundle_proc_flags=flags,
        primary_crc_type=crc_type,
        destination=primary[3],
        source=primary[4],
        report_to=primary[5],
        creation_time_ms=creation_time_ms,
        creation_seq=creation_seq,
        lifetime_ms=primary[7],
        blocks=blocks,
    )


def reserved_flags_set(bundle: Bundle) -> int:
    """Bundle processing control flags RFC 9171 Section 4.2.3 does not assign."""
    return bundle.bundle_proc_flags & ~BPF_ASSIGNED_MASK


def ion_qos(bundle: Bundle) -> Optional[dict]:
    """
    Decode ION's Quality of Service block (type 193), or None if absent.

    ION 4.2.0 qos_serialize (bpv7/library/ext/bpq/bpq.c) writes a 4-item
    array: [ancillary flags, class of service, ordinal, data label].
    """
    qos = bundle.blocks_of_type(BLOCK_TYPE_ION_QOS)
    if not qos:
        return None
    if len(qos) != 1:
        raise BundleFormatError("More than one ION QoS block")
    items = cbor2.loads(qos[0].data)
    if not (isinstance(items, list) and len(items) == 4):
        raise BundleFormatError(f"ION QoS block data {items!r} is not a 4-item array")
    flags, cos, ordinal, label = items
    return {"flags": flags, "class_of_service": cos, "ordinal": ordinal, "data_label": label}
