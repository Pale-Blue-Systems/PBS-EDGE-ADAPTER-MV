"""
PBS-EDGE-ADAPTER-MV — Worked Example (BPv7 encapsulation)

This example shows how to:
  1) Treat an incoming PBS "envelope" (real binary bytes from pbs_link) as the BPv7 payload (ADU).
  2) Build a BPv7 bundle:
        - Outer bundle: CBOR indefinite-length array of blocks
        - Primary block: CBOR array (RFC 9171 §4.3.1)
        - Payload block: canonical block type 1, number 1 (RFC 9171 §4.3.2)
  3) Compute and attach the Primary Block CRC as CRC32C (Castagnoli) (RFC 9171 §4.2.1–4.2.2, §4.3.1)

Normative reference:
  - IETF RFC 9171: Bundle Protocol Version 7 (BPv7)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple, Union, Optional
import time
import struct
import sys
import os

# External dependency (intentionally small and common).
# pip install cbor2
import cbor2

# Add sibling directory to path to import pbs_link if not installed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../PBS-LINK")))

try:
    from pbs_link import PBSLink, build_envelope
except ImportError:
    # If pbs-link is not installed or found, defining a mock for syntax checking or local execution without it
    print("WARNING: pbs_link not found. Ensure PBS-LINK is installed or in PYTHONPATH.")
    # In a real environment, this should fail.


# -----------------------------
# CRC utilities (RFC 9171 §4.2.1)
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
    """
    Returns CRC32C as an unsigned 32-bit integer.
    """
    crc = 0xFFFFFFFF
    for b in data:
        crc = _CRC32C_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF


def crc16_x25(data: bytes) -> int:
    """
    CRC-16/X-25 ("standard X-25 CRC-16" per RFC 9171 §4.2.1):
      poly=0x1021 (reflected 0x8408), init=0xFFFF, refin/refout=True, xorout=0xFFFF
    Returns CRC as unsigned 16-bit integer.
    """
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if (crc & 0x0001) else (crc >> 1)
    crc ^= 0xFFFF
    return crc & 0xFFFF


# -----------------------------
# BPv7 EID encoding (RFC 9171 §4.2.5.1 + IANA scheme codes §9.6)
# -----------------------------

def eid_dtn(ssp: str) -> list[Union[int, str]]:
    """
    Encodes a dtn-scheme EID as [uri_code, SSP]
      - uri_code for 'dtn' is 1 (RFC 9171 §9.6)
      - SSP is CBOR text string unless SSP == "none", then it is integer 0 (RFC 9171 §4.2.5.1.1)
    Note: SSP here is the scheme-specific part (everything after "dtn:"), not the full URI.
    """
    if ssp == "none":
        return [1, 0]
    return [1, ssp]


def eid_ipn(node_num: int, service_num: int) -> list[Union[int, list[int]]]:
    """
    Encodes an ipn-scheme EID as [uri_code, [node_num, service_num]]
      - uri_code for 'ipn' is 2 (RFC 9171 §9.6; ipn scheme originally RFC 6260)
    """
    return [2, [int(node_num), int(service_num)]]


EID = list[Union[int, str, list[int]]]


# -----------------------------
# Authority Context → BP addressing (PBS mapping MV)
# -----------------------------

@dataclass(frozen=True)
class AuthorityContextMap:
    """
    Minimal MV mapping table:
      authority_context -> { dest, src, report_to } as BPv7 EIDs.

    In a full Edge Adapter, these would be sourced from the PBS Authority Context registry
    and deployment config. This MV just demonstrates deterministic selection.
    """
    table: Dict[str, Dict[str, EID]]

    def resolve(self, authority_context: str) -> Tuple[EID, EID, EID]:
        try:
            row = self.table[authority_context]
            return row["dest"], row["src"], row["report_to"]
        except KeyError as e:
            raise KeyError(f"Unknown or incomplete authority_context mapping: {authority_context}") from e


# -----------------------------
# BPv7 bundle construction (RFC 9171 §4.1, §4.3.1, §4.3.2)
# -----------------------------

@dataclass(frozen=True)
class BPv7Primary:
    """
    Primary block fields (non-fragment) per RFC 9171 §4.3.1, order MUST match:
      [version, bundle_proc_flags, crc_type, dest_eid, src_node_id, report_to_eid, creation_ts, lifetime, crc]
    """
    destination: EID
    source: EID
    report_to: EID
    creation_time_dtn: int         # dtn-time (uint) (RFC 9171 §4.2.6)
    creation_seq: int              # sequence (uint) (RFC 9171 §4.2.7)
    lifetime_ms: int
    bundle_proc_flags: int = 0     # MV: no fragment/admin-record/etc.
    crc_type: int = 2              # MV: CRC32C (Castagnoli) (RFC 9171 §4.2.1)

    def to_cbor_with_crc_placeholder(self) -> list[Any]:
        if self.crc_type == 0:
            raise ValueError("Primary block CRC type must be non-zero unless protected by a BIB (not in this MV).")
        if self.crc_type == 1:
            crc_placeholder = b"\x00\x00"
        elif self.crc_type == 2:
            crc_placeholder = b"\x00\x00\x00\x00"
        else:
            raise ValueError("Invalid CRC type (RFC 9171 allows only 0, 1, 2).")
        return [
            7,                              # version (BPv7)
            int(self.bundle_proc_flags),     # bundle processing control flags
            int(self.crc_type),              # primary CRC type
            self.destination,                # destination EID
            self.source,                     # source node ID (may be dtn:none)
            self.report_to,                  # report-to EID
            [int(self.creation_time_dtn), int(self.creation_seq)],  # creation timestamp
            int(self.lifetime_ms),           # lifetime in ms
            crc_placeholder,                 # CRC field (placeholder for computation)
        ]


@dataclass(frozen=True)
class BPv7PayloadBlock:
    """
    Canonical payload block structure (RFC 9171 §4.3.2):
      [block_type=1, block_number=1, block_ctrl_flags, crc_type, payload_bytes, ?crc]
    MV chooses crc_type=0 for payload block (allowed).
    """
    payload: bytes
    block_ctrl_flags: int = 0
    crc_type: int = 0

    def to_cbor(self) -> list[Any]:
        if self.crc_type != 0:
            raise NotImplementedError("MV only demonstrates payload block CRC type 0.")
        return [
            1,                      # block type code: payload
            1,                      # block number: 1
            int(self.block_ctrl_flags),
            int(self.crc_type),
            bytes(self.payload),    # definite-length CBOR bstr
        ]


def _encode_primary_with_crc(primary: BPv7Primary) -> bytes:
    """
    Encode primary block with computed CRC per RFC 9171:
      - CRC computed over the bytes of the primary block including the CRC field,
        with CRC field bytes temporarily all zeros (RFC 9171 §4.3.1).
      - CRC value is stored as CBOR bstr of length 2 or 4 in network byte order (RFC 9171 §4.2.2).
    """
    prim_list = primary.to_cbor_with_crc_placeholder()
    prim_bytes_zero = cbor2.dumps(prim_list)

    if primary.crc_type == 1:
        crc_val = crc16_x25(prim_bytes_zero)
        crc_bstr = struct.pack("!H", crc_val)  # 2 bytes, network order
    elif primary.crc_type == 2:
        crc_val = crc32c(prim_bytes_zero)
        crc_bstr = struct.pack("!I", crc_val)  # 4 bytes, network order
    else:
        raise ValueError("Invalid primary CRC type.")

    prim_list[-1] = crc_bstr
    return cbor2.dumps(prim_list)


def build_bpv7_bundle(primary: BPv7Primary, payload_block: BPv7PayloadBlock) -> bytes:
    """
    Bundle = CBOR indefinite-length array of blocks:
      - First item: primary block (CBOR array)
      - Last item: payload block (CBOR array)
      - Terminator: CBOR break (0xFF)
    (RFC 9171 §4.1, §4.3)
    """
    primary_bytes = _encode_primary_with_crc(primary)
    payload_bytes = cbor2.dumps(payload_block.to_cbor())

    # CBOR indefinite-length array start (0x9f) + items + break (0xff)
    return b"\x9f" + primary_bytes + payload_bytes + b"\xff"


# -----------------------------
# PBS envelope → BPv7 payload (MV)
# -----------------------------

def pbs_to_bpv7_bundle_mv(
    pbs_envelope_bytes: bytes,
    authority_context: str,
    authority_map: AuthorityContextMap,
    lifetime_ms: int = 60_000,
    creation_seq: int = 1,
) -> bytes:
    """
    Full MV conversion:
      PBS envelope (bytes) -> BPv7 bundle (bytes)
    """
    dest, src, rpt = authority_map.resolve(authority_context)

    # RFC 9171 DTN time is seconds since 2000-01-01T00:00:00Z (DTN epoch),
    # but implementations often supply DTN time via local BP stack.
    # MV approximation: use unix time -> convert to DTN epoch.
    # DTN epoch offset = seconds from 1970-01-01 to 2000-01-01 = 946684800.
    # NOTE: This reference example approximates DTN time by offsetting Unix time.
    # Production gateways MUST derive DTN time from a proper TAI-based clock source.
    unix_now = int(time.time())
    dtn_time_now = max(0, unix_now - 946684800)

    # In actual edge adapters, the envelope is OPAQUE bytes.
    # We do NOT CBOR encode it again; we place it directly into the payload block.
    payload = pbs_envelope_bytes

    primary = BPv7Primary(
        destination=dest,
        source=src,
        report_to=rpt,
        creation_time_dtn=dtn_time_now,
        creation_seq=creation_seq,
        lifetime_ms=lifetime_ms,
        bundle_proc_flags=0,
        crc_type=2,  # CRC32C
    )

    payload_block = BPv7PayloadBlock(payload=payload, crc_type=0)

    return build_bpv7_bundle(primary, payload_block)


# -----------------------------
# Worked example run
# -----------------------------

if __name__ == "__main__":
    # 1) Minimal Authority Context table (MV)
    # Using dtn scheme here for human readability; ipn scheme can be used for compactness.
    ac_map = AuthorityContextMap(
        table={
            "pbsf.luna.ops": {
                "dest": eid_dtn("//pbsf.example/luna/ops"),
                "src": eid_dtn("//pbsf.example/edge/node-17"),
                "report_to": eid_dtn("//pbsf.example/ops/reports"),
            },
            "pbsf.mars.science": {
                "dest": eid_ipn(4001, 10),   # ipn:4001.10
                "src": eid_ipn(4001, 99),    # ipn:4001.99
                "report_to": eid_ipn(4001, 11),
            },
        }
    )

    # 2) Example PBS envelope (Real Binary via pbs_link)
    # Using the SDK to generate a normative compliant binary envelope.
    print("Generating binary PBS envelope using pbs_link...")
    
    pbs_binary_envelope = build_envelope(
        source_id="Rover-Alpha",
        priority=2, # NORMAL
        payload="VOLTAGE=119.7, CURRENT=18.2",
        ttl=120,
        require_ack=False
    )
    
    print(f"Generated {len(pbs_binary_envelope)} bytes of PBS envelope.")
    print(f"Hex: {pbs_binary_envelope.hex()[:64]}...")

    # 3) Convert to BPv7 bundle bytes
    bundle_bytes = pbs_to_bpv7_bundle_mv(
        pbs_envelope_bytes=pbs_binary_envelope,
        authority_context="pbsf.luna.ops",
        authority_map=ac_map,
        lifetime_ms=120_000,
        creation_seq=42,
    )

    # 4) Output: raw bundle hex (portable for fixtures)
    print("\nBPv7 bundle (hex):")
    print(bundle_bytes.hex())

    # 5) Decode for inspection (should round-trip)
    decoded = cbor2.loads(bundle_bytes)
    primary_block = decoded[0]
    payload_block = decoded[-1]

    print("\nDecoded Primary Block:")
    print(primary_block)

    print("\nDecoded Payload Block header:")
    print(payload_block[:4])
    print("Payload bytes length:", len(payload_block[4]))
    
    # Verify the payload in the bundle matches our original binary envelope
    assert payload_block[4] == pbs_binary_envelope
    print("SUCCESS: Bundle payload matches original binary envelope.")
