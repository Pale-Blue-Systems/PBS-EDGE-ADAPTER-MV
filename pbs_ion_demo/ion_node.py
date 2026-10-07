"""
Configuration and process control for a network of ION 4.2.0 nodes on one host.

IonNetwork writes each node's ION configuration files (ionconfig, ionrc,
ionsecrc, bprc, ipnrc), starts the node with the ION administration programs
(ionadmin, ionsecadmin, bpadmin, ipnadmin) and stops it with "bpadmin ." and
"ionadmin .". Every node uses the UDP convergence layer; each node's
outduct sends to a port of the link emulator, which forwards to the peer's
induct after the one-way light time.

Several ION nodes share one host by using distinct shared-memory keys
(wmKey) and SDR names, and by setting ION_NODE_LIST_DIR: ION then records
each node in the file ion_nodes in that directory and selects the node for
an ION program by the program's working directory. Every ION program is
therefore run with cwd set to its node's directory (the method of ION's own
multi-node tests, e.g. tests/ipn-exit-route/dotest in ION 4.2.0).

This module never runs killm, which stops every ION process on the host.
Each node's System V shared-memory segments use keys the harness chooses
and records (wmKey, sdrWmKey, heapKey, logKey in ionconfig), chosen so
that no segment with that key exists when the node is configured. When
the node stops, the harness removes the segments with its own keys and
no attached process, so a run neither leaks memory nor leaves a stale
segment that a later node could attach to. ION's host-wide segments and
semaphores, shared by every ION node on the host, are left in place.
"""

from __future__ import annotations

import datetime
import ctypes
import ctypes.util
import os
import re
import secrets
import signal
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# Programs the demonstration runs; all are installed by ION 4.2.0 "make install".
ION_PROGRAMS = (
    "ionadmin", "ionsecadmin", "bpadmin", "ipnadmin",
    "bpsendfile", "bprecvfile", "bpstats", "udpcli", "udpclo",
)


class IonError(RuntimeError):
    """An ION program failed or ION did not reach the expected state."""


@dataclass(frozen=True)
class IonToolchain:
    """Location of an ION installation."""
    bin_dir: Path
    lib_dir: Optional[Path]

    @classmethod
    def locate(cls, prefix: Optional[str] = None) -> "IonToolchain":
        """
        Find ION from prefix, else $ION_PREFIX, else the PATH.

        Raises IonError if any program in ION_PROGRAMS is missing.
        """
        prefix = prefix or os.environ.get("ION_PREFIX")
        if prefix:
            bin_dir = Path(prefix) / "bin"
            lib_dir: Optional[Path] = Path(prefix) / "lib"
        else:
            found = shutil.which("ionadmin")
            if not found:
                raise IonError("ION not found: set ION_PREFIX or put ionadmin on the PATH")
            bin_dir = Path(found).resolve().parent
            lib_dir = bin_dir.parent / "lib"
        missing = [p for p in ION_PROGRAMS if not (bin_dir / p).is_file()]
        if missing:
            raise IonError(f"ION installation at {bin_dir} lacks {missing}")
        return cls(bin_dir, lib_dir if lib_dir and lib_dir.is_dir() else None)

    def version(self) -> str:
        """
        Return ION's version string, e.g. "ION-OPEN-SOURCE-4.2.0": the
        ionadmin "v" command prints IONVERSIONNUMBER (ici/utils/ionadmin.c).
        Run in an empty directory, so that the ion.log it writes is discarded.
        """
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ)
            env.pop("ION_NODE_LIST_DIR", None)
            if self.lib_dir:
                env["LD_LIBRARY_PATH"] = f"{self.lib_dir}{os.pathsep}{env.get('LD_LIBRARY_PATH', '')}"
            cp = subprocess.run([str(self.bin_dir / "ionadmin")], input="v\nq\n", cwd=d, env=env,
                                capture_output=True, text=True, timeout=30)
        m = re.search(r"ION-OPEN-SOURCE-[0-9][0-9A-Za-z.\-]*", cp.stdout + cp.stderr)
        if not m:
            raise IonError(f"ionadmin did not report a version: {cp.stdout!r}")
        return m.group(0)


@dataclass(frozen=True)
class Contact:
    """
    One scheduled contact, from_node -> to_node (ionadmin "a contact" and
    "a range"). Times are Unix seconds; ION receives them as absolute UTC
    times yyyy/mm/dd-hh:mm:ss, so whole seconds only.
    """
    from_node: int
    to_node: int
    start_unix_s: int
    end_unix_s: int
    rate_bytes_s: int
    owlt_s: int


def ion_utc(unix_s: int) -> str:
    """Format Unix seconds as an ION absolute UTC time, yyyy/mm/dd-hh:mm:ss."""
    t = datetime.datetime.fromtimestamp(unix_s, tz=datetime.timezone.utc)
    return t.strftime("%Y/%m/%d-%H:%M:%S")


@dataclass
class IonNode:
    """One ION node and the files that configure it."""
    number: int
    directory: Path
    induct_port: int
    peer_ports: Dict[int, int]          # peer node number -> emulator port toward it
    keys: Dict[str, int]                # ionconfig key name -> System V key
    sdr_name: str
    endpoints: Sequence[int] = (0, 1, 2)
    network: "IonNetwork" = field(repr=False, default=None)  # type: ignore[assignment]

    def eid(self, service: int) -> str:
        return f"ipn:{self.number}.{service}"

    # -- configuration -------------------------------------------------

    def render(self, contacts: Sequence[Contact]) -> Dict[str, str]:
        n = self.number
        ionconfig = (
            f"wmKey {self.keys['wmKey']}\n"
            f"sdrName {self.sdr_name}\n"
            "wmSize 8000000\n"
            f"sdrWmKey {self.keys['sdrWmKey']}\n"
            "configFlags 1\n"       # SDR in DRAM only (ionconfig(5))
            "heapWords 400000\n"
            f"heapKey {self.keys['heapKey']}\n"
            f"logKey {self.keys['logKey']}\n"
            f"pathName {self.directory}\n"
        )
        ionrc = [f"1 {n} node.ionconfig", "s", "m horizon +0"]
        for c in contacts:
            ionrc.append(
                f"a contact {ion_utc(c.start_unix_s)} {ion_utc(c.end_unix_s)} "
                f"{c.from_node} {c.to_node} {c.rate_bytes_s}"
            )
            ionrc.append(
                f"a range {ion_utc(c.start_unix_s)} {ion_utc(c.end_unix_s)} "
                f"{c.from_node} {c.to_node} {c.owlt_s}"
            )
        bprc = ["1", "a scheme ipn 'ipnfw' 'ipnadminep'"]
        # "q": a bundle for an endpoint no application has open is queued
        # until one opens it (bpadmin(1)).
        bprc += [f"a endpoint ipn:{n}.{s} q" for s in self.endpoints]
        bprc += [
            "a protocol udp 1400 100",
            f"a induct udp 127.0.0.1:{self.induct_port} udpcli",
        ]
        bprc += [f"a outduct udp 127.0.0.1:{p} udpclo" for p in self.peer_ports.values()]
        bprc.append("s")
        ipnrc = [f"a plan {peer} udp/127.0.0.1:{port}" for peer, port in self.peer_ports.items()]
        return {
            "node.ionconfig": ionconfig,
            "node.ionrc": "\n".join(ionrc) + "\n",
            "node.ionsecrc": "1\n",
            "node.bprc": "\n".join(bprc) + "\n",
            "node.ipnrc": "\n".join(ipnrc) + "\n",
        }

    # -- process control -----------------------------------------------

    def run(self, argv: List[str], input_text: Optional[str] = None,
            timeout_s: float = 60, check: bool = True) -> subprocess.CompletedProcess:
        """
        Run an ION program in this node's directory.

        Output goes to temporary files, not pipes: ionadmin and bpadmin
        start daemons that inherit their standard output, so a pipe would
        not reach end-of-file until the node stops.
        """
        with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
            rc = subprocess.run(
                [str(self.network.toolchain.bin_dir / argv[0]), *argv[1:]],
                cwd=self.directory, env=self.network.env(), input=input_text,
                stdout=out, stderr=err, text=True, timeout=timeout_s,
            ).returncode
            out.seek(0)
            err.seek(0)
            cp = subprocess.CompletedProcess(argv, rc, out.read(), err.read())
        if check and cp.returncode != 0:
            raise IonError(f"node {self.number}: {' '.join(argv)} exited {cp.returncode}: {cp.stderr.strip()}")
        return cp

    def popen(self, argv: List[str], log_name: str) -> subprocess.Popen:
        """Start an ION program in this node's directory, output to log_name."""
        log = open(self.directory / log_name, "w")
        return subprocess.Popen(
            [str(self.network.toolchain.bin_dir / argv[0]), *argv[1:]],
            cwd=self.directory, env=self.network.env(), stdout=log, stderr=subprocess.STDOUT,
        )

    # Messages with which the administration programs report a failed
    # initialization or start while still exiting 0 (their exit status is
    # set only by the "t" command).
    START_FAILURES = ("can't initialize", "wrong profile", "can't start", "can't attach")

    def start(self) -> None:
        # "1" in each file initializes, "s" starts the daemons.
        for program, rc in (("ionadmin", "node.ionrc"), ("ionsecadmin", "node.ionsecrc"),
                            ("bpadmin", "node.bprc"), ("ipnadmin", "node.ipnrc")):
            cp = self.run([program, rc], check=False)
            output = cp.stdout + cp.stderr
            with (self.directory / "start.log").open("a") as log:
                log.write(output)
            failed = [m for m in self.START_FAILURES if m in output.lower()]
            if cp.returncode != 0 or failed:
                raise IonError(
                    f"node {self.number}: {program} {rc} exited {cp.returncode}"
                    + (f" reporting {failed}" if failed else "")
                    + f"; see {self.directory / 'start.log'}"
                )

    def bp_is_running(self, wait_s: int = 30) -> bool:
        """
        bpadmin "t p <s>": poll up to s seconds for BP to be running; bpadmin
        exits 1 if it is running and 0 if not (ION system_up script).
        """
        cp = self.run(["bpadmin"], input_text=f"t p {wait_s}\n", timeout_s=wait_s + 10, check=False)
        return cp.returncode == 1

    def stop(self, wait_s: float = 15) -> None:
        """
        Stop BP ("bpadmin .") and ION ("ionadmin ."), wait for this node's
        processes to exit, end any that remain, then remove this node's
        shared-memory segments.
        """
        self.run(["bpadmin", "."], timeout_s=60, check=False)
        self.run(["ionadmin", "."], timeout_s=60, check=False)
        deadline = time.monotonic() + wait_s
        while self.processes() and time.monotonic() < deadline:
            time.sleep(0.2)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for pid in self.processes():
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
            end = time.monotonic() + 5
            while self.processes() and time.monotonic() < end:
                time.sleep(0.1)
        remove_shm_segments(set(self.keys.values()))

    def processes(self) -> List[int]:
        """PIDs of processes whose working directory is this node's directory (Linux /proc)."""
        pids = []
        for entry in os.listdir("/proc"):
            if not entry.isdigit() or int(entry) == os.getpid():
                continue
            try:
                if os.readlink(f"/proc/{entry}/cwd") == str(self.directory):
                    pids.append(int(entry))
            except OSError:
                continue
        return pids

    def ion_log(self) -> str:
        p = self.directory / "ion.log"
        return p.read_text(errors="replace") if p.exists() else ""

    def bp_tallies(self, settle_s: float = 2.0) -> Dict[str, int]:
        """
        Run bpstats and return the bundle counts of its latest tally lines
        in ion.log: {"src", "fwd", "xmt", "rcv", "dlv", "rfw", "exp"}, each
        the "(+)" total bundle count since the node started. bpclock writes
        tallies to the SDR once a second, so the call waits settle_s before
        running bpstats.
        """
        time.sleep(settle_s)
        self.run(["bpstats"], timeout_s=30)
        tallies: Dict[str, int] = {}
        pattern = re.compile(r"\[x\] (\w{3}) from .*\(\+\)\s+(\d+)\s+(\d+)")
        for line in self.ion_log().splitlines():
            m = pattern.search(line)
            if m:
                tallies[m.group(1)] = int(m.group(2))
        return tallies


def shm_segments() -> Dict[int, Tuple[int, int]]:
    """System V shared-memory segments: {key: (shmid, attached processes)} (Linux /proc)."""
    segments: Dict[int, Tuple[int, int]] = {}
    with open("/proc/sysvipc/shm") as f:
        header = f.readline().split()
        k, i, n = header.index("key"), header.index("shmid"), header.index("nattch")
        for line in f:
            cols = line.split()
            segments[int(cols[k])] = (int(cols[i]), int(cols[n]))
    return segments


def remove_shm_segments(keys: set) -> List[int]:
    """Remove the segments with these keys that no process has attached; return their keys."""
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    removed = []
    for key, (shmid, nattch) in shm_segments().items():
        if key in keys and nattch == 0:
            if libc.shmctl(ctypes.c_int(shmid), ctypes.c_int(0), None) == 0:  # IPC_RMID
                removed.append(key)
    return removed


def allocate_keys(names: Sequence[str], exclude: set) -> Dict[str, int]:
    """
    Random System V keys, one per name, that no existing segment uses and
    that are not in exclude. Keys are drawn from 0x10000000-0x6FFFFFFF,
    clear of ION's default keys (e.g. 65281) and of the small keys
    sm_GetUniqueKey() assigns.
    """
    in_use = set(shm_segments()) | set(exclude)
    keys: Dict[str, int] = {}
    for name in names:
        while True:
            key = 0x10000000 + secrets.randbelow(0x60000000)
            if key not in in_use:
                in_use.add(key)
                keys[name] = key
                break
    return keys


class IonNetwork:
    """
    A set of ION nodes on one host, each node in its own directory under
    run_dir, all registered in run_dir/ion_nodes.
    """

    _sdr_counter = 0

    def __init__(self, toolchain: IonToolchain, run_dir: Path) -> None:
        self.toolchain = toolchain
        self.run_dir = Path(run_dir).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.nodes: Dict[int, IonNode] = {}
        self.contacts: List[Contact] = []
        self._started: List[IonNode] = []

    def env(self) -> Dict[str, str]:
        env = dict(os.environ)
        env["ION_NODE_LIST_DIR"] = str(self.run_dir)
        env["PATH"] = f"{self.toolchain.bin_dir}{os.pathsep}{env.get('PATH', '')}"
        if self.toolchain.lib_dir:
            env["LD_LIBRARY_PATH"] = f"{self.toolchain.lib_dir}{os.pathsep}{env.get('LD_LIBRARY_PATH', '')}"
        return env

    def add_node(self, number: int, induct_port: int, peer_ports: Dict[int, int]) -> IonNode:
        IonNetwork._sdr_counter += 1
        taken = {k for n in self.nodes.values() for k in n.keys.values()}
        node = IonNode(
            number=number,
            directory=self.run_dir / f"node{number}",
            induct_port=induct_port,
            peer_ports=dict(peer_ports),
            keys=allocate_keys(("wmKey", "sdrWmKey", "heapKey", "logKey"), taken),
            sdr_name=f"pbsion{os.getpid()}n{number}s{IonNetwork._sdr_counter}",
        )
        node.network = self
        node.directory.mkdir(parents=True, exist_ok=True)
        self.nodes[number] = node
        return node

    def add_contact(self, contact: Contact) -> None:
        self.contacts.append(contact)

    def start(self, wait_s: int = 30) -> None:
        for node in self.nodes.values():
            for name, text in node.render(self.contacts).items():
                (node.directory / name).write_text(text)
        try:
            for node in self.nodes.values():
                self._started.append(node)
                node.start()
                if not node.bp_is_running(wait_s):
                    raise IonError(f"node {node.number}: BP not running after {wait_s} s")
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        for node in reversed(self._started):
            try:
                node.stop()
            except Exception:  # keep stopping the other nodes
                pass
        self._started.clear()

    def __enter__(self) -> "IonNetwork":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
