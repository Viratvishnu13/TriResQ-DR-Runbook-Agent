# Solution documentation

If the organisers provide their own template, copy these sections into it.

## Problem and user
DR coordinators run long runbooks while also tracking the bridge call, approvals, timestamps, deviations and the
report. Steps get missed and reporting is slow. The user is the drill coordinator.

## Solution
A guided, stateful, simulation-only drill with a Drill Coordinator and a connected Failover Operator. See the
[README](../README.md) and [architecture](ARCHITECTURE.md).

## Where AI adds value
Step briefings with a suggested next option, a post-drill analysis, grounded question answering by two Agent
Framework agents, and review of free-text runbooks. Control, approvals, timing and metrics are plain code.
Model results: [real-model evaluation](evidence/MODEL_EVALUATION.md).

## Manual baseline and measured benefit

| Task | Manual baseline | This solution | Basis |
|---|---|---|---|
| Post-drill report | Days (3 days quoted in the engineering guidelines) | Under 0.1 s on demand | Baseline is quoted, **not measured by us**; report time is in the evaluation evidence |
| Approvals and timestamps | Kept by hand on a bridge call | Recorded automatically; every dispatched action checked against its approval | 11 of 11 scenarios with no unapproved action |
| Finding runbook gaps | Manual read-through | Draft steps and gaps in seconds | Sample notes: 5 steps found, missing owner and rollback flagged |

We did not time a human running the same drill, so we make no claim about time saved during the drill itself.

## Model, tools and data
- **Model:** OpenAI `gpt-4.1-mini`, called only from the local Python backend.
- **Framework:** Microsoft Agent Framework with the Foundry Responses host on `localhost:8088`.
- **Agents:** two, because the use case requires a Coordinator and a Failover Operator.
- **Operator tools (6):** `check_replication`, `check_health`, `failover_database`, `repoint_application`,
  `update_dns`, `rollback_step`.
- **Coordinator tools:** `get_drill_state`, `get_events`, `search_runbook`, `ask_failover_operator`.
- **Retrieval:** SQLite FTS5 (BM25) with source IDs, versions and sections. **State:** SQLite.
- **Data:** entirely synthetic. No real systems, people or credentials; the one password is fake.
- **Limits:** 4 tool-loop iterations and 8 tool calls per agent run, 45 s per model call, 60 model calls per
  drill, 3 retries per step.

## Required demonstrations

| Requirement | Where to show it |
|---|---|
| Normal flow | Nominal success scenario, through to a Pass report |
| Exception flow | DNS timeout with rollback; a failback question ("Not covered"); unapproved runbook v2.9 refused |
| Evidence flow | Citations in chat and briefings; structured tool results; Evaluation tab |
| Approval flow | Approval card showing exact parameters; typed "approve" does nothing |

## Evaluation rubric map

| Criterion (weight) | What to show |
|---|---|
| Problem fit and impact (20%) | 11-step Finance drill across five recovery tiers; report on demand with RTO, RPO, deviations and owned actions |
| Technical architecture (20%) | Two agents; deterministic core; versioned state; restart-safe pause; reconcile after a crash |
| AI quality and evidence (20%) | Runbook validation, step citations, "not covered" answers, runtime answer guard, evaluation evidence |
| Innovation (15%) | See below |
| Responsible AI and security (15%) | T-01 to T-10 tests, signed approvals, masking, cross-site protection |
| Demo and documentation (10%) | One-command start, demo script, architecture, evidence |

## What is different
**Judge-controlled failures.** A person sets the next simulated condition, such as a lag value or a DNS timeout,
and sees the rule that decided the result. Approvals still apply and the report declares every condition.

1. **Approvals are bound to the exact action.** A signature covers drill, step, tool, parameters and expiry,
   works once, and typed text can never create one.
2. **The model is outside the control path.** A prompt injection can at most make the model try a tool that
   refuses it, and the attempt is logged.
3. **Rollback follows real simulated state.** Only changes that landed, including partial ones, are queued, and
   the operator itself rejects the wrong order.
4. **Tamper-evident audit.** Events are hash-chained and each report re-checks that every dispatched action had
   its own approval.
5. **Honest results.** Missing data reads "not measured". An incomplete drill can never report Pass.

## Responsible AI
- Human approval for every state-changing simulated action.
- Model answers must come from tool results and carry citations; unknown references are flagged to the user.
- Credentials are masked before storage, display or model calls made by the UI.
- No keys in source. `.env` and the signing key are git-ignored.
- Only names typed by participants are stored as personal data.

## Evidence
[Safety test record](evidence/SAFETY_TESTS.md), [real-model evaluation](evidence/MODEL_EVALUATION.md),
[evaluation results](evidence/EVALUATION.md), [success report](evidence/sample_report_nominal_success.md),
[rollback report](evidence/sample_report_dns_failure_rollback.md).

## Limitations and next steps
See "Known limitations" in the README. Candidates: authenticated approvers with roles, model answer evaluation on
a labelled question set, failback, drill-to-drill trend comparison, runbook quality scoring.
