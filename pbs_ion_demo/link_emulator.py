"""
Space-link emulator for the ION demonstration.

Each LinkChannel listens on one local UDP port, holds every datagram for a
fixed one-way light time (OWLT), then sends it to one target port. It
records every datagram it carries, with the host clock reading at arrival
and at release, so the tests can decode the bundles ION puts on the wire
and check when they crossed the link.

ION's UDP convergence layer sends each bundle in one UDP datagram with no
further framing (ION 4.2.0 bpv7/udp/libudpcla.c, sendBundleByUDP: "Send the
bundle in a single UDP datagram"), so each captured datagram is one
serialized bundle.

The emulator adds delay only. Whether a contact is open is decided by ION's
contact plan: the sending node does not transmit outside a contact. The
emulator records any datagram it carries, so a transmission outside a
planned contact is visible in the capture.
"""

from __future__ import annotations

import heapq
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

# Mean Earth-Moon distance 384 400 km (NASA NSSDCA Moon Fact Sheet,
# semimajor axis) divided by the speed of light, 299 792 458 m/s exactly
# (BIPM SI Brochure, 9th edition, 2019): 1.2822 s.
EARTH_MOON_MEAN_DISTANCE_M = 384_400_000
SPEED_OF_LIGHT_M_S = 299_792_458
EARTH_MOON_OWLT_S = EARTH_MOON_MEAN_DISTANCE_M / SPEED_OF_LIGHT_M_S


@dataclass(frozen=True)
class Capture:
    """One datagram carried by a channel."""
    channel: str
    seq: int                 # order of arrival on this channel, from 0
    arrival_unix_ns: int     # host clock when the datagram reached the emulator
    release_unix_ns: int     # host clock when the emulator sent it on
    data: bytes
    injected: bool = False   # put on the link by inject(), not received from a node


class LinkChannel:
    """One direction of the emulated link: listen_port -> (OWLT) -> target_port."""

    def __init__(
        self,
        name: str,
        listen_port: int,
        target_port: int,
        owlt_s: float,
        host: str = "127.0.0.1",
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        if owlt_s < 0:
            raise ValueError("One-way light time must be non-negative")
        self.name = name
        self.owlt_ns = int(round(owlt_s * 1e9))
        self._target = (host, target_port)
        self._clock_ns = clock_ns
        self._rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rx.bind((host, listen_port))
        self._rx.settimeout(0.05)
        self._tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._pending: List[Tuple[int, int, int, bytes, bool]] = []  # (due, seq, arrival, data, injected)
        self._captures: List[Capture] = []
        self._seq = 0
        self._stop = threading.Event()
        self._threads = [
            threading.Thread(target=self._receive_loop, name=f"{name}-rx", daemon=True),
            threading.Thread(target=self._release_loop, name=f"{name}-tx", daemon=True),
        ]

    @property
    def listen_port(self) -> int:
        return self._rx.getsockname()[1]

    def start(self) -> "LinkChannel":
        for t in self._threads:
            t.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        for t in self._threads:
            t.join(timeout=5)
        self._rx.close()
        self._tx.close()

    def inject(self, data: bytes) -> None:
        """
        Carry bytes over this channel as if they had arrived on listen_port.
        The capture is marked injected, so that tests can tell bundles
        written by a node from bytes they supplied themselves.
        """
        self._enqueue(bytes(data), injected=True)

    def captures(self) -> List[Capture]:
        with self._lock:
            return list(self._captures)

    def wait_for_captures(self, count: int, timeout_s: float) -> List[Capture]:
        """Wait until at least count datagrams have been released, or timeout."""
        deadline = time.monotonic() + timeout_s
        with self._cv:
            while len(self._captures) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cv.wait(remaining)
            return list(self._captures)

    def _enqueue(self, data: bytes, injected: bool = False) -> None:
        arrival = self._clock_ns()
        with self._cv:
            seq = self._seq
            self._seq += 1
            heapq.heappush(self._pending, (arrival + self.owlt_ns, seq, arrival, data, injected))
            self._cv.notify_all()

    def _receive_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, _ = self._rx.recvfrom(65_535)
            except socket.timeout:
                continue
            except OSError:
                return
            self._enqueue(data)

    def _release_loop(self) -> None:
        while True:
            with self._cv:
                while not self._stop.is_set():
                    if self._pending:
                        wait_s = (self._pending[0][0] - self._clock_ns()) / 1e9
                        if wait_s <= 0:
                            break
                        self._cv.wait(min(wait_s, 0.05))
                    else:
                        self._cv.wait(0.05)
                if self._stop.is_set():
                    return
                _, seq, arrival, data, injected = heapq.heappop(self._pending)
            try:
                self._tx.sendto(data, self._target)
            except OSError:
                pass  # UDP: a send failure is a lost datagram, as on a real link
            release = self._clock_ns()
            with self._cv:
                self._captures.append(Capture(self.name, seq, arrival, release, data, injected))
                self._cv.notify_all()


class LinkEmulator:
    """A bidirectional link made of two LinkChannels."""

    def __init__(self, channels: List[LinkChannel]) -> None:
        self.channels = {c.name: c for c in channels}

    def start(self) -> "LinkEmulator":
        for c in self.channels.values():
            c.start()
        return self

    def stop(self) -> None:
        for c in self.channels.values():
            c.stop()

    def __getitem__(self, name: str) -> LinkChannel:
        return self.channels[name]


def free_udp_port(host: str = "127.0.0.1", exclude: Optional[set] = None) -> int:
    """Return a UDP port that is free on host at the time of the call."""
    exclude = exclude or set()
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind((host, 0))
            port = s.getsockname()[1]
        if port not in exclude:
            return port
