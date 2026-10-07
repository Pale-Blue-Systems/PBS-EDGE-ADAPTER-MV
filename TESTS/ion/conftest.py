"""
Fixtures for the ION end-to-end tests (DOCS/PBS-ION-E2E-TEST-PLAN.md).

ION is located through $ION_PREFIX or the PATH. Without ION the tests are
skipped, unless PBS_ION_REQUIRED=1, in which case they fail: the CI job
that builds ION sets it, so a missing ION never passes silently.

Each test records its measured values with the `evidence` fixture. At the
end of the session the records, the ION version, the host and the start and
end times are written to $PBS_ION_EVIDENCE_DIR/as-run-<UTC time>.json
(default ion-test-results/). The ION run directories, with every node's
configuration files and ion.log, are kept under the same directory.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import time
from pathlib import Path

import pytest

from pbs_ion_demo.ion_node import IonError, IonToolchain
from pbs_ion_demo.ion_release import ION_RELEASE_COMMIT, ION_RELEASE_TAG

EVIDENCE_DIR = Path(os.environ.get("PBS_ION_EVIDENCE_DIR", "ion-test-results")).resolve()
_RECORDS: dict = {}
_SESSION = {"start_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}


@pytest.fixture(scope="session")
def ion_toolchain() -> IonToolchain:
    try:
        tc = IonToolchain.locate()
    except IonError as e:
        if os.environ.get("PBS_ION_REQUIRED") == "1":
            pytest.fail(f"PBS_ION_REQUIRED=1 and ION is not available: {e}")
        pytest.skip(f"ION not available: {e}")
    _SESSION["ion_version"] = tc.version()
    _SESSION["ion_bin_dir"] = str(tc.bin_dir)
    return tc


@pytest.fixture(scope="session")
def run_root() -> Path:
    root = EVIDENCE_DIR / f"runs-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def evidence(request):
    """A dict the test fills with measured values; saved in the as-run record."""
    record: dict = {}
    _RECORDS[request.node.nodeid] = record
    yield record


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and item.nodeid in _RECORDS:
        _RECORDS[item.nodeid]["outcome"] = rep.outcome
        _RECORDS[item.nodeid]["duration_s"] = round(rep.duration, 3)


def pytest_sessionfinish(session, exitstatus):
    if not _RECORDS:
        return
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    _SESSION.update({
        "end_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "ion_release_tag": ION_RELEASE_TAG,
        "ion_release_commit": ION_RELEASE_COMMIT,
        "host": platform.platform(),
        "python": platform.python_version(),
        "exit_status": int(exitstatus),
    })
    name = f"as-run-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    (EVIDENCE_DIR / name).write_text(
        json.dumps({"session": _SESSION, "tests": _RECORDS}, indent=2, default=str) + "\n"
    )
