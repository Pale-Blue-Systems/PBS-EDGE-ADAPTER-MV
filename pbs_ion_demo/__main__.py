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
the delivered envelopes, and report.json. Exit status 0 means every check
passed. TESTS/ion/test_ion_end_to_end.py is the formal verification; this
program is the demonstration.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from PBS_LINK import HEADER_SIZE, PBSLink, Priority

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

    def step(self, title: str) -> Dict[str, Any]:
        print(f"\n=== {title} ===")
        s: Dict[str, Any] = {"title": title, "checks": []}
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


def find(channel, envelope: bytes):
    for c in channel.captures():
        if decode_bundle(c.data).payload == envelope:
            return c
    return None


def run_open_link(tc: IonToolchain, run_dir: Path, rep: Report) -> None:
    with LunarEarthNetwork(tc, run_dir / "open-link", always_open(3600)) as net:
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
        net.earth.submit(cmd, net.lunar.receive_eid)
        got = net.lunar.receive(1, TIMEOUT_S)
        cap = find(net.emulator["2->1"], cmd)
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
        rep.check(s, "ION delivered the envelope byte-identical", len(got) == 1 and got[0].envelope_bytes == env)


def run_gap(tc: IonToolchain, run_dir: Path, rep: Report, gap_s: int) -> None:
    start = int(time.time()) + gap_s
    with LunarEarthNetwork(tc, run_dir / "contact-gap", [ContactWindow(start, start + 600)]) as net:
        s = rep.step(f"4. Contact gap: no contact for {gap_s} s")
        net.earth.start_receiver(0)
        held = PBSLink(device_id="Rover-Alpha").send(Priority.NORMAL, b"HELD-UNTIL-CONTACT", ttl=120)
        short = PBSLink(device_id="Rover-Alpha").send(Priority.NORMAL, b"EXPIRES-IN-STORAGE", ttl=6)
        net.lunar.submit(held, net.earth.receive_eid)
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
        rep.check(s, "short-lived envelope expired in storage, never sent",
                  find(net.emulator["1->2"], short) is None and tallies.get("exp", 0) >= 1,
                  f"node 1 tallies {tallies}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ion-prefix", help="ION installation prefix (default: $ION_PREFIX or the PATH)")
    ap.add_argument("--run-dir", type=Path,
                    default=Path("ion-demo-runs") / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    ap.add_argument("--gap-s", type=int, default=15, help="length of the contact gap in step 3")
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
        "ion_version": version,
        "ion_release": {"tag": ION_RELEASE_TAG, "commit": ION_RELEASE_COMMIT},
        "steps": rep.steps,
        "failures": rep.failures,
    }, indent=2) + "\n")
    total = sum(len(s["checks"]) for s in rep.steps)
    print(f"\n{total - rep.failures} of {total} checks passed. Report: {run_dir / 'report.json'}")
    return 0 if rep.failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
