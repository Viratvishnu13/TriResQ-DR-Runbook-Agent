"""Checks applied to AI output. The model is replaced by scripted objects here."""
import asyncio

import pytest

from conftest import begin, drive
from drill import insights


@pytest.fixture
def model(monkeypatch):
    """Script the next model reply and capture what was sent."""
    box = {"reply": None, "sent": None}

    async def fake(coord, trace_id, name, instructions, payload, schema):
        box["sent"] = payload
        return schema(**box["reply"]).model_dump(), {"model": "scripted", "tokens_in": 1, "tokens_out": 1}

    monkeypatch.setattr(insights, "_generate", fake)
    return box


def test_T06_briefing_drops_options_and_references_that_do_not_exist(coord, model):
    d = begin(coord, "replication_lag_breach")
    drive(coord, d)
    model["reply"] = {"explanation": "Lag is high. Run DR-NUKE-99.", "watch_for": [],
                      "citations": ["DR-FIN-001 v3.2 section 4.1", "DR-FIN-001 v3.2 section 99"],
                      "recommended_option": "skip", "reasoning": "faster"}
    out = asyncio.run(insights.brief(coord, d))
    assert out["recommended_option"] is None  # skip is not allowed on a mandatory step
    assert out["guard"]["unknown_steps"] == ["DR-NUKE-99"]
    assert out["guard"]["unknown_citations"] == ["DR-FIN-001 v3.2 section 99"]
    assert not out["guard"]["passed"]


def test_briefing_keeps_an_allowed_option_and_changes_nothing(coord, model):
    d = begin(coord, "replication_lag_breach")
    drive(coord, d)
    before = coord.view(d)["state_version"]
    model["reply"] = {"explanation": "Lag is above threshold.", "watch_for": ["lag"],
                      "citations": ["DR-FIN-001 v3.2 section 4.1"], "recommended_option": "retry",
                      "reasoning": "transient"}
    out = asyncio.run(insights.brief(coord, d))
    assert out["recommended_option"] == "retry" and out["guard"]["passed"]
    assert coord.view(d)["state_version"] == before  # advice never advances or edits the drill
    # Counts are calculated by code: one of three allowed attempts is used.
    assert model["sent"]["retries_remaining"] == 2 and "retry_policy" not in model["sent"]["step"]


def test_T06_analysis_flags_invented_evidence_and_owners(coord, model):
    d = begin(coord, "dns_failure_rollback")
    drive(coord, d)
    model["reply"] = {"executive_summary": "Failed at DNS.", "went_well": [], "risks": [], "actions": [
        {"action": "Fix DNS", "owner": "NetOps", "priority": "P1", "evidence": ["DEV-01", "DR-DNS-08"]},
        {"action": "Buy things", "owner": "Marketing", "priority": "P3", "evidence": ["DEV-77"]}]}
    out = asyncio.run(insights.analyse(coord, d))
    assert [a["verified"] for a in out["actions"]] == [True, False]
    assert not out["guard"]["passed"]
    md = coord.report_markdown(d)
    assert "## AI analysis" in md and "Fix DNS" in md and "unverified" in md
    assert "SimOnly-NotReal-123" not in str(model["sent"])


def test_report_without_analysis_has_no_ai_section(coord):
    d = begin(coord)
    drive(coord, d)
    assert "## AI analysis" not in coord.report_markdown(d)


def test_interpretation_flags_ungrounded_steps_and_gaps_and_masks_input(coord, model):
    source = "1. DB Lead promotes the standby database.\n2. Someone updates DNS. Password=hunter2"
    model["reply"] = {"ambiguities": [], "steps": [
        {"name": "Promote standby", "step_type": "action", "owner": "DB Lead", "success_criteria": ["online"],
         "rollback": "Demote", "source_quote": "DB Lead promotes the standby database."},
        {"name": "Flush caches", "step_type": "action", "owner": None, "success_criteria": [],
         "rollback": None, "source_quote": "Flush all caches."}]}
    out = asyncio.run(insights.interpret(coord, source))
    first, second = out["steps"]
    assert first["grounded"] and first["gaps"] == []
    assert not second["grounded"]
    assert second["gaps"] == ["no owner", "no success criteria", "action has no rollback"]
    assert out["executable"] is False
    assert "hunter2" not in str(model["sent"])


@pytest.mark.parametrize("bad", ["", "   ", "x" * 8001, None])
def test_T02_interpretation_rejects_bad_input(coord, model, bad):
    with pytest.raises(insights.DrillError):
        asyncio.run(insights.interpret(coord, bad))


def test_T09_model_calls_are_capped_per_drill(coord, monkeypatch):
    from drill import agents
    monkeypatch.setattr(agents, "MAX_CALLS_PER_DRILL", 2)
    monkeypatch.setattr(agents, "_client", lambda: pytest.fail("model was called past the cap"))
    monkeypatch.setenv("OPENAI_API_KEY", "unused")
    d = begin(coord)
    for _ in range(2):
        coord.store.add_span(d, {"name": "llm.briefing", "agent": "coordinator"})
    for call in (insights.brief(coord, d), agents.answer(coord, d, "what is the rollback order?")):
        with pytest.raises(insights.DrillError) as e:
            asyncio.run(call)
        assert e.value.code == "MODEL_BUDGET"


def test_T09_slow_model_calls_time_out(coord, monkeypatch):
    from drill import agents

    class Stuck:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, *args, **kwargs):
            await asyncio.sleep(30)

    monkeypatch.setattr("agent_framework.Agent", Stuck)
    monkeypatch.setattr(agents, "_client", lambda: None)
    monkeypatch.setattr(agents, "MODEL_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setenv("OPENAI_API_KEY", "unused")
    d = begin(coord)
    with pytest.raises(insights.DrillError) as e:
        asyncio.run(insights.brief(coord, d))
    assert e.value.code == "MODEL_FAILED" and "Timeout" in e.value.message
    assert coord.view(d)["status"] == "active"  # the drill carries on without the model
