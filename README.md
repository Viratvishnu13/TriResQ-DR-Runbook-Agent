# DR Runbook Agent

> **Simulation only.** No code here can reach real infrastructure. A passing drill does not prove that a real
> system can be recovered.

## 1. Team and Use Case

- **Team number:** 31
- **Team name:** TriResQ
- **Members:** To be added by the team
- **Use case number and title:** 22 - DR Runbook Agent (Backup & Resilience, Advanced)

## 2. Problem Statement

Disaster recovery drills follow long runbooks while one coordinator also tracks the bridge call, approvals,
timestamps and decisions by hand. Steps can be missed or run out of order, and approvals are hard to prove
later. The post-drill report is assembled afterwards and can take days (a figure quoted in our engineering
guidelines, not measured by us). We built a guided, auditable, simulation-only drill that produces its report on
demand.

## 3. Solution Overview

The coordinator opens a web page, picks a scenario and reviews the runbook plan with its source citations. After
confirming and authorizing, they go through 11 steps one at a time. Read-only checks run on request. **Every
simulated action, including each rollback, waits for Approve or Reject.** Failures lead only to the allowed
choices: retry, rollback in reverse order, escalate or cancel. A drill can be paused and resumed after a restart.
The report (RTO, RPO, per-tier timing, deviations, approvals, actions) is calculated from saved records.

**You control the failure:** before any simulated step, choose what goes wrong (for example a replication lag
value or a DNS timeout). The page shows the rule that decided the result.

## 4. Agentic Design

**Model:** OpenAI `gpt-4.1-mini` (set by `OPENAI_MODEL`). **Framework:** Microsoft Agent Framework, with the
Foundry Responses host serving `POST /responses`.

| Agent | Role | Tools |
|---|---|---|
| Drill Coordinator | Answers questions from approved sources, explains steps | `get_drill_state`, `get_events`, `search_runbook`, `ask_failover_operator` |
| Failover Operator (connected to the Coordinator) | Runs read-only simulated checks | `check_replication`, `check_health`, and `failover_database`, `repoint_application`, `update_dns`, `rollback_step`, which refuse without a signed approval token |

**Orchestration.** The Coordinator agent calls the Operator agent through `ask_failover_operator`. The drill
itself is controlled by a deterministic state machine, not by a model:

1. It offers only the commands allowed now.
2. For a check, it calls the Operator tool and applies the thresholds in code.
3. For an action, it saves an approval request. On **Approve** it saves the dispatch, creates a signed
   single-use token bound to the exact action, calls the tool, saves the result and only then advances.
4. On failure it follows the runbook: retry (at most 3), pause, or reverse-order rollback.

| AI feature | What the model does | What code checks |
|---|---|---|
| Chat questions | Answers with citations | Step IDs, tool names and citations exist |
| Step briefing | Explains the step; may suggest an option | The option must be allowed; retry counts come from code |
| Post-drill analysis | Summary, risks, actions | Each action has a real owner and real evidence IDs |
| Runbook review | Drafts steps from rough notes | Each step quotes the source; code finds gaps; draft cannot run |

All AI output is advisory. The checks confirm references exist; they **do not** confirm a sentence is true.
Limits: 900 output tokens per reply, 4 tool-loop iterations and 8 tool calls per agent run, 45 s per call,
60 AI calls per drill. Knowledge search is local SQLite FTS5 (BM25). Diagram: [docs/architecture.md](docs/architecture.md).

## 5. Prerequisites

- Windows 10 or 11.
- **Python:** 3.13 recommended. `run.bat` uses it if the `py -3.13` launcher finds it, otherwise `python`.
  Tested with 3.13.15 and, from a fresh unzip, 3.14.7.
- **Node.js:** not required. There are no npm packages.
- **System packages:** none. SQLite with FTS5 ships with Python.
- Internet access for the first dependency install, and for AI features.
- An OpenAI API key for AI features. **Without a key** the drill, approvals, rollback, search and report still work.

## 6. Setup Steps

Run in PowerShell, starting from a fresh unzip.

1. Open the project folder:
   ```powershell
   cd Team31_UseCase22
   ```
2. Create your settings file:
   ```powershell
   Copy-Item .env.example .env
   ```
3. Add your key (replace `your_key_here` after `OPENAI_API_KEY=`, then save and close):
   ```powershell
   notepad .env
   ```

`run.bat` installs the dependencies, so there is no separate install step.

## 7. How to Run

```powershell
.\run.bat
```

**URL:** http://localhost:8088 (this computer only). The first start creates `.venv` and installs packages, which
can take a few minutes. The app is ready when the window shows `DR Runbook Agent (SIMULATION ONLY)`. The page
header shows `model: gpt-4.1-mini` when a key is set. Stop with Ctrl+C. To use another port:
`.\run.bat --port 8090`.

Optional, if the Azure Developer CLI is installed: `azd ai agent run --no-client` (run `.\run.bat` once first so
that `.venv` exists). Do not run `azd provision` or `azd deploy`.

## 8. How to Test

### A. Normal flow (about 3 minutes)
1. Open http://localhost:8088. Scenario: **Nominal success - primary site outage**. Runbook: **DR-FIN-001 v3.2**.
   Type any name, then **Create drill**.
2. **Confirm plan**, tick both boxes, **Authorize and start**.
3. Click the highlighted button at each step. On approval cards click **Approve**. At Business owner acceptance
   type a name and click **Record sign-off**.
4. Click **Generate post-drill report**.

**Expected:** `Overall result: Pass`, 11/11 steps, RPO 10m 0s (met), all five tiers met, event log hash chain
VALID, 0 actions without matching approval.

### B. Failure flow
1. Start another nominal drill and continue to the **Shift Finance DNS** approval card.
2. Open **You control the failure**, choose **Times out part-way**, click **Use for the next attempt**, then
   **Approve**.
3. For each rollback click **Request rollback approval**, then **Approve**. Generate the report.

**Expected:** rollback order `DR-DNS-08`, `DR-APP-07`, `DR-DB-05`; `Overall result: Fail`; RTO not measured; your
chosen condition is listed.

### C. Exception flow
| Input | Expected |
|---|---|
| New drill with runbook **v2.9** | Refused: `RUNBOOK_NOT_USABLE` (superseded, review stale) |
| At the replication step, open **You control the failure**, set lag `45`, **Use for the next attempt**, run the check | `lag 45s > 10s limit ... -> blocked` |
| At an approval card, type `approve` in the chat box | "Typed text is never treated as approval", nothing runs |
| Chat: `How do we fail back to the primary data center?` | With a key: "Not covered by the approved sources". Without a key it shows search passages, if any, instead |

### D. AI features (needs a key)
- Chat: `What happens if DNS propagation times out?` **Expected:** an answer citing
  `DR-FIN-001 v3.2 section 6.2`. Wording varies.
- **DR / Backup Portal** tab, bottom: **Interpret and check gaps** on the pre-filled sample
  ([sample_data/sample_inputs/runbook_notes.txt](sample_data/sample_inputs/runbook_notes.txt)). **Expected:**
  5 draft steps; the scheduler step shows missing owner and rollback.
- Foundry endpoint, in a second PowerShell window:
  ```powershell
  Invoke-RestMethod -Method Post -Uri http://localhost:8088/responses -ContentType application/json -Body '{"input":"In what order does rollback run? Cite the source."}' | ConvertTo-Json -Depth 8
  ```
  **Expected:** `"status": "completed"` and an answer that cites an approved source.

### E. Automated tests
After `.\run.bat` has created `.venv` (no key needed):
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
**Expected:** `98 passed`. Optional: `.\.venv\Scripts\python.exe scripts\evaluate.py` rewrites `docs/evidence/`;
`scripts\evaluate_model.py` scores the real model (needs a key). Saved results:
[safety tests](docs/evidence/SAFETY_TESTS.md), [evaluation](docs/evidence/EVALUATION.md),
[real model](docs/evidence/MODEL_EVALUATION.md).

## 9. Known Limitations

- **Mocked:** every infrastructure check and action comes from files in `sample_data/scenarios/` or a condition a
  person chose. Communications are recorded, never sent. Sign-off and approver names are typed.
- **No sign-in or roles.** The server listens on localhost only and refuses cross-site requests.
- **One signing key and process** for both agents; separating them needs asymmetric signatures.
- **AI quality is only smoke-tested** with a small team-written set. Prompt, search and a scoring rule were
  improved after failures on those questions, so it is not a held-out score.
- **Failback** is not simulated. Failback questions are answered by a code rule because the model kept offering
  rollback steps.
- **Reference checks ignore meaning**, and citations grouped as "sections 7.1, 7.2" are not verified. The latest
  real-model run scored 21/22; the miss was a correct answer cited in that grouped form.
- **Runbook review** accepts vague owners such as "someone from the network side".
- **Masking** covers common password and key formats only. `/responses` input reaches the model as typed.
- **Event log:** edits are detected; removing the newest events is only detectable against an earlier report.
- **No separate content moderation service.** Harmful requests rely on the prompt and model; tools cannot affect
  real systems.
- **Azure deployment is untested** and not required.
- Elapsed time is real time (including approval waits) plus simulated durations.
