# Architecture

![Architecture](architecture.svg)

<details><summary>Diagram source</summary>

```mermaid
flowchart LR
    H(["Drill coordinator<br/>(human)"])
    subgraph LOCAL["TRUST BOUNDARY: local machine, localhost only, simulation only"]
        direction LR
        UI["Web UI and API<br/>blocks cross-site requests"]
        subgraph AI["AI zone: advisory, cannot approve or advance"]
            direction TB
            CA["Drill Coordinator agent"]
            OA["Failover Operator agent"]
            IN["Briefing, analysis,<br/>runbook review"]
            G["Output checks<br/>steps, tools, citations,<br/>owners, quotes"]
        end
        subgraph CTRL["Control zone: deterministic code"]
            direction TB
            C["Drill state machine"]
            AP{{"HUMAN APPROVAL<br/>signed, single-use token<br/>bound to step and parameters"}}
            O["Operator tools<br/>2 read-only, 4 token-gated"]
        end
        subgraph DATA["Tools and data: synthetic only"]
            direction TB
            K[("Runbooks and docs<br/>SQLite FTS5 / BM25")]
            X[("Scenario fixtures<br/>simulated environment")]
            S[("Drill state and<br/>hash-chained event log")]
            R["Report and metrics<br/>calculated by code"]
        end
    end
    M["OpenAI API<br/>gpt-4.1-mini<br/>(outside boundary)"]
    H --> UI
    UI -->|questions, AI requests| CA
    UI --> IN
    UI -->|commands| C
    C -->|asks| AP
    H ==>|Approve or Reject button| AP
    AP ==>|token| O
    CA -->|connected agent| OA
    CA -->|search| K
    OA -->|"no token: actions refused"| O
    IN --> K
    CA --> G
    IN --> G
    G -->|checked advice| UI
    CA <-->|masked data| M
    OA <-->|masked data| M
    IN <-->|masked data| M
    C --> K
    C --> S
    O --> X
    S --> R
```

</details>

The key design rule: **the model can talk about the drill but cannot drive it.** Control goes from a human
button to the state machine to the operator. The two Agent Framework agents sit beside that path.

## Approval sequence

```mermaid
sequenceDiagram
    participant H as Human
    participant C as Coordinator
    participant DB as State and events
    participant O as Operator
    C->>DB: APPROVAL_REQUESTED (step, tool, exact parameters, expiry)
    C->>H: approval card
    H->>C: Approve (request id, name)
    C->>DB: approval and ACTION_DISPATCHED saved first
    C->>O: tool(parameters, signed token, idempotency key)
    O->>O: verify signature, scope, expiry, single use, preconditions
    O->>C: structured result (simulation = true)
    C->>DB: result saved, then the drill advances
```

If the process dies between dispatch and result, the drill reopens with one option, **Reconcile**. It reads the
operator's ledger. It never sends the action again.

## Components

| File | Responsibility |
|---|---|
| `drill/coordinator.py` | Lifecycle, command gate, approvals, retry, rollback, pause and resume |
| `drill/operator.py` | Six-tool registry, scenario fixtures, token verification, idempotency |
| `drill/security.py` | HMAC approval tokens, secret masking |
| `drill/store.py` | `get_drill_state`, `save_drill_state`, `log_event`, `get_events` |
| `drill/knowledge.py` | Runbook validation, cited search |
| `drill/report.py` | RTO, RPO, tier metrics, approval audit, Markdown report |
| `drill/agents.py` | The two agents, their tools, loop limits, answer guard |
| `drill/insights.py` | Step briefing, post-drill analysis, runbook interpretation, and their output checks |
| `drill/web.py` | HTTP API, localhost and cross-site protection |

## Why these choices

- **SQLite** for state, events and search: one local file, transactions, no service to provision.
- **One command gate:** `controls()` lists what is allowed now, and the UI shows only that. Every guard against
  skipping ahead lives in one place.
- **Failure policy is data:** retry limits, failure branches and rollback text live in the runbook, with a hard
  cap of three retries in code.
- **Model limits:** four tool-loop iterations and eight function calls per agent run.
