import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from drill.coordinator import Coordinator  # noqa: E402


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        self.now += timedelta(seconds=1)
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def coord(tmp_path, clock):
    return Coordinator(tmp_path / "drill.db", secret=b"test-secret", clock=clock)


def begin(c, scenario="nominal_success"):
    d = c.create(scenario_id=scenario, coordinator="Asha")["drill_id"]
    c.command(d, "confirm_plan")
    c.command(d, "start", authorized=True, simulation_ack=True)
    return d


def drive(c, d, stop_before=None, max_moves=120):
    """Act as a coordinator who approves everything, until finished, blocked, or at stop_before."""
    for _ in range(max_moves):
        v = c.view(d)
        names = [x["command"] for x in v["controls"]]
        if stop_before and v["current_step_id"] == stop_before:
            return v
        if "approve" in names:
            c.command(d, "approve", request_id=v["approval"]["request_id"], approver="Asha")
        elif "signoff" in names:
            c.command(d, "signoff", approver="Ravi (Finance owner)")
        elif "next" in names:
            c.command(d, "next")
        else:
            return v
    raise AssertionError("drill did not settle")


def kinds(c, d):
    return [e["event_type"] for e in c.store.get_events(d)]
