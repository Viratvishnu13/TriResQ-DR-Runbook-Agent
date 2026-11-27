"""'You control the failure': a human sets the next simulated condition; the same rules decide the outcome."""
import pytest

from conftest import begin, drive, kinds
from drill import agents
from drill.coordinator import DrillError


def names(c, d):
    return [x["command"] for x in c.view(d)["controls"]]


def at(c, step, scenario="nominal_success"):
    d = begin(c, scenario)
    drive(c, d, stop_before=step)
    return d


@pytest.mark.parametrize("lag,age,passes,needle", [
    (45, 600, False, "lag 45s > 10s limit"),
    (10, 600, True, "lag 10s <= 10s limit"),
    (4, 3600, False, "age 3600s > 1800s RPO"),
])
def test_chosen_replication_numbers_are_judged_by_the_rule(coord, lag, age, passes, needle):
    d = at(coord, "DR-REPL-02")
    coord.command(d, "inject", values={"lag_seconds": lag, "recovery_point_age_seconds": age})
    v = coord.command(d, "next")
    env = v["checks"][-1]
    assert env["injected"] is True and needle in env["rule"]
    assert (v["step_states"]["DR-REPL-02"]["status"] == "completed") is passes
    assert (v["status"] == "active") is passes


def test_injection_applies_to_one_attempt_only(coord):
    d = at(coord, "DR-REPL-02")
    coord.command(d, "inject", values={"lag_seconds": 90, "recovery_point_age_seconds": 600})
    coord.command(d, "next")
    coord.command(d, "retry")
    v = coord.command(d, "next")
    assert v["injection"] is None and v["checks"][-1]["injected"] is False
    assert v["step_states"]["DR-REPL-02"]["status"] == "completed"


def test_chosen_dns_timeout_triggers_rollback_and_still_needs_approvals(coord):
    d = at(coord, "DR-DNS-08")
    request = coord.command(d, "next")["approval"]
    before = coord.view(d)["scenario_state"]
    v = coord.command(d, "inject", values={"outcome": "timeout"})
    assert v["scenario_state"] == before and v["approval"]["request_id"] == request["request_id"]
    assert "ACTION_DISPATCHED" not in [e["event_type"] for e in v["events"] if e["step_id"] == "DR-DNS-08"]
    assert drive(coord, d)["status"] == "rolled_back"
    rolled = [e["step_id"] for e in coord.store.get_events(d, event_type="ROLLBACK_COMPLETED")]
    assert rolled == ["DR-DNS-08", "DR-APP-07", "DR-DB-05"]


def test_chosen_lost_response_is_reconciled_not_repeated(coord):
    d = at(coord, "DR-DB-05")
    coord.command(d, "next")
    coord.command(d, "inject", values={"outcome": "response_lost_not_applied"})
    request = coord.view(d)["approval"]
    v = coord.command(d, "approve", request_id=request["request_id"], approver="Asha")
    assert names(coord, d) == ["reconcile"]
    v = coord.command(d, "reconcile")
    assert v["scenario_state"]["database"] == "standby" and v["blocker"]["retryable"]


def test_chosen_rollback_failure_forces_escalation(coord):
    d = at(coord, "DR-DNS-08")
    coord.command(d, "next")
    coord.command(d, "inject", values={"outcome": "timeout"})
    request = coord.view(d)["approval"]
    coord.command(d, "approve", request_id=request["request_id"], approver="Asha")
    coord.command(d, "inject", values={"outcome": "failed"})
    v = drive(coord, d)
    assert v["status"] == "blocked" and v["blocker"]["kind"] == "rollback_failed"
    coord.command(d, "escalate")
    assert coord.report(d)["overall_result"] == "Fail"


@pytest.mark.parametrize("step,values", [
    ("DR-REPL-02", {"lag_seconds": -1, "recovery_point_age_seconds": 600}),
    ("DR-REPL-02", {"lag_seconds": "4", "recovery_point_age_seconds": 600}),
    ("DR-REPL-02", {"lag_seconds": True, "recovery_point_age_seconds": 600}),
    ("DR-REPL-02", {"lag_seconds": float("nan"), "recovery_point_age_seconds": 600}),
    ("DR-REPL-02", {"lag_seconds": 4}),
    ("DR-REPL-02", {"lag_seconds": 4, "recovery_point_age_seconds": 600, "result": "healthy"}),
    ("DR-STOR-03", {"health": "on_fire"}),
    ("DR-DB-05", {"outcome": "drop_database_tables"}),
    ("DR-DB-05", {"outcome": ["success"]}),
    ("DR-DB-05", "timeout"),
])
def test_T02_invalid_injected_values_are_refused(coord, step, values):
    d = at(coord, step)
    with pytest.raises(DrillError) as error:
        coord.command(d, "inject", values=values)
    assert error.value.code == "INVALID_INPUT" and coord.view(d)["injection"] is None


def test_injection_is_only_offered_where_something_can_be_simulated(coord):
    d = coord.create(scenario_id="nominal_success", coordinator="Asha")["drill_id"]
    assert "inject" not in names(coord, d)
    d = at(coord, "DR-BIZ-10")
    assert "inject" not in names(coord, d)
    d = at(coord, "DR-STOR-03")
    coord.command(d, "pause")
    assert "inject" not in names(coord, d)


def test_injected_conditions_are_audited_and_declared_in_the_report(coord):
    d = at(coord, "DR-STOR-03")
    coord.command(d, "inject", values={"health": "hardware_fault"})
    coord.command(d, "next")
    assert "CONDITION_INJECTED" in kinds(coord, d)
    report = coord.report(d)
    assert [x["step_id"] for x in report["injected_conditions"]] == ["DR-STOR-03"]
    assert "Conditions set by a person during the drill: 1" in coord.report_markdown(d)
    clean = begin(coord)
    drive(coord, clean)
    assert coord.report(clean)["injected_conditions"] == []


def test_T04_the_model_cannot_inject_or_use_up_a_condition(coord):
    d = at(coord, "DR-STOR-03")
    coord.command(d, "inject", values={"health": "hardware_fault"})
    tools = {**agents.operator_tools(coord), **agents.coordinator_tools(coord)}
    assert not [n for n in tools if "inject" in n]
    tools["check_health"](drill_id=d, step_id="DR-STOR-03")
    assert coord.view(d)["injection"]["values"] == {"health": "hardware_fault"}
