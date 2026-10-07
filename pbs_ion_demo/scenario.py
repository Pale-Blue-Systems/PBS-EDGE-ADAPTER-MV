"""
The demonstration network: two ION nodes and the emulated Earth-Moon link.

    node 1 (lunar PBS gateway)                 node 2 (Earth PBS gateway)
    udpclo -> [channel "1->2": OWLT] -> udpcli
    udpcli <- [channel "2->1": OWLT] <- udpclo

LunarEarthNetwork starts the link emulator and both nodes with a contact
plan given in absolute Unix seconds, and stops them in reverse order.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from .ion_gateway import IonGateway
from .ion_node import Contact, IonNetwork, IonToolchain
from .link_emulator import EARTH_MOON_OWLT_S, LinkChannel, LinkEmulator, free_udp_port

LUNAR_NODE = 1
EARTH_NODE = 2

# Contact data rate, bytes per second, in each direction. The demonstration
# sends envelopes of a few hundred bytes; the rate only has to exceed that.
DEFAULT_RATE_BYTES_S = 125_000


@dataclass(frozen=True)
class ContactWindow:
    """Both directions of the link are planned open from start to end (Unix s)."""
    start_unix_s: int
    end_unix_s: int


class LunarEarthNetwork:
    def __init__(
        self,
        toolchain: IonToolchain,
        run_dir: Path,
        windows: Sequence[ContactWindow],
        owlt_s: float = EARTH_MOON_OWLT_S,
        rate_bytes_s: int = DEFAULT_RATE_BYTES_S,
    ) -> None:
        self.owlt_s = owlt_s
        self.windows = list(windows)
        used: set = set()
        ports = []
        for _ in range(4):
            p = free_udp_port(exclude=used)
            used.add(p)
            ports.append(p)
        lunar_in, earth_in, emu_to_earth, emu_to_lunar = ports
        self.emulator = LinkEmulator([
            LinkChannel("1->2", emu_to_earth, earth_in, owlt_s),
            LinkChannel("2->1", emu_to_lunar, lunar_in, owlt_s),
        ])
        self.ion = IonNetwork(toolchain, run_dir)
        self.lunar_node = self.ion.add_node(LUNAR_NODE, lunar_in, {EARTH_NODE: emu_to_earth})
        self.earth_node = self.ion.add_node(EARTH_NODE, earth_in, {LUNAR_NODE: emu_to_lunar})
        # ION ranges are whole seconds; ceil keeps CGR's arrival estimates
        # no earlier than the emulated arrival.
        ion_owlt = max(1, math.ceil(owlt_s)) if owlt_s > 0 else 0
        for w in self.windows:
            for a, b in ((LUNAR_NODE, EARTH_NODE), (EARTH_NODE, LUNAR_NODE)):
                self.ion.add_contact(Contact(a, b, w.start_unix_s, w.end_unix_s, rate_bytes_s, ion_owlt))
        self.lunar: Optional[IonGateway] = None
        self.earth: Optional[IonGateway] = None

    def start(self) -> "LunarEarthNetwork":
        self.emulator.start()
        try:
            self.ion.start()
        except Exception:
            self.emulator.stop()
            raise
        self.lunar = IonGateway(self.lunar_node)
        self.earth = IonGateway(self.earth_node)
        return self

    def stop(self) -> None:
        for gw in (self.lunar, self.earth):
            if gw is not None:
                gw.stop_receiver()
        self.ion.stop()
        self.emulator.stop()

    def __enter__(self) -> "LunarEarthNetwork":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def always_open(duration_s: int = 3600, lead_s: int = 0) -> List[ContactWindow]:
    """One window from now (minus 1 s) for duration_s seconds."""
    now = int(time.time())
    return [ContactWindow(now - 1 + lead_s, now + lead_s + duration_s)]
