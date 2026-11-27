"""Scenario outcomes, durability, metrics, audit integrity, runbook validation and retrieval."""
import json
import sqlite3
from pathlib import Path

import pytest

from conftest import begin, drive, kinds
from drill.coordinator import Coordinator, DrillError
from drill.knowledge import Knowledge

ROOT = Path(__file__).resolve().parents[1]


def finish(c, d):
    """Take whatever recovery option is offered until the drill reaches a terminal state."""
    for _ in range(40):
        v = drive(c, d)
        names = [x["command"] for x in v["controls"]]
        for choice in ("reconcile", "retry", "escalate"):
            if choice in names:
                c.command(d, choice)
                break
        else:
            return v
    raise AssertionError("never finished")


@pytest.mark.parametrize("path", sorted((ROOT / "scenarios").glob("*.json")), ids=lambda p: p.stem)
def test_every_scenario_reaches_its_declared_outcome(coord, path):
    d = begin(coord, path.stem)
    finish(coord, d)
    report = coord.report(d)
    assert report["overall_result"] == json.loads(path.read_text())["expected_outcome"]
    assert report["integrity"]["event_chain_valid"]
    assert report["integrity"]["actions_without_matching_approval"] == []


def test_scenarios_are_deterministic(coord):
    def run():
        d = begin(coord, "dns_failure_rollback")
        drive(coord, d)
        return [(e["event_type"], e["step_id"], e["status"]) for e in coord.store.get_events(d)]
    assert run() == run()


def test_pause_during_pending_approval_survives_restart(coord, tmp_path, clock):
    d = begin(coord)
    drive(coord, d, stop_before="DR-DB-05")
    req = coord.command(d, "next")["approval"]
    coord.command(d, "pause")
    restarted = Coordinator(tmp_path / "drill.db", secret=b"test-secret", clock=clock)
    v = restarted.view(d)
    assert v["paused"] and v["approval"]["request_id"] == req["request_id"]
    with pytest.raises(DrillError):
        restarted.command(d, "approve", request_id=req["request_id"], approver="Asha")
    restarted.command(d, "resume")
    assert drive(restarted, d)["status"] == "completed"
    dispatched = [e["step_id"] for e in restarted.store.get_events(d) if e["event_type"] == "ACTION_DISPATCHED"]
    assert dispatched == ["DR-DB-05", "DR-APP-07", "DR-DNS-08"]


def test_crash_after_operator_ran_is_reconciled_not_replayed(coord):
    d = begin(coord)
    drive(coord, d, stop_before="DR-DB-05")
    req = coord.command(d, "next")["approval"]
    real = coord.operator.execute

    def run_then_die(*a, **k):
        real(*a, **k)
        raise RuntimeError("process killed")

    coord.operator.execute = run_then_die
    with pytest.raises(RuntimeError):
        coord.command(d, "approve", request_id=req["request_id"], approver="Asha")
    coord.operator.execute = real
    v = coord.view(d)
    assert [x["command"] for x in v["controls"]] == ["reconcile"]
    v = coord.command(d, "reconcile")
    assert v["step_states"]["DR-DB-05"]["status"] == "completed"
    assert drive(coord, d)["status"] == "completed"
    assert [e["step_id"] for e in coord.store.get_events(d) if e["event_type"] == "ACTION_DISPATCHED"].count("DR-DB-05") == 1


def test_concurrent_update_conflicts_and_writes_nothing(coord):
    d = begin(coord)
    stale = coord.view(d)["state_version"]
    coord.command(d, "next", expected_version=stale)
    count = len(coord.store.get_events(d))
    with pytest.raises(DrillError) as e:
        coord.command(d, "next", expected_version=stale)
    assert e.value.code == "VERSION_CONFLICT"
    state = coord.store.get_drill_state(d)
    with pytest.raises(DrillError):
        coord.store.save_drill_state(d, state, expected_version=stale)
    assert len(coord.store.get_events(d)) == count


def test_event_log_is_append_only_and_tamper_evident(coord):
    d = begin(coord)
    db = sqlite3.connect(coord.store.path)
    for sql in ("UPDATE events SET body='{}'", "DELETE FROM events"):
        with pytest.raises(sqlite3.DatabaseError):
            db.execute(sql)
        db.rollback()
    assert coord.store.verify_chain(d)
    db.execute("DROP TRIGGER events_no_update")
    db.execute("UPDATE events SET body=replace(body,'Asha','Mallory') WHERE drill_id=?", (d,))
    db.commit()
    assert not coord.store.verify_chain(d)


def test_plan_must_be_confirmed_and_start_authorized(coord):
    d = coord.create(scenario_id="nominal_success", coordinator="Asha")["drill_id"]
    with pytest.raises(DrillError):
        coord.command(d, "next")
    coord.command(d, "confirm_plan")
    with pytest.raises(DrillError):
        coord.command(d, "start", authorized=True, simulation_ack=False)
    other = coord.create(scenario_id="nominal_success", coordinator="Asha")["drill_id"]
    assert coord.command(other, "reject_plan", rationale="wrong scope")["status"] == "plan_rejected"


def test_incomplete_and_cancelled_drills_are_never_reported_as_pass(coord):
    d = begin(coord)
    drive(coord, d, stop_before="DR-BIZ-10")
    assert coord.report(d)["overall_result"] == "Incomplete"
    coord.command(d, "cancel", rationale="stop")
    assert coord.report(d)["overall_result"] == "Cancelled"


def test_optional_step_skip_needs_a_reason_and_is_a_deviation(coord):
    d = begin(coord)
    drive(coord, d, stop_before="DR-COMMS-11")
    with pytest.raises(DrillError):
        coord.command(d, "skip", rationale="")
    coord.command(d, "skip", rationale="Bridge already closed")
    assert coord.view(d)["status"] == "completed"
    assert coord.report(d)["overall_result"] == "Pass with deviations"


def test_metrics_come_from_timestamps_and_include_approval_waits(coord, clock):
    d = begin(coord)
    drive(coord, d, stop_before="DR-DB-05")
    req = coord.command(d, "next")["approval"]
    clock.advance(600)
    coord.command(d, "approve", request_id=req["request_id"], approver="Asha")
    drive(coord, d)
    r = coord.report(d)
    assert r["rpo"] == {"target_seconds": 1800, "observed_seconds": 600, "status": "met",
                        "recovery_point": r["rpo"]["recovery_point"], "reference_time": r["rpo"]["reference_time"]}
    assert r["rto"]["observed_seconds"] >= 600 + 48 + 35 + 20
    assert r["metrics"]["approval_wait_seconds"] >= 600
    db = next(t for t in r["tiers"] if t["tier"] == "database")
    assert db["tier_execution_seconds"] >= 648 and db["cumulative_seconds"] >= db["tier_execution_seconds"]


def test_missing_recovery_point_is_not_measured_not_zero(coord):
    d = begin(coord, "backup_unavailable")
    drive(coord, d)
    r = coord.report(d)
    assert r["rpo"]["status"] == "not_measured" and r["rpo"]["observed_seconds"] is None
    assert r["rto"]["status"] == "not_measured"


def test_report_markdown_has_required_sections_and_disclaimer(coord):
    d = begin(coord, "dns_failure_rollback")
    drive(coord, d)
    md = coord.report_markdown(d)
    for heading in ["Executive summary", "Objectives and scope", "Recovery metrics", "Timeline",
                    "Step execution summary", "Approval record", "Deviations and issues", "Rollback",
                    "Lessons learned", "Improvement actions", "Sign-off", "Evidence and sources"]:
        assert f"## {heading}" in md, heading
    assert "SIMULATION" in md and "DR-FIN-001" in md
    assert "REPORT_GENERATED" in kinds(coord, d)


def test_runbook_validation_flags_gaps_and_blocks_unapproved_runbooks(coord):
    kb = coord.knowledge
    assert kb.validate("DR-FIN-001", "3.2", coord.clock())["usable"]
    old = kb.validate("DR-FIN-001", "2.9", coord.clock())
    assert not old["usable"] and any("superseded" in i for i in old["issues"])
    text = " | ".join(kb.validate("DR-HR-009", "0.4", coord.clock())["issues"])
    for needle in ["draft", "owner", "rollback", "DR-MISSING-99", "restart_cluster", "success criteria", "review"]:
        assert needle in text, needle
    with pytest.raises(DrillError) as e:
        coord.create(scenario_id="nominal_success", coordinator="Asha", runbook_id="DR-FIN-001", runbook_version="2.9")
    assert e.value.code == "RUNBOOK_NOT_USABLE"


def test_conflicting_approved_versions_are_flagged(tmp_path, clock):
    import shutil
    copy = tmp_path / "knowledge"
    shutil.copytree(ROOT / "knowledge", copy)
    rb = json.loads((copy / "runbooks/DR-FIN-001_v3.2.json").read_text())
    rb["version"] = "3.3"
    (copy / "runbooks/DR-FIN-001_v3.3.json").write_text(json.dumps(rb))
    result = Knowledge(copy).validate("DR-FIN-001", "3.2", clock())
    assert not result["usable"] and any("conflict" in i.lower() for i in result["issues"])


def test_search_returns_cited_approved_passages_and_admits_gaps(coord):
    hits = coord.knowledge.search("what happens if DNS propagation times out", application="FINANCE-PROD")
    assert hits and any(h["citation"].startswith("DR-FIN-001 v3.2 section 6.2") for h in hits[:3])
    assert all(h["approval_status"] == "approved" for h in hits)
    assert coord.knowledge.search("kubernetes helm chart upgrade pizza", application="FINANCE-PROD") == []


@pytest.mark.parametrize("question", ["How do we undo the database failover?", "revert the database failover"])
def test_search_understands_operator_wording(coord, question):
    hits = coord.knowledge.search(question, application="FINANCE-PROD", limit=3)
    assert "DR-FIN-001 v3.2 section 7.1" in [h["citation"] for h in hits]
