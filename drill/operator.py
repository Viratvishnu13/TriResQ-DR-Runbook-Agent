"""Failover Operator agent: fixture-backed checks and approval-gated SIMULATED actions.

This module deliberately has no network, shell or cloud SDK access. Its only side effects
are rows in the local SQLite simulation state.
"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from .errors import DrillError

# The complete tool registry. Anything not listed here cannot run.
TOOLS = {
    "check_replication": {"mutating": False},
    "check_health": {"mutating": False},
    "failover_database": {"mutating": True, "key": "database", "from": "standby", "to": "online_dr",
                          "partial": "promoting", "requires": {"storage": "ready"}},
    "repoint_application": {"mutating": True, "key": "application", "from": "pointing_to_primary",
                            "to": "pointing_to_dr", "partial": "config_partial", "requires": {"database": "online_dr"}},
    "update_dns": {"mutating": True, "key": "dns", "from": "primary", "to": "dr", "partial": "propagating",
                   "requires": {"application": "pointing_to_dr"}},
    "rollback_step": {"mutating": True},
}
# Order in which effects stack; rollback must unwind from the end.
STACK = ["failover_database", "repoint_application", "update_dns"]
RECOVERED = {"database": {"database": "online_dr"},
             "application": {"database": "online_dr", "application": "pointing_to_dr", "dns": "dr"}}
RESULT_CODES = {"success": "SIMULATED_SUCCESS", "failed": "SIMULATED_FAILURE",
                "timed_out": "SIMULATED_TIMEOUT", "unknown": "SIMULATED_UNKNOWN"}


# Conditions a person may set for the next simulated attempt. They choose inputs; the rules still decide.
ACTION_CHOICES = {
    "success": {"result": "success"},
    "transient_error": {"result": "failed", "failure_class": "transient_failure"},
    "permanent_error": {"result": "failed", "failure_class": "config_error"},
    "timeout": {"result": "timed_out", "failure_class": "propagation_timeout", "state_effect": "partial"},
    "response_lost_applied": {"result": "unknown", "failure_class": "response_lost", "state_effect": "applied"},
    "response_lost_not_applied": {"result": "unknown", "failure_class": "response_lost", "state_effect": "none"},
}
HEALTH_CHOICES = {"healthy": None, "degraded": "transient_failure", "hardware_fault": "hardware_fault"}
ROLLBACK_CHOICES = {"success": {"result": "success"},
                    "failed": {"result": "failed", "failure_class": "rollback_error"}}
NUMBER_LIMITS = {"lag_seconds": 3600, "recovery_point_age_seconds": 86400}


def validate_injection(tool, values):
    """Strict allowlist: exact keys, known choices, bounded finite numbers."""
    def bad(why):
        raise DrillError("INVALID_INPUT", why)

    if not isinstance(values, dict):
        bad("Injected values must be an object.")
    if tool == "check_replication":
        if set(values) != set(NUMBER_LIMITS):
            bad("Give lag_seconds and recovery_point_age_seconds.")
        for key, limit in NUMBER_LIMITS.items():
            number = values[key]
            if type(number) not in (int, float) or not 0 <= number <= limit:
                bad(f"{key} must be a number from 0 to {limit}.")
        return dict(values)
    field, choices = (("health", HEALTH_CHOICES) if tool == "check_health" else
                      ("outcome", ROLLBACK_CHOICES if tool == "rollback_step" else ACTION_CHOICES))
    if set(values) != {field} or not isinstance(values[field], str) or values[field] not in choices:
        bad(f"{field} must be one of: {', '.join(choices)}.")
    return dict(values)


def _injected_outcome(tool, values, fixture_outcome):
    duration = fixture_outcome.get("duration_seconds", 10)
    if tool == "check_replication":
        return {"result": "healthy", **values, "duration_seconds": duration}
    if tool == "check_health":
        return {"result": values["health"], "failure_class": HEALTH_CHOICES[values["health"]],
                "duration_seconds": duration}
    choices = ROLLBACK_CHOICES if tool == "rollback_step" else ACTION_CHOICES
    return {**choices[values["outcome"]], "duration_seconds": duration,
            "details": f"Simulated {tool}: condition set by a person ({values['outcome']})."}


def _compare(label, value, limit, unit):
    if value is None:
        return f"{label} unavailable (limit {limit}s {unit})"
    return f"{label} {value:g}s {'<=' if value <= limit else '>'} {limit}s {unit}"


def _merge(base, over):
    if isinstance(base, dict) and isinstance(over, dict):
        return {k: _merge(base.get(k), over[k]) if k in over else base[k] for k in {**base, **over}}
    return over


def _pick(entry, attempt):
    """A fixture entry is one outcome, or a list of per-attempt outcomes (the last one repeats)."""
    attempts = entry.get("attempts")
    return attempts[min(attempt, len(attempts)) - 1] if attempts else entry


class FailoverOperator:
    name = "Failover Operator"

    def __init__(self, store, signer, scenarios_dir, clock):
        self.store, self.signer, self.clock = store, signer, clock
        self.scenarios_dir = Path(scenarios_dir)

    # ---- scenarios ---------------------------------------------------------
    def list_scenarios(self):
        return [self.load_scenario(p.stem) for p in sorted(self.scenarios_dir.glob("*.json"))]

    def load_scenario(self, scenario_id):
        if not isinstance(scenario_id, str) or not re.fullmatch(r"[a-z0-9_]{1,60}", scenario_id):
            raise DrillError("INVALID_INPUT", "Invalid scenario id.")
        path = self.scenarios_dir / f"{scenario_id}.json"
        if not path.is_file():
            raise DrillError("NOT_FOUND", "Unknown scenario.")
        text = path.read_text(encoding="utf-8")
        if re.search(r"(?i)\b(https?|ssh|jdbc|ftp)://", text):
            raise DrillError("UNSAFE_SCENARIO", "Scenario fixtures may not name external endpoints.")
        data = json.loads(text)
        if data.get("extends"):
            data = _merge(self.load_scenario(data["extends"]), data)
        if data.get("simulation") is not True:
            raise DrillError("UNSAFE_SCENARIO", "Scenario must be marked simulation: true.")
        return data

    # ---- simulated environment --------------------------------------------
    def register(self, drill_id, scenario_id):
        initial = self.load_scenario(scenario_id)["initial_state"]
        with self.store.tx() as db:
            db.execute("INSERT INTO op_state VALUES(?,?,?)", (drill_id, scenario_id, json.dumps(initial)))

    def state(self, drill_id):
        """Read-only copy of the simulated environment."""
        with self.store.tx() as db:
            row = db.execute("SELECT state FROM op_state WHERE drill_id=?", (drill_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def assess(self, drill_id, tool):
        """Has this action's effect landed? applied | not_applied | partial."""
        spec, value = TOOLS[tool], self.state(drill_id)[TOOLS[tool]["key"]]
        return {spec["to"]: "applied", spec["from"]: "not_applied"}.get(value, "partial")

    def lookup(self, idempotency_key):
        with self.store.tx() as db:
            row = db.execute("SELECT body FROM op_ledger WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        return json.loads(row[0]) if row else None

    # ---- the single entry point --------------------------------------------
    def execute(self, tool, request):
        if tool not in TOOLS:
            return self._refuse(tool, request, "REJECTED_UNKNOWN_TOOL", "Tool is not in the operator registry.")
        needed = ("drill_id", "step_id", "scenario_id", "params", "drill_time")
        if any(request.get(k) is None for k in needed) or self.state(request["drill_id"]) is None:
            return self._refuse(tool, request, "REJECTED_INVALID_INPUT", "Missing context or unknown drill.")
        with self.store.tx() as db:
            row = db.execute("SELECT scenario_id, state FROM op_state WHERE drill_id=?",
                             (request["drill_id"],)).fetchone()
            if row[0] != request["scenario_id"]:
                return self._refuse(tool, request, "REJECTED_INVALID_INPUT", "Scenario does not match this drill.")
            fixture, env = self.load_scenario(row[0]), json.loads(row[1])
            if not TOOLS[tool]["mutating"]:
                return self._check(tool, request, fixture, env)
            return self._act(db, tool, request, fixture, env)

    def _envelope(self, tool, request, **fields):
        start = request.get("drill_time")
        duration = fields.get("duration_seconds", 0)
        done = (datetime.fromisoformat(start) + timedelta(seconds=duration)).isoformat() if start else None
        return {"drill_id": request.get("drill_id"), "scenario_id": request.get("scenario_id"),
                "step_id": request.get("step_id"), "step": request.get("step_id"), "tool": tool, "action": tool,
                "idempotency_key": request.get("idempotency_key"), "approval_id": None, "started_at": start,
                "completed_at": done, "duration_seconds": duration, "evidence_refs": [],
                "replayed": False, "simulation": True, **fields}

    def _refuse(self, tool, request, code, details):
        return self._envelope(tool, request, action_id=None, operation_type="refused", result="rejected",
                              result_code=code, status=code, details=details, failure_class="rejected")

    def _check(self, tool, request, fixture, env):
        params, attempt = request["params"], int(request.get("attempt", 1))
        component = params.get("component")
        key = f"{tool}:{component}" if tool == "check_health" else tool
        entry = fixture["checks"].get(key)
        if entry is None:
            return self._refuse(tool, request, "REJECTED_INVALID_INPUT", "No fixture for that check.")
        outcome = _pick(entry, attempt)
        injected = request.get("injected")
        if injected:
            outcome = _injected_outcome(tool, validate_injection(tool, injected), outcome)
        status, failure_class, extra = outcome["result"], outcome.get("failure_class"), {}
        if tool == "check_replication":
            lag, age = outcome.get("lag_seconds"), outcome.get("recovery_point_age_seconds")
            limit, rpo = fixture["lag_threshold_seconds"], request.get("rpo_target_seconds")
            point = None
            if age is not None and request.get("reference_time"):
                point = (datetime.fromisoformat(request["reference_time"]) - timedelta(seconds=age)).isoformat()
            assessment = "not_measured" if point is None or rpo is None else ("met" if age <= rpo else "missed")
            if status == "healthy" and (lag is None or lag > limit):
                status, failure_class = "lagging", failure_class or "transient_failure"
            if status == "healthy" and assessment != "met":
                status, failure_class = "rpo_not_confirmed", "recovery_point_missing"
            passed = status == "healthy"
            details = (f"Lag {'unavailable' if lag is None else f'{lag}s'} (threshold {limit}s); "
                       f"recovery point age {'unavailable' if age is None else f'{age}s'}; RPO {assessment}.")
            rule = (f"{_compare('lag', lag, limit, 'limit')}; {_compare('recovery point age', age, rpo or 0, 'RPO')}"
                    f" -> {'proceed' if passed else 'blocked'}")
            extra = {"rule": rule, "lag_seconds": lag, "lag_threshold_seconds": limit, "recovery_point_timestamp": point,
                     "rpo_assessment": assessment, "can_proceed": passed}
        else:
            wrong = {k: env[k] for k, v in RECOVERED.get(component, {}).items() if env[k] != v}
            if status == "healthy" and wrong:
                status, failure_class = "unhealthy", "state_mismatch"
            passed = status == "healthy"
            details = f"Simulated {component} health: {status}." + (f" Unexpected state: {wrong}." if wrong else "")
            rule = f"health must be 'healthy'; got '{status}' -> {'proceed' if passed else 'blocked'}"
            extra = {"rule": rule, "component": component, "healthy": passed, "http_code": 200 if passed else 503,
                     "can_proceed": passed}
        check_id = f"chk-{request['drill_id'][-6:]}-{request['step_id']}-{attempt}"
        return self._envelope(tool, request, action_id=check_id, check_id=check_id, operation_type="check",
                              result="success" if passed else "failed",
                              result_code="SIMULATED_CHECK_PASSED" if passed else "SIMULATED_CHECK_FAILED",
                              status=status, details=details, injected=bool(injected), failure_class=None if passed else failure_class,
                              duration_seconds=outcome.get("duration_seconds", 10),
                              evidence_refs=[f"evidence-{check_id}"], **extra)

    def _act(self, db, tool, request, fixture, env):
        drill_id, key = request["drill_id"], request.get("idempotency_key")
        if not key:
            return self._refuse(tool, request, "REJECTED_INVALID_INPUT", "Idempotency key required.")
        row = db.execute("SELECT body FROM op_ledger WHERE idempotency_key=?", (key,)).fetchone()
        if row:
            seen = json.loads(row[0])
            if (seen["drill_id"], seen["step_id"], seen["tool"]) != (drill_id, request["step_id"], tool):
                return self._refuse(tool, request, "REJECTED_UNAUTHORIZED", "Idempotency key belongs to another call.")
            return {**seen, "replayed": True}
        approval_id, reason = self.signer.verify(
            request.get("approval_id"), drill_id=drill_id, step_id=request["step_id"], tool=tool,
            params=request["params"], now_ts=self.clock().timestamp())
        if reason:
            return self._refuse(tool, request, "REJECTED_UNAUTHORIZED", reason)
        if db.execute("SELECT 1 FROM op_used_approvals WHERE drill_id=? AND approval_id=?",
                      (drill_id, approval_id)).fetchone():
            return self._refuse(tool, request, "REJECTED_UNAUTHORIZED", "Approval token was already used.")

        if tool == "rollback_step":
            target = request["params"].get("reverses")
            if target not in STACK:
                return self._refuse(tool, request, "REJECTED_INVALID_INPUT", "Nothing to roll back for that step.")
            spec = TOOLS[target]
            if env[spec["key"]] == spec["from"]:
                return self._refuse(tool, request, "REJECTED_PRECONDITION", "That change is not applied.")
            later = [t for t in STACK[STACK.index(target) + 1:] if env[TOOLS[t]["key"]] != TOOLS[t]["from"]]
            if later:
                return self._refuse(tool, request, "REJECTED_PRECONDITION", f"Roll back {later[-1]} first.")
            table = fixture["rollbacks"]
            outcome = _pick(table.get(request["params"].get("step_id"), table["default"]),
                            int(request.get("attempt", 1)))
            changes = {"success": spec["from"]}
        else:
            spec = TOOLS[tool]
            unmet = {k: env[k] for k, v in spec["requires"].items() if env[k] != v}
            if env[spec["key"]] != spec["from"] or unmet:
                return self._refuse(tool, request, "REJECTED_PRECONDITION",
                                    f"Simulated state does not allow this action: {unmet or env[spec['key']]}.")
            outcome = _pick(fixture["actions"][tool], int(request.get("attempt", 1)))
            changes = {"success": spec["to"], "applied": spec["to"], "partial": spec["partial"]}

        injected = request.get("injected")
        if injected:  # reached only after the token, single-use and precondition checks above
            outcome = _injected_outcome(tool, validate_injection(tool, injected), outcome)
            if tool != "rollback_step":
                changes = {"success": spec["to"], "applied": spec["to"], "partial": spec["partial"]}
        result = outcome["result"]
        effect = "success" if result == "success" else outcome.get("state_effect")
        before = env[spec["key"]]
        if effect in changes:
            env[spec["key"]] = changes[effect]
        number = db.execute("SELECT COUNT(*) FROM op_ledger WHERE drill_id=?", (drill_id,)).fetchone()[0] + 1
        action_id = f"act-{number:05d}"
        envelope = self._envelope(
            tool, request, action_id=action_id, operation_type="action", result=result,
            result_code=RESULT_CODES[result], status="COMPLETED" if result == "success" else result.upper(),
            details=outcome.get("details", f"Simulated {tool} completed."), approval_id=approval_id,
            failure_class=outcome.get("failure_class"), duration_seconds=outcome["duration_seconds"],
            evidence_refs=[f"evidence-{drill_id[-6:]}-{action_id}"],
            before={spec["key"]: before}, after={spec["key"]: env[spec["key"]]}, injected=bool(injected),
            rule=f"outcome '{result}': simulated {spec['key']} {before} -> {env[spec['key']]}")
        db.execute("INSERT INTO op_used_approvals VALUES(?,?)", (drill_id, approval_id))
        db.execute("INSERT INTO op_ledger VALUES(?,?,?)", (key, drill_id, json.dumps(envelope)))
        db.execute("UPDATE op_state SET state=? WHERE drill_id=?", (json.dumps(env), drill_id))
        return envelope
