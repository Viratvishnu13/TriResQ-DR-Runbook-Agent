# DR Runbook Agent

Use case 22, Backup & Resilience (Advanced). A guided disaster recovery **drill simulator** with two agents.

> **Simulation only.** No code here can reach real infrastructure. Every check and action result comes from a
> scenario file. A passing drill does not prove that a real system can be recovered.

## What it does

A coordinator picks a scenario. The **Drill Coordinator** checks the runbook is approved and current, shows the
plan, and walks through 11 steps. The **Failover Operator** runs simulated checks and actions. Every action,
rollbacks included, needs a human approval. At the end the report is built from saved state and the event log.

| Manual drill problem | What this does | How to check it |
|---|---|---|
| Steps missed or run out of order | Dependency-gated state machine, one step at a time | `tests/test_drill.py` |
| Approvals and timestamps tracked by hand | Signed single-use approvals and a hash-chained event log | Evaluation tab, live audit |
| Reporting takes days (per the use case) | Report generated on demand in milliseconds | `docs/evidence/EVALUATION.md` |
| Unclear what to do on failure | Retry, escalate or reverse-order rollback from the runbook | Scenario matrix |

## You control the failure

Before any check, action or rollback, open **You control the failure** and choose what the simulator will do:
type a replication lag and recovery point age, mark storage as faulty, or make DNS time out. The same rules
decide what happens, for example `lag 45s > 10s limit -> blocked`. A condition applies to one attempt, cannot
skip an approval, is logged, and is declared in the report. The model has no tool that can set one.

## Where the AI is used

| Feature | What the model does | What code checks |
|---|---|---|
| Chat questions (Coordinator agent, with the Operator agent connected) | Answers from approved passages, runs read-only checks | Step IDs, tool names and citations exist |
| Step briefing | Explains the current step; after a failure, suggests one option | Suggestion must be an allowed command; retry counts are calculated by code |
| Post-drill analysis | Summary, risks, proposed actions | Each action needs a real owner and real step or deviation IDs |
| Runbook review (Portal tab) | Turns free-text notes into draft steps | Each step must quote the source; gaps are found by code; the draft cannot run |

All of it is advisory. The reference checks confirm that IDs and citations exist. They **do not** confirm that
a sentence is true. In testing, a briefing once misstated the retry limit and still passed; retry counts are now
supplied by code.

## Run it (Windows PowerShell)

```powershell
py -3.13 -m venv .venv          # or: uv venv --python 3.13 .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt # or: uv pip install -r requirements.txt
python main.py                  # http://localhost:8088
```

No key is needed. The drill, approvals, rollback, search and reports all work without a model.

### Or run it through the Azure Developer CLI

```powershell
winget install --id Microsoft.Azd --exact
azd ai agent run --no-client    # same app on http://localhost:8088
```

Tested locally with azd 1.40.0 and the `azure.ai.agents` 1.2.0 extension, using an existing Python 3.13
`.venv` (create it first: without one, azd built a 3.14 environment). No Azure sign-in, `init`, `provision` or
`deploy` was needed. Its console also prints telemetry records.

### Turn on the AI agents

```powershell
Copy-Item .env.example .env     # then set OPENAI_API_KEY (or the two Azure OpenAI variables)
python main.py
```

This turns on the four AI features and the Foundry Responses endpoint at `POST http://localhost:8088/responses`.
Drill data (masked) and any pasted runbook text are sent to your model provider.

## Test and evaluate

```powershell
python -m pytest -q
python scripts/evaluate.py        # tests, scenarios, search; writes docs/evidence/
python scripts/evaluate_model.py  # scores the real model (needs a key, makes about 14 calls)
```

## What the model can and cannot do

| Can | Cannot |
|---|---|
| Read drill state and events | Confirm a plan, approve, sign off or advance a step |
| Search approved documents | Create an approval token |
| Ask the Operator for read-only checks | Change a tool's parameters (they come from the runbook) |
| Try an action tool, and be refused and logged | Change the simulated environment without a valid token |

Sequencing, approvals, timing, RTO/RPO, the report and runbook validation are plain Python.

## Where this differs from the source documents

| Topic | Choice made here |
|---|---|
| Replication lag limit (guidelines say 10s, baseline example shows 420s as healthy) | Set per scenario (`lag_threshold_seconds`, 10s). RPO age is checked separately |
| Rollback (guidelines: automatic; baseline: approved) | Starts automatically, each step needs its own approval |
| Sample rollback token `ROLLBACK-APPV-<step>-APPROVED` | Replaced by an HMAC-signed token; the fixed string is rejected |
| Search (baseline: AI Search) | Local SQLite FTS5 with BM25, as the guidelines recommend |
| UI evaluation and token figures in the first mock-up | Removed. Only measured values are shown |

## Known limitations

- **Approver identity is typed, not authenticated.** The server only listens on localhost and refuses
  cross-site requests. Real use needs sign-in and roles.
- **One signing key, one process.** Both agents run together, so the Operator could in principle sign tokens.
  Separating them needs asymmetric signatures.
- **Event log:** edits and removals in the middle are detected. Deleting the newest events is only detectable by
  comparing with the chain head printed in an earlier report.
- **Model quality is only smoke-tested.** One run of a small team-written set
  ([results](docs/evidence/MODEL_EVALUATION.md)). Prompt, search and scoring were improved after failures on
  those same questions, so it is not a held-out score.
- **Failback questions are answered by a code rule.** The model kept offering rollback steps as failback.
- **Runbook review** accepts vague owners such as "someone from the network side" as an owner.
- **`/responses` input** goes to the model as typed. Tool results are masked, and chat in the UI is masked first.
- **Azure deployment is untested** and not required. Only the local `azd ai agent run` was tested.
- **Elapsed time** is real time (including approval waits) plus the simulated durations in the scenario file.
- **Failback** is not simulated.
- `knowledge/runbooks` contains a **fake** password, there to demonstrate masking. A secret scanner may flag it.

## Build the submission zip

```powershell
python scripts/package.py       # dist/Team31_UseCase22_Final.zip; refuses if it finds a secret
```

It includes only the project folders. `.env`, `data/` (signing key and drill database) and `.venv` stay out.
Upload the zip, not the working folder.

All data in this project is synthetic. A model call times out after 45 seconds, replies are capped at 900 tokens, API response storage is switched
off (`store: false`), and one drill is limited to
60 model calls (the `/responses` endpoint is limited per run, not per drill).

## Layout

```
main.py            start the server
drill/             coordinator, operator, agents, insights, security, store, knowledge, report, web
knowledge/         runbooks (JSON) and reference documents (Markdown)
scenarios/         deterministic scenario fixtures
web/               browser UI
tests/             guardrail, scenario, agent and HTTP tests
evals/, scripts/   retrieval question set and evaluation runner
docs/              architecture, solution write-up, demo script, evidence
```

To add a scenario, create `scenarios/<name>.json` with `"extends": "nominal_success"`, an `expected_outcome` and
only the results that differ. The tests pick it up automatically.
