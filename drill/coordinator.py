"""Drill Coordinator agent core: the deterministic state machine.

Every state change goes through command(), and command() only accepts what controls()
currently offers. No model output can widen that set, and only approve() creates tokens.
"""
import inspect
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import report as reporting
from .errors import DrillError
from .knowledge import Knowledge
from .operator import STACK, FailoverOperator, validate_injection
from .security import ApprovalSigner, digest, load_secret, mask
from .store import Store

ROOT = Path(__file__).resolve().parents[1]
MAX_RETRIES = 3  # hard cap, whatever a runbook says
TERMINAL = {"completed", "rolled_back", "cancelled", "escalated", "plan_rejected"}
APPROVAL_WORDS = re.compile(r"\b(approve|approved|lgtm|looks good|continue|proceed|go ahead|authori[sz]e|yes|ok|okay)\b")


def utcnow():
    return datetime.now(timezone.utc)


def _text(value, field, required=True, limit=500):
    value = str(value or "").strip()
    if required and not value:
        raise DrillError("INVALID_INPUT", f"{field} is required.")
    if len(value) > limit:
        raise DrillError("INVALID_INPUT", f"{field} is too long (max {limit}).")
    return mask(value)


class _Work:
    """One loaded drill plus the events produced while changing it."""

    def __init__(self, state, clock):
        self.s, self.clock, self.events = state, clock, []

    def now(self):
        return self.clock()

    def drill_time(self, at=None):
        """Wall clock plus accumulated simulated operation and backoff time."""
        return ((at or self.now()) + timedelta(seconds=self.s["sim_offset_seconds"])).isoformat()

    def event(self, event_type, summary, step_id=None, actor="Drill Coordinator", status="success", **extra):
        at = self.now()
        self.s["event_count"] += 1
        event_id = f"evt-{self.s['event_count']:05d}"
        self.s["last_event_id"] = event_id
        self.events.append({"event_id": event_id, "timestamp": at.isoformat(), "drill_time": self.drill_time(at),
                            "event_type": event_type, "actor": actor, "step_id": step_id, "status": status,
                            "summary": summary, "action_id": extra.pop("action_id", None),
                            "approval_id": extra.pop("approval_id", None),
                            "evidence_refs": list(extra.pop("evidence_refs", [])),
                            "correlation_id": self.s["correlation_id"], "details": extra})


class Coordinator:
    name = "Drill Coordinator"

    def __init__(self, db_path=ROOT / "data" / "drill.db", secret=None, clock=utcnow,
                 knowledge_dir=ROOT / "knowledge", scenarios_dir=ROOT / "scenarios", approval_ttl=900):
        self.clock, self.approval_ttl = clock, approval_ttl
        self.store = Store(db_path)
        self.security = ApprovalSigner(secret or load_secret(self.store.path.parent / "approval.key"))
        self.operator = FailoverOperator(self.store, self.security, scenarios_dir, clock)
        self.knowledge = Knowledge(knowledge_dir)
        # ponytail: one process-wide lock; per-drill locks if many drills ever run at once.
        # Cross-process safety comes from the state version check in the store.
        self._lock = threading.RLock()

    # ===================================================================== create / read
    def create(self, scenario_id, coordinator, application="FINANCE-PROD", runbook_id="DR-FIN-001",
               runbook_version="3.2", participants=None, scope="application"):
        coordinator = _text(coordinator, "coordinator", limit=80)
        scenario = self.operator.load_scenario(scenario_id)
        if scope not in {"tabletop", "component", "application", "full_simulation"}:
            raise DrillError("INVALID_INPUT", "Unknown drill scope.")
        check = self.knowledge.validate(runbook_id, runbook_version, self.clock())
        if not check["usable"]:
            raise DrillError("RUNBOOK_NOT_USABLE", "Runbook failed validation; the drill was not created.",
                             check["issues"])
        book = self.knowledge.runbook(runbook_id, runbook_version)
        if application != book["application"] or scenario["application"] != application:
            raise DrillError("INVALID_INPUT", "Application, scenario and runbook do not match.")
        drill_id = f"drill-{self.clock():%Y%m%d}-{secrets.token_hex(3)}"
        plan = mask(sorted(book["steps"], key=lambda s: s["sequence"]))
        state = {
            "drill_id": drill_id, "application": application, "scenario_id": scenario_id,
            "scenario_title": scenario["title"], "scope": scope, "coordinator": coordinator,
            "participants": [_text(p, "participant", limit=80) for p in (participants or [])][:20]
            or sorted({s["owner"] for s in plan}),
            "runbook": {**{k: book[k] for k in ("document_id", "version", "title", "approval_status", "owner",
                                                "effective_date", "last_reviewed", "source_uri")},
                        "validation_issues": check["issues"], "content_hash": digest(plan)},
            "definitions": book["metrics"], "rto_target_seconds": book["metrics"]["rto_target_seconds"],
            "rpo_target_seconds": book["metrics"]["rpo_target_seconds"],
            "status": "planned", "paused": False, "created_at": self.clock().isoformat(), "started_at": None,
            "paused_at": None, "completed_at": None, "current_step_id": None, "plan": plan,
            "step_states": {s["step_id"]: {"status": "pending", "attempts": 0, "rollback_attempts": 0,
                                           "started_at": None, "completed_at": None, "approval_ids": [],
                                           "evidence_refs": [], "note": None} for s in plan},
            "pending": None, "inflight": None, "blocker": None, "approvals": [], "action_records": [], "checks": [],
            "decisions": [], "deviations": [], "evidence_refs": [], "recovery_point": None, "signoffs": [],
            "communications": [], "rollback": {"required": False, "queue": [], "done": [], "result": None},
            "injection": None, "injections": [], "sim_offset_seconds": 0, "event_count": 0, "last_event_id": None,
            "correlation_id": f"corr-{drill_id[-6:]}", "simulation": True,
        }
        w = _Work(state, self.clock)
        w.event("DRILL_CREATED", f"Drill created for {application}, scenario {scenario_id}.", actor=coordinator)
        w.event("RUNBOOK_RETRIEVED", f"Retrieved {runbook_id} v{runbook_version} from the local knowledge base.",
                source=state["runbook"]["source_uri"])
        w.event("RUNBOOK_VALIDATED", "Runbook is approved, current and complete.", issues=check["issues"])
        self.operator.register(drill_id, scenario_id)
        self.store.save_drill_state(drill_id, state, 0, w.events)
        return self.view(drill_id)

    def _load(self, drill_id):
        if not isinstance(drill_id, str) or not re.fullmatch(r"drill-\d{8}-[0-9a-f]{6}", drill_id):
            raise DrillError("INVALID_INPUT", "Invalid drill id.")
        return self.store.get_drill_state(drill_id)

    def view(self, drill_id):
        s = self._load(drill_id)
        step = next((p for p in s["plan"] if p["step_id"] == s["current_step_id"]), None)
        elapsed = None
        if s["started_at"]:
            end = s["completed_at"] or _Work(s, self.clock).drill_time()
            elapsed = int((datetime.fromisoformat(end) - datetime.fromisoformat(s["started_at"])).total_seconds())
        return {**s, "current_step": step, "controls": self.controls(s), "approval": s["pending"],
                "events": self.store.get_events(drill_id), "scenario_state": self.operator.state(drill_id),
                "elapsed_seconds": elapsed}

    # ===================================================================== gate
    def controls(self, s):
        """The only commands currently allowed."""
        offered = self._flow_controls(s)
        if self._injection_target(s):
            offered.append({"command": "inject", "label": "Set what happens next"})
        return offered

    def _injection_target(self, s):
        """(step_id, tool, is_rollback) for the next simulated call a person may influence, else None."""
        if s["paused"] or s["status"] not in ("active", "awaiting_approval", "rolling_back"):
            return None
        rollback = s["status"] == "rolling_back" or bool(s["pending"] and s["pending"]["is_rollback"])
        sid = s["rollback"]["queue"][0] if rollback else s["current_step_id"]
        tool = "rollback_step" if rollback else self._step(s, sid)["tool"]
        return (sid, tool, rollback) if tool else None

    def _cmd_inject(self, w, values):
        sid, tool, rollback = self._injection_target(w.s)
        values = validate_injection(tool, values)
        record = {"step_id": sid, "tool": tool, "is_rollback": rollback, "values": values,
                  "by": w.s["coordinator"], "at": w.drill_time()}
        w.s["injection"] = record
        w.s["injections"].append(record)
        shown = ", ".join(f"{k}={v}" for k, v in values.items())
        w.event("CONDITION_INJECTED", f"Person set the next simulated {tool} result for {sid}: {shown}.",
                step_id=sid, actor=w.s["coordinator"], values=values, is_rollback=rollback)

    @staticmethod
    def _take_injection(s, step_id, rollback):
        """Hand over the pending condition once, only to the call it was set for."""
        pending = s.get("injection")
        if pending and (pending["step_id"], pending["is_rollback"]) == (step_id, rollback):
            s["injection"] = None
            return pending["values"]
        return None

    def _flow_controls(self, s):
        def c(name, label):
            return {"command": name, "label": label}

        status = s["status"]
        if status in TERMINAL:
            return []
        if status == "dispatching":
            return [c("reconcile", "Reconcile interrupted action")]
        if s["paused"]:
            return [c("resume", "Resume drill"), c("cancel", "Cancel drill")]
        pause, cancel = c("pause", "Pause"), c("cancel", "Cancel drill")
        if status == "planned":
            return [c("confirm_plan", "Confirm plan"), c("reject_plan", "Reject plan")]
        if status == "ready":
            return [c("start", "Authorize and start"), cancel]
        if status == "awaiting_approval":
            extra = [c("escalate", "Escalate")] if s["pending"]["is_rollback"] else [cancel]
            return [c("approve", "Approve"), c("reject", "Reject"), pause, *extra]
        if status == "awaiting_signoff":
            return [c("signoff", "Record sign-off"), c("reject", "Decline sign-off"), pause, cancel]
        if status == "rolling_back":
            return [c("next", "Request rollback approval"), pause, c("escalate", "Escalate")]
        if status == "active":
            step = self._step(s, s["current_step_id"])
            label = {"check": "Run read-only check", "validation": "Run validation", "action": "Request approval",
                     "signoff": "Request sign-off", "communication": "Record communication"}.get(step["step_type"], "Next")
            skip = [] if step["mandatory"] else [c("skip", "Skip optional step")]
            return [c("next", label), *skip, pause, cancel]
        blocker = s["blocker"]  # status == "blocked"
        if blocker["kind"] == "unknown":
            return [c("reconcile", "Inspect state and reconcile")]
        out = [c("retry", "Retry")] if blocker["retryable"] else []
        if blocker["in_rollback"]:
            return [*out, c("escalate", "Escalate"), pause]
        if self._applied(s):
            out.append(c("rollback", "Start rollback"))
        return [*out, c("escalate", "Escalate"), pause, cancel]

    def command(self, drill_id, command, expected_version=None, **args):
        with self._lock:
            s = self._load(drill_id)
            if expected_version is not None and expected_version != s["state_version"]:
                raise DrillError("VERSION_CONFLICT", "The drill changed since you loaded it. Refresh and retry.")
            allowed = [x["command"] for x in self.controls(s)]
            if command not in allowed:
                raise DrillError("NOT_ALLOWED", "That command is not allowed right now.", {"allowed": allowed})
            handler = getattr(self, f"_cmd_{command}")
            w = _Work(s, self.clock)
            try:
                inspect.signature(handler).bind(w, **args)
            except TypeError as exc:
                raise DrillError("INVALID_INPUT", "Missing or unexpected arguments for that command.") from exc
            handler(w, **args)
            self._commit(w)
            return self.view(drill_id)

    def _commit(self, w):
        self.store.save_drill_state(w.s["drill_id"], w.s, w.s["state_version"], w.events)
        w.events = []

    # ===================================================================== helpers
    @staticmethod
    def _step(s, step_id):
        return next(p for p in s["plan"] if p["step_id"] == step_id)

    def _applied(self, s):
        """Action steps whose simulated effect is (partly) in place, newest first."""
        done = [p for p in s["plan"] if p["step_type"] == "action"
                and self.operator.assess(s["drill_id"], p["tool"]) != "not_applied"]
        return [p["step_id"] for p in sorted(done, key=lambda p: STACK.index(p["tool"]), reverse=True)]

    def _deviation(self, w, step_id, description, severity="medium", impact="Drill left the nominal path."):
        w.s["deviations"].append({"id": f"DEV-{len(w.s['deviations']) + 1:02d}", "step_id": step_id,
                                  "description": mask(description), "severity": severity, "impact": impact,
                                  "at": w.drill_time(), "resolution": "Open"})

    def _decision(self, w, who, decision, rationale, step_id=None):
        w.s["decisions"].append({"at": w.drill_time(), "by": who, "decision": decision,
                                 "rationale": rationale, "step_id": step_id})
        w.event("DECISION_RECORDED", decision + (f": {rationale}" if rationale else ""), step_id=step_id, actor=who)

    def _finish(self, w, status, event_type, summary, outcome="success"):
        w.s.update(status=status, completed_at=w.drill_time(), pending=None, blocker=None, paused=False)
        w.event(event_type, summary, status=outcome)

    def _complete_step(self, w, step_id, note=None):
        state = w.s["step_states"][step_id]
        state.update(status="completed", completed_at=w.drill_time(), note=note)
        for d in w.s["deviations"]:
            if d["step_id"] == step_id and d["resolution"] == "Open":
                d["resolution"] = "Resolved: step later completed"
        w.event("STEP_COMPLETED", f"{step_id} completed.", step_id=step_id, evidence_refs=state["evidence_refs"])
        self._advance(w)

    def _advance(self, w):
        s = w.s
        remaining = [p for p in s["plan"] if s["step_states"][p["step_id"]]["status"] not in ("completed", "skipped")]
        s.update(blocker=None, pending=None)
        if remaining:
            s.update(status="active", current_step_id=remaining[0]["step_id"])
        else:
            s["current_step_id"] = None
            self._finish(w, "completed", "DRILL_COMPLETED", "All mandatory steps, validations and sign-off recorded.")

    def _block(self, w, step_id, kind, reason, retryable, in_rollback=False):
        w.s.update(status="blocked", pending=None, current_step_id=step_id,
                   blocker={"step_id": step_id, "kind": kind, "reason": mask(reason), "retryable": retryable,
                            "in_rollback": in_rollback})
        w.event("STEP_BLOCKED", f"{step_id} blocked: {reason}", step_id=step_id, status="blocked")

    @staticmethod
    def _can_retry(step, attempts, failure_class):
        policy = step["retry_policy"]
        return failure_class in policy["retry_on"] and attempts < min(policy["max_attempts"], 1 + MAX_RETRIES)

    def _step_failed(self, w, step, failure_class, details, result):
        sid = step["step_id"]
        state = w.s["step_states"][sid]
        state.update(status="timed_out" if result == "timed_out" else "failed", note=details)
        self._deviation(w, sid, f"{step['name']}: {details}", severity="high" if step["mandatory"] else "low")
        retryable = self._can_retry(step, state["attempts"], failure_class)
        if not retryable and step["failure_branch"] == "rollback" and self._applied(w.s):
            self._start_rollback(w, sid, f"Automatic rollback: {details}", "Drill Coordinator")
        else:
            self._block(w, sid, "failure", details, retryable)

    def _start_rollback(self, w, trigger_step, reason, actor):
        queue = self._applied(w.s)
        w.s["rollback"] = {"required": True, "queue": list(queue), "done": [], "result": None,
                           "trigger_step": trigger_step, "reason": mask(reason)}
        w.s.update(status="rolling_back", blocker=None, pending=None, current_step_id=queue[0])
        w.event("ROLLBACK_REQUESTED", f"Reverse-order rollback: {' -> '.join(queue)}. Each step needs approval.",
                step_id=trigger_step, actor=actor, status="pending", queue=queue, reason=reason)

    def _operate(self, w, tool, request):
        """Call the Failover Operator and record a real timing span."""
        at, started = self.clock().isoformat(), time.perf_counter()
        env = self.operator.execute(tool, request)
        self.store.add_span(w.s["drill_id"], {
            "name": f"tool.{tool}", "agent": "operator", "step_id": request["step_id"], "started_at": at,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "simulated_seconds": env["duration_seconds"], "status": env["result"], "tokens_in": 0, "tokens_out": 0})
        return env

    def record_operator_call(self, drill_id, env):
        """Audit an operator call made outside the guided flow (by the model). Drill progress is unchanged."""
        with self._lock:
            w = _Work(self._load(drill_id), self.clock)
            refused = env["result"] == "rejected"
            w.event("OPERATOR_REJECTED" if refused else "ADVISORY_CHECK",
                    f"Model-initiated {env['tool']}: {env['result_code']}. {env['details']}",
                    step_id=env["step_id"], actor=self.operator.name, status=env["result"],
                    result_code=env["result_code"])
            self._commit(w)

    # ===================================================================== plan and start
    def _cmd_confirm_plan(self, w):
        w.s["status"] = "ready"
        w.event("PLAN_CONFIRMED", f"Plan of {len(w.s['plan'])} steps confirmed.", actor=w.s["coordinator"])

    def _cmd_reject_plan(self, w, rationale=""):
        self._decision(w, w.s["coordinator"], "Plan rejected", _text(rationale, "rationale", required=False))
        self._finish(w, "plan_rejected", "DRILL_CANCELLED", "Drill closed: plan rejected.", "rejected")

    def _cmd_start(self, w, authorized=False, simulation_ack=False):
        if authorized is not True or simulation_ack is not True:
            raise DrillError("INVALID_INPUT", "Confirm both drill authorization and the simulation-only notice.")
        s = w.s
        s["started_at"] = w.drill_time()
        w.event("DRILL_AUTHORIZED", "Drill authorization and simulation-only nature confirmed.", actor=s["coordinator"])
        s.update(status="active", current_step_id=s["plan"][0]["step_id"])
        w.event("DRILL_STARTED", "SIMULATED drill started. RTO clock running.", actor=s["coordinator"])

    # ===================================================================== guided execution
    def _cmd_next(self, w):
        s = w.s
        if s["status"] == "rolling_back":
            return self._request_approval(w, self._step(s, s["rollback"]["queue"][0]), rollback=True)
        step = self._step(s, s["current_step_id"])
        sid, state = step["step_id"], s["step_states"][step["step_id"]]
        unmet = [d for d in step["dependencies"] if s["step_states"][d]["status"] not in ("completed", "skipped")]
        if unmet:
            raise DrillError("DEPENDENCY_UNMET", "Dependencies are not complete.", unmet)
        state["started_at"] = state["started_at"] or w.drill_time()
        w.event("STEP_READY", f"{sid} ready: {step['name']} ({step['source']['citation']}).", step_id=sid)
        kind = step["step_type"]
        if kind in ("check", "validation"):
            self._run_check(w, step)
        elif kind == "action":
            self._request_approval(w, step)
        elif kind == "signoff":
            state["status"] = "waiting"
            s["status"] = "awaiting_signoff"
            w.event("APPROVAL_REQUESTED", f"{step['owner']} sign-off requested.", step_id=sid, status="pending")
        elif kind == "communication":
            record = self.knowledge.template(
                step["parameters"]["template"], drill_id=s["drill_id"], application=s["application"],
                scenario=s["scenario_title"], status=s["status"], step=sid, deviation="", reason="")
            ref = f"evidence-comms-{sid}"
            s["communications"].append({**record, "step_id": sid, "at": w.drill_time(), "sent": False})
            state["evidence_refs"].append(ref)
            s["evidence_refs"].append(ref)
            w.event("COMMUNICATION_RECORDED", "Draft recorded (not sent).", step_id=sid, evidence_refs=[ref], **record)
            self._complete_step(w, sid, "Recorded, not sent")
        else:
            raise DrillError("UNSUPPORTED_STEP", f"No handler for step type {kind}.")

    def _run_check(self, w, step):
        s, sid = w.s, step["step_id"]
        state = s["step_states"][sid]
        state["attempts"] += 1
        w.event("CHECK_STARTED", f"Read-only SIMULATED {step['tool']} (attempt {state['attempts']}).", step_id=sid)
        env = self._operate(w, step["tool"], {
            "drill_id": s["drill_id"], "step_id": sid, "scenario_id": s["scenario_id"], "params": step["parameters"],
            "attempt": state["attempts"], "drill_time": w.drill_time(), "reference_time": s["started_at"],
            "injected": self._take_injection(s, sid, False),
            "rpo_target_seconds": s["rpo_target_seconds"]})
        s["sim_offset_seconds"] += env["duration_seconds"]
        s["checks"].append(env)
        state["evidence_refs"] += env["evidence_refs"]
        s["evidence_refs"] += env["evidence_refs"]
        if "recovery_point_timestamp" in env:
            s["recovery_point"] = {"timestamp": env["recovery_point_timestamp"], "reference_time": s["started_at"],
                                   "source_check": env.get("check_id")}
        w.event("CHECK_COMPLETED", env["details"], step_id=sid, actor=self.operator.name,
                status=env["result"], evidence_refs=env["evidence_refs"], action_id=env["action_id"],
                result_code=env["result_code"], duration_seconds=env["duration_seconds"])
        if env["result"] == "success":
            if step["step_type"] == "validation":
                w.event("VALIDATION_COMPLETED", f"{step['name']}: passed.", step_id=sid,
                        evidence_refs=env["evidence_refs"])
            self._complete_step(w, sid)
        else:
            self._step_failed(w, step, env.get("failure_class"), env["details"], env["result"])

    def _request_approval(self, w, step, rollback=False):
        s, sid = w.s, step["step_id"]
        tool = "rollback_step" if rollback else step["tool"]
        params = {"step_id": sid, "reverses": step["tool"]} if rollback else step["parameters"]
        at = w.now()
        s["pending"] = {
            "request_id": f"req-{secrets.token_hex(4)}", "step_id": sid, "tool": tool, "params": params,
            "params_hash": digest(params), "is_rollback": rollback, "requested_at": at.isoformat(),
            "expires_at": (at + timedelta(seconds=self.approval_ttl)).isoformat(),
            "name": ("Roll back: " if rollback else "") + step["name"], "owner": step["owner"],
            "expected_effect": step["rollback"]["expected"] if rollback else step["expected_result"],
            "risks": step["risks"], "rollback_plan": step["rollback"]["description"],
            "success_criteria": [step["rollback"]["validation"]] if rollback else step["success_criteria"],
            "citation": step["rollback"]["citation"] if rollback else step["source"]["citation"], "simulation": True}
        s.update(status="awaiting_approval", current_step_id=sid)
        if not rollback:
            s["step_states"][sid]["status"] = "approval_pending"
        w.event("APPROVAL_REQUESTED", f"Approval required for SIMULATED {tool} on {sid}.", step_id=sid,
                status="pending", params=params, request_id=s["pending"]["request_id"])

    def _expired(self, w, request):
        return w.now() > datetime.fromisoformat(request["expires_at"])

    def _expire(self, w, request):
        sid = request["step_id"]
        w.event("APPROVAL_EXPIRED", "Approval window expired. Nothing was executed.", step_id=sid, status="timed_out",
                request_id=request["request_id"])
        self._deviation(w, sid, "Approval request expired before a decision.", severity="low")
        self._block(w, sid, "approval_expired", "approval window expired", True, request["is_rollback"])

    @staticmethod
    def _pending_for(w, request_id):
        request = w.s["pending"]
        if request_id != request["request_id"] or digest(request["params"]) != request["params_hash"]:
            raise DrillError("STALE_APPROVAL", "That approval request is no longer current. Review the new one.")
        return request

    @staticmethod
    def _approval_record(w, request, decision, approver, rationale, decided):
        record = {"approval_id": f"apr-{len(w.s['approvals']) + 1:05d}", "request_id": request["request_id"],
                  "step_id": request["step_id"], "tool": request["tool"], "params": request["params"],
                  "params_hash": request["params_hash"], "approver": approver, "decision": decision,
                  "rationale": rationale, "requested_at": request["requested_at"], "decided_at": decided.isoformat(),
                  "expires_at": request["expires_at"],
                  "wait_seconds": int((decided - datetime.fromisoformat(request["requested_at"])).total_seconds())}
        w.s["approvals"].append(record)
        return record

    def _cmd_approve(self, w, request_id, approver, rationale=""):
        s = w.s
        request = self._pending_for(w, request_id)
        approver, rationale = _text(approver, "approver", limit=80), _text(rationale, "rationale", required=False)
        if self._expired(w, request):
            return self._expire(w, request)
        sid, rollback = request["step_id"], request["is_rollback"]
        state = s["step_states"][sid]
        approval_id = self._approval_record(w, request, "approved", approver, rationale, w.now())["approval_id"]
        state["approval_ids"].append(approval_id)
        w.event("ROLLBACK_APPROVED" if rollback else "APPROVAL_GRANTED", f"{approver} approved {request['tool']}.",
                step_id=sid, actor=approver, approval_id=approval_id, params_hash=request["params_hash"])
        counter = "rollback_attempts" if rollback else "attempts"
        state[counter] += 1
        key = f"{s['drill_id']}-{sid}-{'rollback-' if rollback else ''}attempt-{state[counter]}"
        s["inflight"] = {"step_id": sid, "tool": request["tool"], "approval_id": approval_id, "idempotency_key": key,
                         "attempt": state[counter], "is_rollback": rollback, "params": request["params"],
                         "injected": self._take_injection(s, sid, rollback)}
        s["action_records"].append({**s["inflight"], "status": "dispatched"})
        if not rollback:
            state["status"] = "running"
        s.update(status="dispatching", pending=None)
        w.event("ACTION_DISPATCHED", f"Dispatched SIMULATED {request['tool']} to the Failover Operator.",
                step_id=sid, approval_id=approval_id, status="pending", idempotency_key=key)
        self._commit(w)  # persisted before the operator runs, so a crash is reconcilable

        token = self.security.generate_approval_token(
            drill_id=s["drill_id"], step_id=sid, tool=request["tool"], params=request["params"],
            approval_id=approval_id, expires=datetime.fromisoformat(request["expires_at"]).timestamp())
        env = self._operate(w, request["tool"], {
            "drill_id": s["drill_id"], "step_id": sid, "scenario_id": s["scenario_id"], "params": request["params"],
            "approval_id": token, "idempotency_key": key, "attempt": s["inflight"]["attempt"],
            "injected": s["inflight"]["injected"],
            "drill_time": w.drill_time()})
        self._apply_result(w, env)

    def _record_for(self, s, key):
        return next(r for r in reversed(s["action_records"]) if r["idempotency_key"] == key)

    def _apply_result(self, w, env):
        s, flight = w.s, w.s["inflight"]
        sid, rollback = flight["step_id"], flight["is_rollback"]
        step, state = self._step(s, sid), s["step_states"][sid]
        s["inflight"] = None
        s["sim_offset_seconds"] += env["duration_seconds"]
        self._record_for(s, flight["idempotency_key"]).update(status=env["result"], result=env)
        state["evidence_refs"] += env["evidence_refs"]
        s["evidence_refs"] += env["evidence_refs"]
        common = {"step_id": sid, "actor": self.operator.name, "approval_id": flight["approval_id"],
                  "action_id": env["action_id"], "evidence_refs": env["evidence_refs"], "status": env["result"],
                  "result_code": env["result_code"], "duration_seconds": env["duration_seconds"]}
        if rollback:
            return self._apply_rollback_result(w, step, state, env, common)
        if env["result"] == "success":
            w.event("ACTION_COMPLETED", env["details"], **common)
            return self._complete_step(w, sid)
        if env["result"] == "unknown":
            state.update(status="unknown", note=env["details"])
            w.event("ACTION_UNKNOWN", env["details"], **common)
            self._deviation(w, sid, f"{step['name']}: outcome unknown. {env['details']}", severity="high")
            return self._block(w, sid, "unknown", "action outcome unknown; it will not be repeated blindly", False)
        w.event("ACTION_TIMED_OUT" if env["result"] == "timed_out" else "ACTION_FAILED", env["details"], **common)
        self._step_failed(w, step, env.get("failure_class"), env["details"], env["result"])

    def _apply_rollback_result(self, w, step, state, env, common):
        s, sid = w.s, step["step_id"]
        if env["result"] != "success":
            w.event("ACTION_FAILED", f"Rollback failed: {env['details']}", **common)
            s["rollback"]["result"] = "failed"
            self._deviation(w, sid, f"Rollback of {sid} failed: {env['details']}", severity="critical",
                            impact="Simulated environment left partly recovered.")
            retry = self._can_retry(step, state["rollback_attempts"], env.get("failure_class"))
            return self._block(w, sid, "rollback_failed", env["details"], retry, in_rollback=True)
        state["status"] = "rolled_back"
        s["rollback"]["done"].append(sid)
        s["rollback"]["queue"].remove(sid)
        w.event("ROLLBACK_COMPLETED", f"{sid} rolled back. {env['details']}", **common)
        if s["rollback"]["queue"]:
            s.update(status="rolling_back", current_step_id=s["rollback"]["queue"][0])
            return None
        clean = not self._applied(s)
        s["rollback"]["result"] = "success" if clean else "incomplete"
        w.event("VALIDATION_COMPLETED", "Rollback validation: " +
                ("simulated environment matches its pre-drill action state." if clean else "changes remain."),
                status="success" if clean else "failed", state=self.operator.state(s["drill_id"]))
        s["current_step_id"] = None
        return self._finish(w, "rolled_back", "DRILL_COMPLETED", "Drill ended after rollback. Recovery NOT achieved.",
                            "failed")

    def _cmd_reconcile(self, w):
        """Settle an uncertain action by reading evidence. Never re-dispatches."""
        s = w.s
        if s["status"] == "dispatching":
            flight = s["inflight"]
            env = self.operator.lookup(flight["idempotency_key"])
            self._decision(w, "Drill Coordinator", "Reconciled interrupted action",
                           "operator ledger has a result" if env else "operator ledger shows it never ran",
                           flight["step_id"])
            if env:
                return self._apply_result(w, env)
            self._record_for(s, flight["idempotency_key"])["status"] = "not_run"
            s["inflight"] = None
            sid = flight["step_id"]
            self._deviation(w, sid, "Dispatch interrupted before the operator ran it.")
            return self._block(w, sid, "not_run", "action never ran; a new approval is required", True,
                               flight["is_rollback"])
        sid = s["blocker"]["step_id"]
        step = self._step(s, sid)
        finding = self.operator.assess(s["drill_id"], step["tool"])
        ref = f"evidence-reconcile-{sid}"
        s["step_states"][sid]["evidence_refs"].append(ref)
        s["evidence_refs"].append(ref)
        self._decision(w, "Drill Coordinator", f"Reconciliation found the action {finding}",
                       "read-only inspection of simulated state", sid)
        if finding == "applied":
            return self._complete_step(w, sid, "Completed after reconciliation")
        if finding == "not_applied":
            return self._block(w, sid, "not_run", "state shows the action did not apply; new approval required", True)
        return self._step_failed(w, step, "partial_change", "Reconciliation found a partial change.", "failed")

    def _cmd_reject(self, w, approver, request_id=None, rationale=""):
        s = w.s
        approver, rationale = _text(approver, "approver", limit=80), _text(rationale, "rationale", required=False)
        sid = s["current_step_id"]
        if s["status"] == "awaiting_signoff":
            s["signoffs"].append({"step_id": sid, "by": approver, "decision": "declined", "rationale": rationale,
                                  "at": w.drill_time()})
            s["step_states"][sid]["status"] = "rejected"
            w.event("SIGNOFF_RECORDED", f"{approver} declined sign-off.", step_id=sid, actor=approver,
                    status="rejected")
            self._deviation(w, sid, f"Sign-off declined by {approver}: {rationale or 'no reason given'}", "high")
            return self._block(w, sid, "signoff_declined", "sign-off declined", True)
        request = self._pending_for(w, request_id)
        rollback = request["is_rollback"]
        record = self._approval_record(w, request, "rejected", approver, rationale, w.now())
        if not rollback:
            s["step_states"][sid]["status"] = "rejected"
        w.event("APPROVAL_REJECTED", f"{approver} rejected {request['tool']}. Nothing was dispatched.",
                step_id=sid, actor=approver, status="rejected", approval_id=record["approval_id"], rationale=rationale)
        self._deviation(w, sid, f"Approval rejected: {rationale or 'no reason given'}")
        self._block(w, sid, "rejected", "approval rejected; choose how to proceed", True, rollback)

    def _cmd_signoff(self, w, approver, rationale=""):
        s, sid = w.s, w.s["current_step_id"]
        approver, rationale = _text(approver, "approver", limit=80), _text(rationale, "rationale", required=False)
        ref = f"evidence-signoff-{sid}"
        s["signoffs"].append({"step_id": sid, "by": approver, "decision": "accepted", "rationale": rationale,
                              "at": w.drill_time()})
        s["step_states"][sid]["evidence_refs"].append(ref)
        s["evidence_refs"].append(ref)
        w.event("SIGNOFF_RECORDED", f"{approver} recorded acceptance.", step_id=sid, actor=approver,
                evidence_refs=[ref])
        self._complete_step(w, sid, f"Signed off by {approver}")

    # ===================================================================== control flow
    def _cmd_retry(self, w):
        s, blocker = w.s, w.s["blocker"]
        sid = blocker["step_id"]
        step, state = self._step(s, sid), s["step_states"][sid]
        attempts = state["rollback_attempts" if blocker["in_rollback"] else "attempts"]
        backoff = step["retry_policy"]["backoff_seconds"]
        wait = backoff[min(attempts, len(backoff)) - 1] if backoff and attempts else 0
        w.event("RETRY_REQUESTED", f"Retry of {sid} after a simulated {wait}s wait. Reason: {blocker['reason']}",
                step_id=sid, actor=s["coordinator"], wait_seconds=wait, previous_attempts=attempts)
        s["sim_offset_seconds"] += wait
        if not blocker["in_rollback"]:
            state["status"] = "ready"
        s.update(status="rolling_back" if blocker["in_rollback"] else "active", blocker=None)

    def _cmd_rollback(self, w, rationale=""):
        sid = w.s["blocker"]["step_id"]
        reason = _text(rationale, "rationale", required=False) or w.s["blocker"]["reason"]
        self._start_rollback(w, sid, reason, w.s["coordinator"])

    def _cmd_skip(self, w, rationale=""):
        rationale = _text(rationale, "rationale")
        sid = w.s["current_step_id"]
        w.s["step_states"][sid].update(status="skipped", note=rationale)
        self._decision(w, w.s["coordinator"], f"Skipped optional step {sid}", rationale, sid)
        self._deviation(w, sid, f"Optional step skipped: {rationale}", severity="low")
        self._advance(w)

    def _cmd_pause(self, w, rationale=""):
        w.s.update(paused=True, paused_at=w.drill_time())
        w.event("DRILL_PAUSED", _text(rationale, "rationale", required=False) or "Drill paused.",
                step_id=w.s["current_step_id"], actor=w.s["coordinator"])

    def _cmd_resume(self, w):
        w.s.update(paused=False, paused_at=None)
        w.event("DRILL_RESUMED", "Drill resumed from persisted state.", step_id=w.s["current_step_id"],
                actor=w.s["coordinator"])
        if w.s["pending"] and self._expired(w, w.s["pending"]):
            self._expire(w, w.s["pending"])

    def _cmd_escalate(self, w, rationale=""):
        s = w.s
        reason = _text(rationale, "rationale", required=False) or (s["blocker"] or {}).get("reason", "escalated")
        record = self.knowledge.template(
            "Escalation", drill_id=s["drill_id"], application=s["application"], scenario=s["scenario_title"],
            status=s["status"], step=s["current_step_id"], deviation="", reason=reason)
        s["communications"].append({**record, "step_id": s["current_step_id"], "at": w.drill_time(), "sent": False})
        self._decision(w, s["coordinator"], "Escalated and stopped the drill", reason, s["current_step_id"])
        if s["rollback"]["required"] and s["rollback"]["result"] != "success":
            s["rollback"]["result"] = "failed"
        self._finish(w, "escalated", "DRILL_ESCALATED", record["draft"], "failed")

    def _cmd_cancel(self, w, rationale=""):
        reason = _text(rationale, "rationale", required=False) or "No reason given"
        self._decision(w, w.s["coordinator"], "Cancelled the drill", reason, w.s["current_step_id"])
        left = self._applied(w.s)
        if left:
            self._deviation(w, left[0], f"Cancelled with simulated changes still applied: {', '.join(left)}", "high")
        self._finish(w, "cancelled", "DRILL_CANCELLED", f"Drill cancelled: {reason}", "cancelled")

    # ===================================================================== text input
    def handle_text(self, drill_id, text):
        """Typed text can ask, check status, pause, resume or run the next step. It can never approve."""
        text = _text(text, "message", limit=1000)
        v = self.view(drill_id)
        lowered, allowed = text.lower().strip(), [c["command"] for c in v["controls"]]
        reply, intent, citations = None, "command", []
        if lowered in ("pause", "resume", "next", "run step", "status"):
            name = "next" if lowered == "run step" else lowered
            if name == "status":
                done = sum(x["status"] == "completed" for x in v["step_states"].values())
                reply = (f"Status: {v['status']}{' (paused)' if v['paused'] else ''}. {done}/{len(v['plan'])} steps "
                         f"completed. Current step: {v['current_step_id'] or 'none'}.")
            elif name in allowed:
                v = self.command(drill_id, name)
                reply = f"Done: {name}. Drill is now {v['status']}."
            else:
                reply = f"'{name}' is not allowed right now. Available: {', '.join(allowed) or 'nothing'}."
        elif APPROVAL_WORDS.search(lowered) and not lowered.endswith("?"):
            intent = "approval_text"
            reply = ("Typed text is never treated as approval. Nothing was executed. Use the Approve or Reject "
                     "button on the approval card, which records your name against the exact parameters.")
        else:
            intent = "question"
            citations = self.knowledge.search(text, application=v["application"], limit=3)
            reply = ("From the approved sources:\n" + "\n".join(f"[{h['citation']}] {h['text']}" for h in citations)
                     if citations else "The approved runbook and reference documents do not cover that. I will not "
                     "guess a procedure; please ask the runbook owner.")
        return {"reply": reply, "intent": intent, "citations": citations, "view": self.view(drill_id)}

    # ===================================================================== report
    def report(self, drill_id):
        s = self._load(drill_id)
        return reporting.build(s, self.store.get_events(drill_id), self.store.verify_chain(drill_id),
                               self.knowledge.prior_lessons(s["application"]), self.clock())

    def report_markdown(self, drill_id):
        with self._lock:
            report = self.report(drill_id)
            w = _Work(self._load(drill_id), self.clock)
            w.event("REPORT_GENERATED", f"Report generated: {report['overall_result']}.",
                    event_chain_head=report["integrity"]["head_hash"])
            self._commit(w)
        notes = [x["output"] for x in self.store.get_spans(drill_id) if x["name"] == "guard.analysis"]
        return reporting.to_markdown(report, notes[-1] if notes else None)
