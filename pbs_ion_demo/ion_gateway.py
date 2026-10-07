"""
PBS gateway functions over an ION 4.2.0 bundle protocol agent.

Outbound (PBS-DTN-MAP-01 Section 6): plan_submission() validates one
PBS-ENV-01 envelope and selects the bundle lifetime and ION class of
service; IonGateway.submit() hands the unmodified envelope to ION with ION's
bpsendfile program, so ION's bundle protocol agent creates the bundle and
assigns its creation timestamp (PBS-DTN-MAP-01 Section 6.1, "Gateway BPA").

Inbound (PBS-DTN-MAP-01 Section 7): IonGateway.receive() collects the
payloads ION's bprecvfile program delivers, and restore_envelope() checks
each one and returns the envelope verbatim (Section 7.2).

Lifetime (PBS-DTN-MAP-01 Section 6.1). ION, not the gateway, assigns the
creation time, so the gateway computes the lifetime first. Section 6.1:
"A gateway that computes the lifetime before its BPA assigns the creation
time meets this bound by using for c_us a time not earlier than that
creation time, such as its clock reading plus the maximum latency of the
transmission request." plan_submission() uses c_us = clock reading +
max_submit_latency_us, and submit() checks that bpsendfile exited within
max_submit_latency_us of that clock reading. bpsendfile creates the bundle
before it exits, so the creation time is not later than c_us.

ION's bp_send() takes the lifetime in whole seconds and multiplies it by
1000 (ION 4.2.0 bpv7/library/libbp.c, bp_send; bpsendfile passes its
<time to live (seconds)> argument to it). The gateway therefore uses
floor(lifetime_ms / 1000) seconds, which does not exceed the Section 6.1
bound, and refuses an envelope for which that is 0 s.

No-expiry lifetime (PBS-DTN-MAP-01 Section 6.1.1). bp_send() declares the
lifetime an int, so the largest lifetime ION accepts through it is
2 147 483 647 s. ION stores the expiration time as a time_t count of
seconds (bpv7/library/bpP.h, Bundle.expirationTime), which is 64 bits on
LP64 Linux, so creation time + 2 147 483 647 s does not overflow there. The
gateway's no-expiry lifetime is ION_NO_EXPIRY_LIFETIME_MS = 2 147 483 647 000
ms, selected for ION 4.2.0 on 64-bit Linux. Every lifetime the gateway
assigns is min(this value, the Section 6.1 bound), so none exceeds it.

Class of service (PBS-DTN-MAP-01 Section 6.3; PBS-DTN-MAP-02 Section 5).
ION offers the three DTN priority classes of RFC 4838 Section 3.5 through
bp_send's classOfService argument: 0 bulk, 1 standard (normal),
2 expedited (ION bp.h BP_BULK_PRIORITY, BP_STD_PRIORITY,
BP_EXPEDITED_PRIORITY). The gateway requests the class Section 6.3's table
gives for the envelope's Priority. DOCS/PBS-ION-MAPPING-PROFILE.md is the
mapping profile.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PBS_LINK import HEADER_SIZE, PBSEnvelope, Priority, parse_envelope

from pbs_edge_adapter_worked_example import (
    EnvelopeExpiredError,
    EnvelopeLengthError,
    bundle_lifetime_ms,
    unix_time_us,
)

from .ion_node import IonError, IonNode

# Largest lifetime bp_send() accepts: INT_MAX seconds (see module docstring).
ION_MAX_LIFESPAN_S = 2_147_483_647
ION_NO_EXPIRY_LIFETIME_MS = ION_MAX_LIFESPAN_S * 1000

# ION class-of-service codes (ION 4.2.0 bpv7/include/bp.h).
ION_BULK = 0
ION_STANDARD = 1
ION_EXPEDITED = 2

# PBS-DTN-MAP-01 Section 6.3 table: PBS Priority -> DTN class (RFC 4838
# Section 3.5), expressed as ION class-of-service codes.
PBS_PRIORITY_TO_ION_COS: Dict[int, int] = {
    Priority.CRITICAL: ION_EXPEDITED,
    Priority.HIGH: ION_EXPEDITED,
    Priority.NORMAL: ION_STANDARD,
    Priority.LOW: ION_BULK,
    Priority.BULK: ION_BULK,
}

# Default bound on the time from the gateway's clock reading to the exit of
# bpsendfile. bpsendfile attaches to ION, creates the bundle and exits; on
# the reference host this takes well under 1 s.
DEFAULT_MAX_SUBMIT_LATENCY_US = 2_000_000


class IonLifetimeGranularityError(EnvelopeExpiredError):
    """Less than 1 s of lifetime remains: ION's bp_send counts whole seconds."""


class SubmitLatencyExceeded(IonError):
    """
    bpsendfile took longer than the latency the lifetime was computed for.

    ION has already accepted the bundle when this is raised, so its expiry
    may be later than the envelope's by up to the excess. It signals that
    max_submit_latency_us is too small for the host and must be raised; it
    is not a per-envelope condition to retry.
    """


@dataclass(frozen=True)
class SubmissionPlan:
    """What the gateway asks ION for, for one envelope."""
    envelope: PBSEnvelope
    envelope_bytes: bytes
    clock_us: int                 # gateway clock reading
    c_us: int                     # clock_us + max_submit_latency_us (Section 6.1)
    lifetime_ms_bound: int        # min(no-expiry lifetime, Section 6.1 bound at c_us)
    lifespan_s: int               # what bpsendfile receives
    class_of_service: int         # ION class of service (Section 6.3 table)

    @property
    def lifetime_ms(self) -> int:
        """The bundle lifetime ION writes: lifespan_s * 1000 (bp_send)."""
        return self.lifespan_s * 1000

    @property
    def envelope_expiry_unix_ms(self) -> Optional[float]:
        """Timestamp + TTL in Unix ms (PBS-ENV-01 Section 12.2); None for TTL 0."""
        if self.envelope.ttl == 0:
            return None
        return self.envelope.timestamp / 1000 + self.envelope.ttl * 1000


def validate_envelope(envelope_bytes: bytes) -> PBSEnvelope:
    """
    PBS_LINK.parse_envelope (magic, header CRC32, priority, payload length:
    PBS-ENV-01 Sections 13, 14) and the one-envelope length check of the
    worked example (PBS-DTN-MAP-01 Sections 5.1, 6.2).
    """
    envelope = parse_envelope(envelope_bytes)
    if len(envelope_bytes) != HEADER_SIZE + envelope.size:
        raise EnvelopeLengthError(
            f"Input is {len(envelope_bytes)} bytes; header Size gives {HEADER_SIZE + envelope.size}"
        )
    return envelope


def plan_submission(
    envelope_bytes: bytes,
    clock_us: int,
    max_submit_latency_us: int = DEFAULT_MAX_SUBMIT_LATENCY_US,
    no_expiry_lifetime_ms: int = ION_NO_EXPIRY_LIFETIME_MS,
) -> SubmissionPlan:
    """
    Select lifetime and class of service for one envelope.

    Raises the PBS_LINK validation errors, EnvelopeLengthError,
    EnvelopeExpiredError (expired, or less than 1 ms left at c_us),
    IonLifetimeGranularityError (less than 1 s left at c_us), and ValueError
    for a negative latency or a no-expiry lifetime outside
    1..ION_NO_EXPIRY_LIFETIME_MS.
    """
    if max_submit_latency_us < 0:
        raise ValueError("max_submit_latency_us must be non-negative")
    if not 1 <= no_expiry_lifetime_ms <= ION_NO_EXPIRY_LIFETIME_MS:
        raise ValueError(
            f"no_expiry_lifetime_ms must be 1 to {ION_NO_EXPIRY_LIFETIME_MS} ms, "
            "the largest lifetime ION bp_send accepts"
        )
    envelope = validate_envelope(envelope_bytes)
    c_us = clock_us + max_submit_latency_us
    bound_ms = bundle_lifetime_ms(envelope, c_us, no_expiry_lifetime_ms)
    lifespan_s = bound_ms // 1000
    if lifespan_s < 1:
        raise IonLifetimeGranularityError(
            f"{bound_ms} ms of lifetime remain at bundle creation; ION bp_send takes whole seconds"
        )
    return SubmissionPlan(
        envelope=envelope,
        envelope_bytes=bytes(envelope_bytes),
        clock_us=clock_us,
        c_us=c_us,
        lifetime_ms_bound=bound_ms,
        lifespan_s=lifespan_s,
        class_of_service=PBS_PRIORITY_TO_ION_COS[envelope.priority],
    )


@dataclass(frozen=True)
class Submission:
    plan: SubmissionPlan
    source_eid: str
    destination_eid: str
    spool_path: Path
    exit_unix_us: int


@dataclass(frozen=True)
class Delivery:
    """One envelope restored from a delivered bundle payload."""
    envelope: PBSEnvelope
    envelope_bytes: bytes
    file_path: Path
    restored_unix_us: int


class EnvelopeRestoreError(ValueError):
    """A delivered payload is not an envelope PBS-native routing may accept."""


def restore_envelope(payload: bytes, clock_us: int) -> PBSEnvelope:
    """
    Inbound checks on a delivered payload (PBS-DTN-MAP-01 Sections 7.2,
    7.3): the payload is one valid envelope (magic, header CRC32, priority,
    length), and an envelope with TTL > 0 has not expired: its age is not
    more than TTL seconds (PBS-ENV-01 Section 12.2; time spent in the DTN
    domain counts, PBS-DTN-MAP-01 Section 7.3). The envelope is returned
    unmodified; TTL is not changed (Section 7.3).
    """
    envelope = validate_envelope(payload)
    if envelope.ttl and clock_us - envelope.timestamp > envelope.ttl * 1_000_000:
        raise EnvelopeRestoreError(
            f"Envelope expired in transit: age {clock_us - envelope.timestamp} us > TTL {envelope.ttl} s"
        )
    return envelope


class IonGateway:
    """
    The PBS gateway function of one ION node: sends from ipn:N.1 and
    receives on ipn:N.2.
    """

    SEND_SERVICE = 1
    RECEIVE_SERVICE = 2

    def __init__(
        self,
        node: IonNode,
        max_submit_latency_us: int = DEFAULT_MAX_SUBMIT_LATENCY_US,
        clock_us: Callable[[], int] = unix_time_us,
    ) -> None:
        self.node = node
        self.max_submit_latency_us = max_submit_latency_us
        self.clock_us = clock_us
        self.spool = node.directory / "spool"
        self.spool.mkdir(exist_ok=True)
        self.inbox = node.directory / "inbox"
        self.inbox.mkdir(exist_ok=True)
        self._spooled = 0
        self._receiver: Optional[subprocess.Popen] = None
        self._collected = 0

    @property
    def send_eid(self) -> str:
        return self.node.eid(self.SEND_SERVICE)

    @property
    def receive_eid(self) -> str:
        return self.node.eid(self.RECEIVE_SERVICE)

    def submit(self, envelope_bytes: bytes, destination_eid: str) -> Submission:
        """
        Hand one envelope to ION: bpsendfile <send EID> <destination>
        <spool file> 0.<class of service> <lifespan s>.

        The spool file stays in place: bpsendfile gives ION a reference to
        the file (zco_create_file_ref), and ION reads the payload from it
        when it transmits the bundle, which can be after a contact gap.
        """
        clock = self.clock_us()
        plan = plan_submission(envelope_bytes, clock, self.max_submit_latency_us)
        self._spooled += 1
        spool_path = self.spool / f"envelope-{self._spooled:04d}.pbs"
        spool_path.write_bytes(plan.envelope_bytes)
        # Class-of-service string <custody-requested>.<priority>
        # (BP_PARSE_QUALITY_OF_SERVICE_USAGE, ION bp.h): no custody.
        cos = f"0.{plan.class_of_service}"
        cp = self.node.run(
            ["bpsendfile", self.send_eid, destination_eid, str(spool_path), cos, str(plan.lifespan_s)],
            timeout_s=max(5.0, self.max_submit_latency_us / 1e6 + 5),
            check=False,
        )
        exit_us = self.clock_us()
        # bpsendfile writes "[i] bpsendfile sent '<file>', size <n>." to
        # ion.log only after bp_send() accepts the bundle. Its exit status
        # is not enough: it exits 0 when it cannot create the payload ZCO
        # (ION 4.2.0 bpv7/utils/bpsendfile.c).
        accepted = f"bpsendfile sent '{spool_path}', size {len(plan.envelope_bytes)}."
        if cp.returncode != 0 or accepted not in self.node.ion_log():
            raise IonError(
                f"ION did not accept {spool_path.name} (bpsendfile exit {cp.returncode}); see "
                f"{self.node.directory / 'ion.log'}: {cp.stdout.strip()} {cp.stderr.strip()}"
            )
        if exit_us - clock > self.max_submit_latency_us:
            raise SubmitLatencyExceeded(
                f"bpsendfile took {exit_us - clock} us, more than the {self.max_submit_latency_us} us "
                "the lifetime was computed for (PBS-DTN-MAP-01 Section 6.1)"
            )
        return Submission(plan, self.send_eid, destination_eid, spool_path, exit_us)

    def start_receiver(self, max_files: int) -> None:
        """
        Start bprecvfile on the receive EID; it exits after max_files
        payloads (0: no limit). Each bprecvfile process numbers its files
        from testfile1, so the gateway restarts its count and removes any
        testfile left by an earlier receiver; receive() has already moved
        every file it collected to the inbox.
        """
        if self._receiver is not None:
            raise IonError("receiver already running")
        for stale in self.node.directory.glob("testfile*"):
            stale.unlink()
        self._collected = 0
        self._receiver = self.node.popen(
            ["bprecvfile", self.receive_eid, str(max_files)], "bprecvfile.log"
        )

    def stop_receiver(self) -> None:
        if self._receiver is None:
            return
        if self._receiver.poll() is None:
            self._receiver.terminate()
            try:
                self._receiver.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._receiver.kill()
                self._receiver.wait(timeout=10)
        self._receiver = None

    def receive(self, count: int, timeout_s: float, poll_s: float = 0.05) -> List[Delivery]:
        """
        Wait for count payloads from bprecvfile, move each to the inbox and
        restore the envelope. bprecvfile names its files testfile1,
        testfile2, ... in the node directory (ION 4.2.0 bprecvfile.c) and
        writes each in full before naming the next. A payload that fails
        restore_envelope raises EnvelopeRestoreError or a PBS_LINK error.
        """
        deadline = time.monotonic() + timeout_s
        deliveries: List[Delivery] = []
        while len(deliveries) < count and time.monotonic() < deadline:
            name = self.node.directory / f"testfile{self._collected + 1}"
            receiver_done = self._receiver is not None and self._receiver.poll() is not None
            nxt = self.node.directory / f"testfile{self._collected + 2}"
            if name.exists() and (nxt.exists() or receiver_done or self._file_complete(name)):
                self._collected += 1
                target = self.inbox / f"delivery-{self._collected:04d}.pbs"
                os.replace(name, target)
                payload = target.read_bytes()
                now = self.clock_us()
                envelope = restore_envelope(payload, now)
                deliveries.append(Delivery(envelope, payload, target, now))
                continue
            time.sleep(poll_s)
        return deliveries

    def _file_complete(self, path: Path) -> bool:
        """
        bprecvfile logs "has created '<name>'" after its last write() to the
        file and just before close() (ION 4.2.0 bpv7/utils/bprecvfile.c), so
        the file's contents are complete when the message appears.
        """
        log = self.node.ion_log()
        return f"has created '{path.name}'" in log
