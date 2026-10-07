"""
Run the PBS-over-ION end-to-end demonstration and print what happens.

    python -m pbs_ion_demo [--ion-prefix DIR] [--run-dir DIR] [--gap-s N]

Four steps, each checked on observed data:
  1. Downlink: a rover telemetry envelope from the lunar gateway (ipn:1) to
     the Earth gateway (ipn:2) across the emulated 1.2822 s link.
  2. Uplink: a CRITICAL command envelope from Earth to the rover.
  3. Interoperability: a bundle encoded by pbs_edge_adapter_worked_example
     delivered by ION.
  4. Contact gap: an envelope held by ION until a planned contact opens,
     and an envelope whose lifetime ends before it opens.

The run directory keeps every node's ION configuration files and ion.log,
the delivered envelopes, and report.json. For each step, report.json
records the checks and the evidence behind them: each envelope's header
fields and bytes, what the gateway asked ION for, each bundle as captured
on the link (bytes, decoded primary block, blocks, link arrival and release
times) and each delivery. Exit status 0 means every check
passed. TESTS/ion/test_ion_end_to_end.py is the formal verification; this
program is the demonstration.
"""

from __future__ import annotations

import argparse
import datetime
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from PBS_LINK import HEADER_SIZE, PBSLink, Priority, parse_envelope

from pbs_edge_adapter_worked_example import (
    AuthorityContextMap,
    CreationTimestampCounter,
    eid_ipn,
    pbs_to_bpv7_bundle_mv,
)

from .bpv7_wire import decode_bundle, eid_to_text, ion_qos, reserved_flags_set
from .ion_node import IonToolchain
from .ion_release import ION_RELEASE_COMMIT, ION_RELEASE_TAG
from .scenario import ContactWindow, LunarEarthNetwork, always_open

TIMEOUT_S = 30


class Report:
    def __init__(self) -> None:
        self.steps: List[Dict[str, Any]] = []
        self.failures = 0
        self.network: Dict[str, Any] = {}

    def step(self, title: str) -> Dict[str, Any]:
        print(f"\n=== {title} ===")
        s: Dict[str, Any] = {"title": title, "checks": [], "evidence": {}}
        self.steps.append(s)
        return s

    def check(self, step: Dict[str, Any], what: str, ok: bool, detail: str = "") -> None:
        step["checks"].append({"check": what, "pass": bool(ok), "detail": detail})
        self.failures += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {what}" + (f": {detail}" if detail else ""))


def describe_bundle(raw: bytes) -> str:
    b = decode_bundle(raw)
    qos = ion_qos(b)
    blocks = ", ".join(f"type {x.block_type}" for x in b.blocks)
    return (
        f"{eid_to_text(b.source)} -> {eid_to_text(b.destination)}, flags 0x{b.bundle_proc_flags:x}, "
        f"created {b.creation_time_ms} ms DTN time (seq {b.creation_seq}), lifetime {b.lifetime_ms} ms, "
        f"blocks [{blocks}], ION class {qos['class_of_service'] if qos else 'none'}, {len(raw)} bytes"
    )


def envelope_record(env: bytes) -> Dict[str, Any]:
    """Header fields and bytes of one envelope (PBS-ENV-01)."""
    e = parse_envelope(env)
    return {
        "hex": env.hex(),
        "bytes": len(env),
        "source_id": e.source_id,
        "priority": Priority(e.priority).name,
        "priority_value": int(e.priority),
        "timestamp_unix_us": e.timestamp,
        "ttl_s": e.ttl,
        "sequence": e.sequence,
        "payload_bytes": e.size,
        "payload_text": e.payload.decode("ascii", "replace"),
        "crc32": f"0x{e.crc32:08x}",
    }


def bundle_record(raw: bytes, capture=None) -> Dict[str, Any]:
    """A bundle as decoded by bpv7_wire, with the link times if it was captured."""
    b = decode_bundle(raw)
    qos = ion_qos(b)
    rec: Dict[str, Any] = {
        "hex": raw.hex(),
        "bytes": len(raw),
        "source": eid_to_text(b.source),
        "destination": eid_to_text(b.destination),
        "report_to": eid_to_text(b.report_to),
        "bundle_proc_flags": f"0x{b.bundle_proc_flags:x}",
        "primary_crc_type": b.primary_crc_type,
        "creation_time_dtn_ms": b.creation_time_ms,
        "creation_unix_ms": b.creation_unix_ms,
        "creation_seq": b.creation_seq,
        "lifetime_ms": b.lifetime_ms,
        "expiry_unix_ms": b.expiry_unix_ms,
        "blocks": [
            {"type": x.block_type, "number": x.block_number, "flags": x.block_proc_flags,
             "crc_type": x.crc_type, "data_bytes": len(x.data)}
            for x in b.blocks
        ],
        "ion_class_of_service": qos["class_of_service"] if qos else None,
    }
    if capture is not None:
        rec["link"] = {
            "channel": capture.channel,
            "arrival_unix_ns": capture.arrival_unix_ns,
            "release_unix_ns": capture.release_unix_ns,
            "injected": capture.injected,
        }
    return rec


def submission_record(sub) -> Dict[str, Any]:
    return {
        "source_eid": sub.source_eid,
        "destination_eid": sub.destination_eid,
        "clock_unix_us": sub.plan.clock_us,
        "c_us": sub.plan.c_us,
        "lifetime_bound_ms": sub.plan.lifetime_ms_bound,
        "lifespan_s": sub.plan.lifespan_s,
        "ion_class_of_service": sub.plan.class_of_service,
        "bpsendfile_exit_unix_us": sub.exit_unix_us,
    }


def delivery_record(d) -> Dict[str, Any]:
    return {"file": d.file_path.name, "restored_unix_us": d.restored_unix_us, "bytes": len(d.envelope_bytes)}


def find(channel, envelope: bytes):
    for c in channel.captures():
        if not c.injected and decode_bundle(c.data).payload == envelope:
            return c
    return None


def network_record(net: LunarEarthNetwork) -> Dict[str, Any]:
    contacts = net.ion.contacts
    return {
        "owlt_s": net.owlt_s,
        "ion_range_s": contacts[0].owlt_s if contacts else None,
        "contact_rate_bytes_s": contacts[0].rate_bytes_s if contacts else None,
        "nodes": {
            "lunar": {"node": net.lunar_node.number, "send_eid": net.lunar_node.eid(1), "receive_eid": net.lunar_node.eid(2)},
            "earth": {"node": net.earth_node.number, "send_eid": net.earth_node.eid(1), "receive_eid": net.earth_node.eid(2)},
        },
        "convergence_layer": "udp",
    }


def run_open_link(tc: IonToolchain, run_dir: Path, rep: Report) -> None:
    with LunarEarthNetwork(tc, run_dir / "open-link", always_open(3600)) as net:
        rep.network = network_record(net)
        print(f"Nodes up: ipn:1 (lunar) and ipn:2 (Earth); one-way light time {net.owlt_s:.4f} s")
        net.earth.start_receiver(0)
        net.lunar.start_receiver(0)

        s = rep.step("1. Downlink: rover telemetry, lunar gateway -> Earth gateway")
        env = PBSLink(device_id="Rover-Alpha").send(Priority.NORMAL, b"VOLTAGE=119.7,CURRENT=18.2", ttl=120)
        print(f"  envelope header {env[:HEADER_SIZE].hex()}")
        sub = net.lunar.submit(env, net.earth.receive_eid)
        print(f"  bpsendfile {sub.source_eid} -> {sub.destination_eid}: lifetime {sub.plan.lifespan_s} s, "
              f"ION class {sub.plan.class_of_service}")
        got = net.earth.receive(1, TIMEOUT_S)
        cap = find(net.emulator["1->2"], env)
        s["evidence"] = {
            "envelope": envelope_record(env),
            "submission": submission_record(sub),
            "bundle": bundle_record(cap.data, cap) if cap else None,
            "deliveries": [delivery_record(d) for d in got],
        }
        rep.check(s, "delivered byte-identical, header CRC32 verified", len(got) == 1 and got[0].envelope_bytes == env)
        if cap:
            b = decode_bundle(cap.data)
            print(f"  on the wire: {describe_bundle(cap.data)}")
            rep.check(s, "bundle CRCs verify, no reserved flag", reserved_flags_set(b) == 0)
            rep.check(s, "bundle expires no later than the envelope",
                      b.expiry_unix_ms <= sub.plan.envelope_expiry_unix_ms,
                      f"margin {sub.plan.envelope_expiry_unix_ms - b.expiry_unix_ms:.0f} ms")
            rep.check(s, "held on the link for one OWLT",
                      cap.release_unix_ns - cap.arrival_unix_ns >= int(net.owlt_s * 1e9),
                      f"{(cap.release_unix_ns - cap.arrival_unix_ns) / 1e9:.4f} s")
        else:
            rep.check(s, "bundle captured on the link", False)

        s = rep.step("2. Uplink: CRITICAL command, Earth gateway -> lunar gateway")
        cmd = PBSLink(device_id="Earth-Ops").send(Priority.CRITICAL, b"CMD=SAFE_MODE", ttl=300)
        sub = net.earth.submit(cmd, net.lunar.receive_eid)
        got = net.lunar.receive(1, TIMEOUT_S)
        cap = find(net.emulator["2->1"], cmd)
        s["evidence"] = {
            "envelope": envelope_record(cmd),
            "submission": submission_record(sub),
            "bundle": bundle_record(cap.data, cap) if cap else None,
            "deliveries": [delivery_record(d) for d in got],
        }
        rep.check(s, "delivered byte-identical", len(got) == 1 and got[0].envelope_bytes == cmd)
        if cap:
            print(f"  on the wire: {describe_bundle(cap.data)}")
        rep.check(s, "ION class expedited (PBS-DTN-MAP-01 Section 6.3)",
                  bool(cap) and ion_qos(decode_bundle(cap.data))["class_of_service"] == 2)

        s = rep.step("3. Interoperability: worked-example bundle delivered by ION")
        amap = AuthorityContextMap({"luna": {"dest": eid_ipn(2, 2), "src": eid_ipn(1, 0), "report_to": eid_ipn(1, 0)}})
        env = PBSLink(device_id="Rover-Alpha").send(Priority.HIGH, b"ENCODED-BY-WORKED-EXAMPLE", ttl=60)
        raw = pbs_to_bpv7_bundle_mv(env, "luna", amap, sequence_counter=CreationTimestampCounter())
        print(f"  injected: {describe_bundle(raw)}")
        net.emulator["1->2"].inject(raw)
        got = net.earth.receive(1, TIMEOUT_S)
        injected = [c for c in net.emulator["1->2"].captures() if c.injected and c.data == raw]
        s["evidence"] = {
            "envelope": envelope_record(env),
            "bundle": bundle_record(raw, injected[0] if injected else None),
            "encoder": "pbs_edge_adapter_worked_example.pbs_to_bpv7_bundle_mv",
            "deliveries": [delivery_record(d) for d in got],
        }
        rep.check(s, "ION delivered the envelope byte-identical", len(got) == 1 and got[0].envelope_bytes == env)


def run_gap(tc: IonToolchain, run_dir: Path, rep: Report, gap_s: int) -> None:
    start = int(time.time()) + gap_s
    with LunarEarthNetwork(tc, run_dir / "contact-gap", [ContactWindow(start, start + 600)]) as net:
        s = rep.step(f"4. Contact gap: no contact for {gap_s} s")
        net.earth.start_receiver(0)
        held = PBSLink(device_id="Rover-Alpha").send(Priority.NORMAL, b"HELD-UNTIL-CONTACT", ttl=120)
        short = PBSLink(device_id="Rover-Alpha").send(Priority.NORMAL, b"EXPIRES-IN-STORAGE", ttl=6)
        sub_held = net.lunar.submit(held, net.earth.receive_eid)
        sub_short = net.lunar.submit(short, net.earth.receive_eid)
        print(f"  submitted two envelopes {start - time.time():.1f} s before the contact opens; "
              f"the short one has an ION lifetime of {sub_short.plan.lifespan_s} s")
        got = net.earth.receive(1, gap_s + TIMEOUT_S)
        got += net.earth.receive(1, 6)
        cap = find(net.emulator["1->2"], held)
        rep.check(s, "held envelope crossed the link only after the contact opened",
                  bool(cap) and cap.arrival_unix_ns >= start * 1_000_000_000,
                  f"{(cap.arrival_unix_ns / 1e9 - start):.3f} s after" if cap else "not captured")
        rep.check(s, "held envelope delivered byte-identical", [g.envelope_bytes for g in got] == [held])
        tallies = net.lunar_node.bp_tallies()
        s["evidence"] = {
            "contact_start_unix_s": start,
            "contact_end_unix_s": start + 600,
            "held": {
                "envelope": envelope_record(held),
                "submission": submission_record(sub_held),
                "bundle": bundle_record(cap.data, cap) if cap else None,
                "deliveries": [delivery_record(d) for d in got if d.envelope_bytes == held],
            },
            "short": {
                "envelope": envelope_record(short),
                "submission": submission_record(sub_short),
                "bundle": None,
                "deliveries": [delivery_record(d) for d in got if d.envelope_bytes == short],
            },
            "lunar_node_tallies": tallies,
        }
        rep.check(s, "short-lived envelope expired in storage, never sent",
                  find(net.emulator["1->2"], short) is None and tallies.get("exp", 0) >= 1,
                  f"node 1 tallies {tallies}")


def software_record() -> Dict[str, Any]:
    """Versions of the software that produced the report."""
    from importlib.metadata import PackageNotFoundError, version as dist_version

    def dist(name: str) -> str:
        try:
            return dist_version(name)
        except PackageNotFoundError:
            return "not installed"

    repo = Path(__file__).resolve().parents[1]
    try:
        commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=10).stdout.strip() or None
        dirty = bool(subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                                    capture_output=True, text=True, timeout=10).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        commit, dirty = None, None
    return {
        "pbs_edge_adapter_mv_commit": commit,
        "working_tree_modified": dirty,
        "pbs_link": dist("pbs-link"),
        "cbor2": dist("cbor2"),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ion-prefix", help="ION installation prefix (default: $ION_PREFIX or the PATH)")
    ap.add_argument("--run-dir", type=Path,
                    default=Path("ion-demo-runs") / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    ap.add_argument("--gap-s", type=int, default=15, help="length of the contact gap in step 4")
    args = ap.parse_args(argv)

    tc = IonToolchain.locate(args.ion_prefix)
    version = tc.version()
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"ION {version} ({ION_RELEASE_TAG} {ION_RELEASE_COMMIT[:12]}) from {tc.bin_dir}")
    print(f"Run directory: {run_dir}")

    rep = Report()
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    run_open_link(tc, run_dir, rep)
    run_gap(tc, run_dir, rep, args.gap_s)
    rep.steps.sort(key=lambda s: s["title"])
    (run_dir / "report.json").write_text(json.dumps({
        "started_utc": started,
        "finished_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "ion_version": version,
        "ion_release": {"tag": ION_RELEASE_TAG, "commit": ION_RELEASE_COMMIT},
        "software": software_record(),
        "network": rep.network,
        "steps": rep.steps,
        "failures": rep.failures,
    }, indent=2) + "\n")
    total = sum(len(s["checks"]) for s in rep.steps)
    print(f"\n{total - rep.failures} of {total} checks passed. Report: {run_dir / 'report.json'}")
    return 0 if rep.failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
