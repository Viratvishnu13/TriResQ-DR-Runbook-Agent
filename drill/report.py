"""Post-drill report: a pure function of persisted state and events. No model is involved."""
from datetime import datetime, timedelta

DISCLAIMER = ("SIMULATION ONLY. Every check and action result in this report comes from scenario files or from "
              "simulated conditions a person set, which are listed. Nothing here proves that real infrastructure can "
              "be recovered.")


def _seconds(start, end):
    if not start or not end:
        return None
    return int(round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()))


def _measure(observed, target):
    status = "not_measured" if observed is None else ("met" if observed <= target else "missed")
    return {"target_seconds": target, "observed_seconds": observed, "status": status}


def audit_approvals(events):
    """Every dispatched action must have an earlier, unused approval for the same step."""
    granted, used, bad = {}, set(), []
    for e in events:
        if e["event_type"] in ("APPROVAL_GRANTED", "ROLLBACK_APPROVED"):
            granted[e["approval_id"]] = e["step_id"]
        elif e["event_type"] == "ACTION_DISPATCHED":
            ref = e["approval_id"]
            if granted.get(ref) != e["step_id"] or ref in used:
                bad.append(e["event_id"])
            used.add(ref)
    return bad


def _tiers(s):
    out = []
    for tier in s["definitions"]["tiers"]:
        steps = [p["step_id"] for p in s["plan"] if p["tier"] == tier["tier"]]
        states = [s["step_states"][i] for i in steps]
        ready = s["step_states"][tier["ready_step"]]
        done = ready["completed_at"]
        starts = [x["started_at"] for x in states if x["started_at"]]
        first = min(starts) if starts else None
        cumulative = _seconds(s["started_at"], done)
        item = {"tier": tier["tier"], "label": tier["label"], "target_seconds": tier["target_seconds"],
                "cumulative_seconds": cumulative, "tier_execution_seconds": _seconds(first, done),
                "ready_step": tier["ready_step"]}
        if any(i in s["rollback"]["done"] for i in steps):
            item["result"] = "rolled_back"
        else:
            item["result"] = _measure(cumulative, tier["target_seconds"])["status"]
        out.append(item)
    return out


def _overall(s, rto, rpo, tiers):
    status = s["status"]
    if status == "cancelled":
        return "Cancelled"
    if status == "rolled_back" or (status == "escalated" and s["rollback"]["result"] == "failed"):
        return "Fail"
    if status != "completed":
        return "Incomplete"
    if "missed" in [rto["status"], rpo["status"], *(t["result"] for t in tiers)]:
        return "Fail"
    return "Pass with deviations" if s["deviations"] else "Pass"


def _improvements(s, now, rto):
    owners = {p["step_id"]: p["owner"] for p in s["plan"]}
    due = {"critical": 7, "high": 14, "medium": 30, "low": 60}
    priority = {"critical": "P1", "high": "P1", "medium": "P2", "low": "P3"}
    actions, seen = [], set()
    for d in s["deviations"]:
        key = (d["step_id"], d["description"])
        if key in seen:
            continue
        seen.add(key)
        actions.append({"action": f"Investigate and remediate {d['id']} ({d['step_id']}): {d['description']}",
                        "priority": priority[d["severity"]], "owner": owners.get(d["step_id"], "DR Lead"),
                        "target_date": (now + timedelta(days=due[d["severity"]])).date().isoformat(),
                        "status": "Open"})
    if rto["status"] == "missed":
        actions.append({"action": "Reduce recovery time: overall RTO target was missed.", "priority": "P1",
                        "owner": "DR Lead", "target_date": (now + timedelta(days=14)).date().isoformat(),
                        "status": "Open"})
    return actions


def build(s, events, chain_valid, prior_lessons, now):
    point = s["recovery_point"] or {}
    observed_rpo = _seconds(point.get("timestamp"), point.get("reference_time"))
    rpo = {**_measure(observed_rpo, s["rpo_target_seconds"]), "recovery_point": point.get("timestamp"),
           "reference_time": point.get("reference_time")}
    business = next(p for p in s["plan"] if p["step_type"] == "signoff")
    rto_end = s["step_states"][business["step_id"]]["completed_at"]
    rto = _measure(_seconds(s["started_at"], rto_end), s["rto_target_seconds"])
    tiers = _tiers(s)
    result = _overall(s, rto, rpo, tiers)

    states = s["step_states"]
    executed = [i for i, x in states.items() if x["status"] != "pending"]
    completed = [i for i, x in states.items() if x["status"] == "completed"]
    evidenced = [i for i in completed if states[i]["evidence_refs"]]
    action_seconds = sum(r["result"]["duration_seconds"] for r in s["action_records"] if "result" in r)
    validation_ids = {p["step_id"] for p in s["plan"] if p["step_type"] == "validation"}
    metrics = {
        "elapsed_seconds": _seconds(s["started_at"], s["completed_at"]),
        "planned_completion_seconds": s["rto_target_seconds"],
        "steps_completed": len(completed), "steps_total": len(states),
        "step_success_rate": round(len(completed) / len(executed), 3) if executed else None,
        "failed_or_blocked_events": sum(e["event_type"] == "STEP_BLOCKED" for e in events),
        "retries": sum(e["event_type"] == "RETRY_REQUESTED" for e in events),
        "approval_wait_seconds": sum(a["wait_seconds"] for a in s["approvals"]),
        "action_execution_seconds": action_seconds,
        "validation_seconds": sum(c["duration_seconds"] for c in s["checks"] if c["step_id"] in validation_ids),
        "deviations": len(s["deviations"]), "manual_decisions": len(s["decisions"]),
        "runbook_gaps": len(s["runbook"]["validation_issues"]),
        "evidence_completeness": round(len(evidenced) / len(completed), 3) if completed else None,
    }
    names = {p["step_id"]: p["name"] for p in s["plan"]}
    waited = metrics["approval_wait_seconds"]
    lessons = {
        "worked_well": [f"{i} {names[i]}" for i in completed],
        "did_not_work": [f"{d['step_id']}: {d['description']}" for d in s["deviations"]],
        "runbook_gaps": s["runbook"]["validation_issues"],
        "coordination_gaps": [f"Approval waits totalled {waited}s."] if waited > 300 else [],
        "carried_forward": prior_lessons,
    }
    return {
        "drill_id": s["drill_id"], "application": s["application"], "scenario_id": s["scenario_id"],
        "scenario_title": s["scenario_title"], "drill_date": (s["started_at"] or s["created_at"])[:10],
        "generated_at": now.isoformat(), "status": s["status"], "overall_result": result,
        "disclaimer": DISCLAIMER, "runbook": s["runbook"], "scope": s["scope"],
        "participants": s["participants"], "coordinator": s["coordinator"], "definitions": s["definitions"],
        "rto": rto, "rpo": rpo, "tiers": tiers, "metrics": metrics,
        "timeline": [{k: e.get(k) for k in ("event_id", "timestamp", "drill_time", "event_type", "actor",
                                            "step_id", "status", "summary")} for e in events],
        "steps": [{"step_id": p["step_id"], "name": p["name"], "owner": p["owner"],
                   "citation": p["source"]["citation"], **{k: states[p["step_id"]][k] for k in
                   ("status", "attempts", "approval_ids", "evidence_refs", "note")},
                   "duration_seconds": _seconds(states[p["step_id"]]["started_at"],
                                                states[p["step_id"]]["completed_at"])} for p in s["plan"]],
        "approvals": s["approvals"], "action_records": s["action_records"], "checks": s["checks"],
        "deviations": s["deviations"], "decisions": s["decisions"], "rollback": s["rollback"],
        "injected_conditions": s.get("injections", []), "signoffs": s["signoffs"], "communications": s["communications"], "lessons": lessons,
        "improvement_actions": _improvements(s, now, rto),
        "integrity": {"event_chain_valid": chain_valid, "event_count": len(events),
                      "head_hash": events[-1]["hash"] if events else None,
                      "actions_without_matching_approval": audit_approvals(events)},
    }


def duration(seconds):
    if seconds is None:
        return "not measured"
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return (f"{hours}h " if hours else "") + (f"{minutes}m " if hours or minutes else "") + f"{secs}s"


def _table(headers, rows):
    def cell(v):
        return str(v if v not in (None, "", []) else "-").replace("|", "\\|").replace("\n", " ")

    if not rows:
        return "_None recorded._"
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def _bullets(items):
    return "\n".join(f"- {i}" for i in items) or "- None recorded."


def _ai_section(a):
    """Model-written commentary, kept apart from the measured sections."""
    return [
        "## AI analysis (advisory, model-generated)",
        f"_Written by {a['model']} from the records above. Figures and results elsewhere in this report are "
        f"calculated by code. Reference check: {'passed' if a['guard']['passed'] else 'FAILED - review'}._",
        a["executive_summary"],
        "**Went well**", _bullets(a["went_well"]), "**Risks**", _bullets(a["risks"]),
        _table(["Proposed action", "Owner", "Priority", "Evidence", "Check"],
               [[x["action"], x["owner"], x["priority"], ", ".join(x["evidence"]),
                 "verified" if x["verified"] else "unverified"] for x in a["actions"]]),
    ]


def to_markdown(r, analysis=None):
    book, rb, m, lessons = r["runbook"], r["rollback"], r["metrics"], r["lessons"]
    signed = {x["step_id"]: x for x in r["signoffs"] if x["decision"] == "accepted"}
    business = next(iter(signed.values()), None)
    parts = [
        "# Disaster Recovery Drill Report", f"> **{r['disclaimer']}**",
        "## Executive summary",
        _bullets([f"Drill ID: {r['drill_id']}", f"Application: {r['application']}",
                  f"Scenario: {r['scenario_title']} (`{r['scenario_id']}`)", f"Drill date: {r['drill_date']} (UTC)",
                  f"Runbook: {book['document_id']} v{book['version']} ({book['approval_status']})",
                  f"Conditions set by a person during the drill: {len(r['injected_conditions'])}"
                  + "".join(f"; {x['step_id']} {x['values']}" for x in r["injected_conditions"]),
                  f"**Overall result: {r['overall_result']}**",
                  f"Steps completed: {m['steps_completed']}/{m['steps_total']}; deviations: {m['deviations']}; "
                  f"retries: {m['retries']}"]),
        "## Objectives and scope",
        _bullets([f"Scope: {r['scope']}", f"Participating teams: {', '.join(r['participants'])}",
                  f"Target RTO: {duration(r['rto']['target_seconds'])}",
                  f"Target RPO: {duration(r['rpo']['target_seconds'])}",
                  f"RTO definition: {r['definitions']['rto_definition']}",
                  f"RPO definition: {r['definitions']['rpo_definition']}"]),
        "## Recovery metrics",
        _table(["Tier", "Target RTO", "Cumulative from DR start", "Tier execution", "Result"],
               [[t["label"], duration(t["target_seconds"]), duration(t["cumulative_seconds"]),
                 duration(t["tier_execution_seconds"]), t["result"]] for t in r["tiers"]]),
        "",
        _table(["Metric", "Target", "Observed", "Status"],
               [["Overall RTO", duration(r["rto"]["target_seconds"]), duration(r["rto"]["observed_seconds"]),
                 r["rto"]["status"]],
                ["RPO", duration(r["rpo"]["target_seconds"]), duration(r["rpo"]["observed_seconds"]),
                 r["rpo"]["status"]],
                ["Drill completion time", duration(m["planned_completion_seconds"]), duration(m["elapsed_seconds"]),
                 r["status"]]]),
        "Tiers run in sequence in this runbook, so no tier durations overlap.",
        f"Approval wait {duration(m['approval_wait_seconds'])}; simulated action time "
        f"{duration(m['action_execution_seconds'])}; validation time {duration(m['validation_seconds'])}.",
        "## Timeline",
        _table(["Timestamp (UTC)", "Event", "Step", "Actor", "Result", "Summary"],
               [[e["timestamp"][:19], e["event_type"], e["step_id"], e["actor"], e["status"], e["summary"]]
                for e in r["timeline"]]),
        "## Step execution summary",
        _table(["Step ID", "Step", "Owner", "Status", "Attempts", "Duration", "Approval", "Evidence", "Source"],
               [[x["step_id"], x["name"], x["owner"], x["status"], x["attempts"], duration(x["duration_seconds"]),
                 ", ".join(x["approval_ids"]), ", ".join(x["evidence_refs"]), x["citation"]] for x in r["steps"]]),
        "## Approval record",
        _table(["Approval", "Step", "Tool", "Approver", "Decision", "Decided (UTC)", "Parameter hash", "Rationale"],
               [[a["approval_id"], a["step_id"], a["tool"], a["approver"], a["decision"], a["decided_at"][:19],
                 a["params_hash"][:12], a["rationale"]] for a in r["approvals"]]),
        "## Deviations and issues",
        _table(["ID", "Step", "Description", "Impact", "Severity", "Resolution"],
               [[d["id"], d["step_id"], d["description"], d["impact"], d["severity"], d["resolution"]]
                for d in r["deviations"]]),
        "## Rollback",
        _bullets([f"Rollback required: {'Yes' if rb['required'] else 'No'}",
                  f"Reason: {rb.get('reason') or '-'}",
                  f"Steps rolled back (in order): {', '.join(rb['done']) or 'none'}",
                  f"Not rolled back: {', '.join(rb['queue']) or 'none'}",
                  f"Approvals: {', '.join(a['approval_id'] for a in r['approvals'] if a['tool'] == 'rollback_step') or 'none'}",
                  f"Result: {rb['result'] or 'not applicable'}"]),
        "## Lessons learned",
        "**What worked well**", _bullets(lessons["worked_well"]),
        "**What did not work**", _bullets(lessons["did_not_work"]),
        "**Runbook gaps**", _bullets(lessons["runbook_gaps"]),
        "**Coordination gaps**", _bullets(lessons["coordination_gaps"]),
        "**Carried forward from the prior drill**",
        _bullets(f"{x['title']}: {x['text']} [{x['citation']}]" for x in lessons["carried_forward"]),
        "## Improvement actions",
        _table(["Action", "Priority", "Owner", "Target date", "Status"],
               [[a["action"], a["priority"], a["owner"], a["target_date"], a["status"]]
                for a in r["improvement_actions"]]),
        "## Sign-off",
        _bullets([f"Drill Coordinator: {r['coordinator']} (ran the drill)",
                  f"Business owner: {business['by'] + ' at ' + business['at'][:19] if business else 'NOT RECORDED'}",
                  "Application owner: NOT RECORDED", "DR lead: NOT RECORDED"]),
        "## Evidence and sources",
        _bullets([f"Runbook: {book['document_id']} v{book['version']} - {book['source_uri']}",
                  f"Plan content hash: {book['content_hash']}",
                  f"Event log: {r['integrity']['event_count']} events, hash chain "
                  f"{'VALID' if r['integrity']['event_chain_valid'] else 'BROKEN'}",
                  f"Event chain head: {r['integrity']['head_hash']}",
                  "Actions without a matching approval: "
                  f"{len(r['integrity']['actions_without_matching_approval'])}",
                  f"Check results: {len(r['checks'])}; action records: {len(r['action_records'])}; "
                  f"approval decisions: {len(r['approvals'])}"]),
    ]
    if analysis:
        parts += _ai_section(analysis)
    return "\n\n".join(p for p in parts if p != "") + "\n"
