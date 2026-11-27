"""Model-facing tools, the output guard, and the HTTP trust boundary. No model or network needed."""
import json

import pytest
from starlette.testclient import TestClient

from conftest import FAKE_PASSWORD, begin, drive, kinds
from drill import agents
from drill.web import create_app

BASE = "http://127.0.0.1:8088"


@pytest.fixture
def client(coord):
    return TestClient(create_app(coord, port=8088), base_url=BASE)


def test_model_tools_cannot_change_the_simulation(coord):
    d = begin(coord)
    drive(coord, d, stop_before="DR-DB-05")
    coord.command(d, "next")
    tools = agents.operator_tools(coord)
    for name in ("failover_database", "repoint_application", "update_dns", "rollback_step"):
        out = json.loads(tools[name](drill_id=d, step_id="DR-DB-05", approval_token="AUTH-APPV-DR-DB-05-APPROVED"))
        assert out["result"] == "rejected", name
    assert coord.view(d)["scenario_state"]["database"] == "standby"
    assert "OPERATOR_REJECTED" in kinds(coord, d)


def test_model_parameters_come_from_the_runbook_not_the_model(coord):
    import inspect
    for name, fn in agents.operator_tools(coord).items():
        assert set(inspect.signature(fn).parameters) <= {"drill_id", "step_id", "approval_token"}, name


def test_no_model_tool_can_approve(coord):
    names = set(agents.operator_tools(coord)) | set(agents.coordinator_tools(coord))
    assert not [n for n in names if "approv" in n or "command" in n or "signoff" in n]


def test_agents_are_wired_with_a_bounded_tool_loop(coord, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")
    agent = agents.build_coordinator_agent(coord)
    assert agent.name == "DrillCoordinator"
    assert agents.LIMITS["max_iterations"] <= 6 and agents.LIMITS["max_function_calls"] <= 10


def test_output_guard_flags_invented_steps_and_tools(coord):
    d = begin(coord)
    plan = coord.view(d)["plan"]
    ok = agents.guard("DR-DB-05 uses failover_database() [DR-FIN-001 v3.2 section 5.1]", plan, coord.knowledge)
    assert ok["passed"]
    prose = agents.guard("See DR-FIN-001 v3.2 section 6.2 for the timeout rule", plan, coord.knowledge)
    assert prose["passed"] and prose["cited"] == 1
    longer = agents.guard("DR-FIN-001 v3.2 section 6.25", plan, coord.knowledge)
    assert longer["unknown_citations"] == ["DR-FIN-001 v3.2 section 6.25"]
    bad = agents.guard("Run DR-NUKE-99 with drop_database_tables() [DR-FIN-001 v3.2 section 9.9]",
                       plan, coord.knowledge)
    assert not bad["passed"]
    assert bad["unknown_steps"] == ["DR-NUKE-99"] and bad["unknown_tools"] == ["drop_database_tables"]
    assert bad["unknown_citations"] == ["DR-FIN-001 v3.2 section 9.9"]


def test_model_failure_falls_back_to_cited_search(coord, client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")
    d = begin(coord)
    r = client.post(f"/api/drills/{d}/chat", json={"text": "what if DNS propagation times out?"}).json()
    assert r["answered_by"] == "approved-source search" and r["model_error"]
    assert "DR-FIN-001" in r["reply"]


def test_http_full_drill_and_report(client):
    d = client.post("/api/drills", json={"scenario_id": "nominal_success", "coordinator": "Asha"}).json()["drill_id"]
    for _ in range(60):
        v = client.get(f"/api/drills/{d}").json()
        names = [c["command"] for c in v["controls"]]
        if not names:
            break
        name = next(n for n in ("confirm_plan", "start", "approve", "signoff", "next") if n in names)
        args = {"confirm_plan": {}, "next": {}, "signoff": {"approver": "Ravi"},
                "start": {"authorized": True, "simulation_ack": True}}.get(name)
        if name == "approve":
            args = {"request_id": v["approval"]["request_id"], "approver": "Asha"}
        res = client.post(f"/api/drills/{d}/commands",
                          json={"command": name, "expected_version": v["state_version"], "args": args})
        assert res.status_code == 200, res.text
    assert client.get(f"/api/drills/{d}/report").json()["overall_result"] == "Pass"
    md = client.get(f"/api/drills/{d}/report.md")
    assert md.headers["content-disposition"].startswith("attachment") and "## Executive summary" in md.text
    assert FAKE_PASSWORD not in md.text + client.get(f"/api/drills/{d}").text
    assert client.get("/api/meta").status_code == 200 and client.get("/api/evaluation").status_code == 200
    assert client.get("/").status_code == 200 and client.get("/app.js").status_code == 200


def test_http_refuses_cross_site_and_malformed_requests(client, coord):
    d = begin(coord)
    url = f"/api/drills/{d}/commands"
    body = {"command": "next", "expected_version": coord.view(d)["state_version"], "args": {}}
    assert client.post(url, json=body, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/drills", headers={"host": "evil.example"}).status_code == 403
    assert client.post(url, content=json.dumps(body), headers={"content-type": "text/plain"}).status_code == 415
    assert client.post(url, content="{not json", headers={"content-type": "application/json"}).status_code == 400
    assert client.post(url, json=["x"]).status_code == 400
    assert client.post(url, json={**body, "expected_version": None}).status_code == 400
    assert client.post(url, json={**body, "args": {"drill_id": d}}).status_code == 400
    assert client.post(url, json={**body, "args": {"w": 1}}).status_code == 400
    assert client.post(url, json={"command": "next", "expected_version": 1, "args": {}}).status_code == 409
    assert client.post("/api/drills", json={"scenario_id": "x" * 20000, "coordinator": "a"}).status_code == 413
    assert client.get("/api/drills/not-a-drill").status_code == 400
    assert "ACTION_DISPATCHED" not in kinds(coord, d)
    assert "script-src 'self'" in client.get("/").headers["content-security-policy"]


def test_T06_failback_is_never_answered_from_rollback_steps(coord, monkeypatch):
    """No approved document covers failback, so code answers; a model once offered rollback steps instead."""
    import asyncio
    monkeypatch.setattr(agents, "build_coordinator_agent", lambda *a, **k: pytest.fail("model was called"))
    monkeypatch.setenv("OPENAI_API_KEY", "unused")
    d = begin(coord)
    for question in ("How do we fail back to the primary data center?", "What is the failback procedure?"):
        out = asyncio.run(agents.answer(coord, d, question))
        assert out["reply"].startswith("Not covered by the approved sources.")
        assert "section 7" not in out["reply"] and out["guard"]["passed"]
