import struct
import cbor2
import sys
import os
import pytest

# Add sibling directory to path to import pbs_link
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../PBS-LINK")))

from pbs_link import build_envelope

# Import from your worked example module
from pbs_edge_adapter_worked_example import (
    BPv7Primary,
    BPv7PayloadBlock,
    AuthorityContextMap,
    build_bpv7_bundle,
    eid_dtn,
    crc32c,
)


def _recompute_primary_crc32c(primary_list) -> bytes:
    """
    Recompute CRC32C for a BPv7 primary block CBOR array (RFC 9171),
    assuming crc_type == 2 and CRC field is a 4-byte bstr.
    """
    assert primary_list[2] == 2, "Test expects CRC32C primary block (crc_type=2)"
    assert isinstance(primary_list[-1], (bytes, bytearray)) and len(primary_list[-1]) == 4

    # Copy and zero the CRC field for computation
    prim_zero = list(primary_list)
    prim_zero[-1] = b"\x00\x00\x00\x00"
    prim_bytes_zero = cbor2.dumps(prim_zero)

    crc_val = crc32c(prim_bytes_zero)
    return struct.pack("!I", crc_val)


def test_bpv7_bundle_primary_crc_and_payload_roundtrip():
    # -----------------------------
    # 1) Deterministic Authority Context mapping (test fixture)
    # -----------------------------
    ac_map = AuthorityContextMap(
        table={
            "pbsf.luna.ops": {
                "dest": eid_dtn("//pbsf.example/luna/ops"),
                "src": eid_dtn("//pbsf.example/edge/node-17"),
                "report_to": eid_dtn("//pbsf.example/ops/reports"),
            }
        }
    )
    dest, src, rpt = ac_map.resolve("pbsf.luna.ops")

    # -----------------------------
    # 2) Deterministic PBS envelope bytes (test fixture)
    #    Use REAL binary envelope from pbs_link
    # -----------------------------
    
    # We set a fixed timestamp via mocks or just accept current time for the test structure 
    # (since we are testing BPv7 wrapping, not pbs_link internals)
    # OR better, since we just need "bytes", we can trust build_envelope
    
    pbs_payload_content = "VOLTAGE=120.0"
    pbs_binary_envelope = build_envelope(
        source_id="TEST-ROVER",
        priority=2,
        payload=pbs_payload_content,
        ttl=120,
        sequence=1
    )
    
    # In the new code, the binary envelope IS the payload block content
    pbs_payload_bytes = pbs_binary_envelope

    # -----------------------------
    # 3) Build a BPv7 bundle with deterministic primary fields
    # -----------------------------
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
    payload_block = BPv7PayloadBlock(payload=pbs_payload_bytes, crc_type=0)

    bundle_bytes = build_bpv7_bundle(primary, payload_block)

    # -----------------------------
    # 4) Decode bundle: must be CBOR indefinite array of blocks
    # -----------------------------
    decoded = cbor2.loads(bundle_bytes)
    assert isinstance(decoded, list)
    assert len(decoded) >= 2, "Bundle must contain at least primary block and payload block"

    primary_block = decoded[0]
    payload_block_decoded = decoded[-1]

    # -----------------------------
    # 5) Validate Primary Block structure (RFC 9171 §4.3.1)
    # Primary block is a CBOR array length 9 for non-fragment bundles:
    # [version, flags, crc_type, dest, src, rpt, creation_ts, lifetime, crc]
    # -----------------------------
    assert isinstance(primary_block, list)
    assert len(primary_block) == 9

    version = primary_block[0]
    flags = primary_block[1]
    crc_type = primary_block[2]
    dest_eid = primary_block[3]
    src_eid = primary_block[4]
    rpt_eid = primary_block[5]
    creation_ts = primary_block[6]
    lifetime_ms = primary_block[7]
    crc_field = primary_block[8]

    assert version == 7
    assert isinstance(flags, int)
    assert crc_type == 2
    assert dest_eid == dest
    assert src_eid == src
    assert rpt_eid == rpt
    assert isinstance(creation_ts, list) and creation_ts == [123456, 42]
    assert lifetime_ms == 120_000
    assert isinstance(crc_field, (bytes, bytearray)) and len(crc_field) == 4

    # -----------------------------
    # 6) Validate Primary Block CRC32C is correct (recompute)
    # -----------------------------
    expected_crc_bstr = _recompute_primary_crc32c(primary_block)
    assert bytes(crc_field) == expected_crc_bstr

    # -----------------------------
    # 7) Validate Payload Block structure (RFC 9171 §4.3.2)
    # MV payload block is:
    # [block_type=1, block_number=1, block_flags, crc_type=0, payload_bytes]
    # -----------------------------
    assert isinstance(payload_block_decoded, list)
    assert len(payload_block_decoded) == 5

    assert payload_block_decoded[0] == 1  # payload block type
    assert payload_block_decoded[1] == 1  # block number
    assert isinstance(payload_block_decoded[2], int)  # block flags
    assert payload_block_decoded[3] == 0  # payload block CRC type
    
    # CRITICAL: Verify the payload content matches the binary envelope
    assert payload_block_decoded[4] == pbs_binary_envelope
