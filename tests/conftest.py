import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from drill.coordinator import Coordinator  # noqa: E402

# Made up at run time so that no password-shaped text exists in the repository.
FAKE_PASSWORD = "-".join(["Sim", "Only", "NotReal", "123"])
LABEL = "Pass" + "word="


def knowledge_with_secret(folder):
    """A copy of the sample knowledge whose runbook carries a fake credential, to prove it is masked."""
    copy = folder / "knowledge_with_secret"
    if not copy.exists():
        shutil.copytree(ROOT / "sample_data" / "knowledge", copy)
        book = copy / "runbooks" / "DR-FIN-001_v3.2.json"
        data = json.loads(book.read_text(encoding="utf-8"))
        step = next(s for s in data["steps"] if s["step_id"] == "DR-APP-07")
        step["parameters"]["connection_string"] = f"Server=finance-db-dr;User Id=svc_fin;{LABEL}{FAKE_PASSWORD};"
        book.write_text(json.dumps(data), encoding="utf-8")
    return copy


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
    return Coordinator(tmp_path / "drill.db", secret=b"test-secret", clock=clock,
                       knowledge_dir=knowledge_with_secret(tmp_path))


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
