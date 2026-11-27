# Disaster Recovery Drill Report

> **SIMULATION ONLY. Every check and action result in this report comes from scenario files or from simulated conditions a person set, which are listed. Nothing here proves that real infrastructure can be recovered.**

## Executive summary

- Drill ID: drill-20261127-60d0f6
- Application: FINANCE-PROD
- Scenario: Nominal success - primary site outage (`nominal_success`)
- Drill date: 2026-11-27 (UTC)
- Runbook: DR-FIN-001 v3.2 (approved)
- Conditions set by a person during the drill: 0
- **Overall result: Pass**
- Steps completed: 11/11; deviations: 0; retries: 0

## Objectives and scope

- Scope: application
- Participating teams: App Lead, Backup & Storage, Compute Platform, DB Lead, DB On-call, Finance Business Owner, Incident Management, NetOps, SRE On-call
- Target RTO: 4h 0m 0s
- Target RPO: 30m 0s
- RTO definition: From recovery authorization (drill start) to recorded business acceptance. Elapsed time = wall-clock time (including approval waits) plus fixture-simulated operation and backoff durations.
- RPO definition: Reference time (simulated outage, recorded at drill start) minus the timestamp of the selected recovery point.

## Recovery metrics

| Tier | Target RTO | Cumulative from DR start | Tier execution | Result |
|---|---|---|---|---|
| Storage | 30m 0s | 27s | 27s | met |
| Infrastructure | 1h 0m 0s | 39s | 12s | met |
| Database | 2h 0m 0s | 1m 39s | 1m 0s | met |
| Application | 3h 0m 0s | 2m 46s | 1m 7s | met |
| Business service | 4h 0m 0s | 2m 47s | 0s | met |

| Metric | Target | Observed | Status |
|---|---|---|---|
| Overall RTO | 4h 0m 0s | 2m 47s | met |
| RPO | 30m 0s | 10m 0s | met |
| Drill completion time | 4h 0m 0s | 2m 47s | completed |

Tiers run in sequence in this runbook, so no tier durations overlap.

Approval wait 0s; simulated action time 1m 43s; validation time 24s.

## Timeline

| Timestamp (UTC) | Event | Step | Actor | Result | Summary |
|---|---|---|---|---|---|
| 2026-11-27T17:00:08 | DRILL_CREATED | - | Asha | success | Drill created for FINANCE-PROD, scenario nominal_success. |
| 2026-11-27T17:00:08 | RUNBOOK_RETRIEVED | - | Drill Coordinator | success | Retrieved DR-FIN-001 v3.2 from the local knowledge base. |
| 2026-11-27T17:00:08 | RUNBOOK_VALIDATED | - | Drill Coordinator | success | Runbook is approved, current and complete. |
| 2026-11-27T17:00:08 | PLAN_CONFIRMED | - | Asha | success | Plan of 11 steps confirmed. |
| 2026-11-27T17:00:08 | DRILL_AUTHORIZED | - | Asha | success | Drill authorization and simulation-only nature confirmed. |
| 2026-11-27T17:00:08 | DRILL_STARTED | - | Asha | success | SIMULATED drill started. RTO clock running. |
| 2026-11-27T17:00:08 | STEP_READY | DR-KICKOFF-01 | Drill Coordinator | success | DR-KICKOFF-01 ready: Record drill kickoff communication (DR-FIN-001 v3.2 section 3.1). |
| 2026-11-27T17:00:08 | COMMUNICATION_RECORDED | DR-KICKOFF-01 | Drill Coordinator | success | Draft recorded (not sent). |
| 2026-11-27T17:00:08 | STEP_COMPLETED | DR-KICKOFF-01 | Drill Coordinator | success | DR-KICKOFF-01 completed. |
| 2026-11-27T17:00:08 | STEP_READY | DR-REPL-02 | Drill Coordinator | success | DR-REPL-02 ready: Verify replication health and recovery point (DR-FIN-001 v3.2 section 4.1). |
| 2026-11-27T17:00:08 | CHECK_STARTED | DR-REPL-02 | Drill Coordinator | success | Read-only SIMULATED check_replication (attempt 1). |
| 2026-11-27T17:00:08 | CHECK_COMPLETED | DR-REPL-02 | Failover Operator | success | Lag 4.2s (threshold 10s); recovery point age 600s; RPO met. |
| 2026-11-27T17:00:08 | STEP_COMPLETED | DR-REPL-02 | Drill Coordinator | success | DR-REPL-02 completed. |
| 2026-11-27T17:00:08 | STEP_READY | DR-STOR-03 | Drill Coordinator | success | DR-STOR-03 ready: Validate DR storage readiness (DR-FIN-001 v3.2 section 4.2). |
| 2026-11-27T17:00:08 | CHECK_STARTED | DR-STOR-03 | Drill Coordinator | success | Read-only SIMULATED check_health (attempt 1). |
| 2026-11-27T17:00:08 | CHECK_COMPLETED | DR-STOR-03 | Failover Operator | success | Simulated storage health: healthy. |
| 2026-11-27T17:00:08 | STEP_COMPLETED | DR-STOR-03 | Drill Coordinator | success | DR-STOR-03 completed. |
| 2026-11-27T17:00:08 | STEP_READY | DR-INFRA-04 | Drill Coordinator | success | DR-INFRA-04 ready: Validate DR compute readiness (DR-FIN-001 v3.2 section 4.3). |
| 2026-11-27T17:00:08 | CHECK_STARTED | DR-INFRA-04 | Drill Coordinator | success | Read-only SIMULATED check_health (attempt 1). |
| 2026-11-27T17:00:08 | CHECK_COMPLETED | DR-INFRA-04 | Failover Operator | success | Simulated compute health: healthy. |
| 2026-11-27T17:00:08 | STEP_COMPLETED | DR-INFRA-04 | Drill Coordinator | success | DR-INFRA-04 completed. |
| 2026-11-27T17:00:08 | STEP_READY | DR-DB-05 | Drill Coordinator | success | DR-DB-05 ready: Fail over Finance database to DR (SIMULATED) (DR-FIN-001 v3.2 section 5.1). |
| 2026-11-27T17:00:08 | APPROVAL_REQUESTED | DR-DB-05 | Drill Coordinator | pending | Approval required for SIMULATED failover_database on DR-DB-05. |
| 2026-11-27T17:00:08 | APPROVAL_GRANTED | DR-DB-05 | Asha | success | Asha approved failover_database. |
| 2026-11-27T17:00:08 | ACTION_DISPATCHED | DR-DB-05 | Drill Coordinator | pending | Dispatched SIMULATED failover_database to the Failover Operator. |
| 2026-11-27T17:00:08 | ACTION_COMPLETED | DR-DB-05 | Failover Operator | success | Simulated failover_database completed. |
| 2026-11-27T17:00:08 | STEP_COMPLETED | DR-DB-05 | Drill Coordinator | success | DR-DB-05 completed. |
| 2026-11-27T17:00:08 | STEP_READY | DR-DB-06 | Drill Coordinator | success | DR-DB-06 ready: Validate database at DR (DR-FIN-001 v3.2 section 5.2). |
| 2026-11-27T17:00:08 | CHECK_STARTED | DR-DB-06 | Drill Coordinator | success | Read-only SIMULATED check_health (attempt 1). |
| 2026-11-27T17:00:08 | CHECK_COMPLETED | DR-DB-06 | Failover Operator | success | Simulated database health: healthy. |
| 2026-11-27T17:00:08 | VALIDATION_COMPLETED | DR-DB-06 | Drill Coordinator | success | Validate database at DR: passed. |
| 2026-11-27T17:00:08 | STEP_COMPLETED | DR-DB-06 | Drill Coordinator | success | DR-DB-06 completed. |
| 2026-11-27T17:00:08 | STEP_READY | DR-APP-07 | Drill Coordinator | success | DR-APP-07 ready: Re-point Finance application to DR database (SIMULATED) (DR-FIN-001 v3.2 section 6.1). |
| 2026-11-27T17:00:08 | APPROVAL_REQUESTED | DR-APP-07 | Drill Coordinator | pending | Approval required for SIMULATED repoint_application on DR-APP-07. |
| 2026-11-27T17:00:08 | APPROVAL_GRANTED | DR-APP-07 | Asha | success | Asha approved repoint_application. |
| 2026-11-27T17:00:08 | ACTION_DISPATCHED | DR-APP-07 | Drill Coordinator | pending | Dispatched SIMULATED repoint_application to the Failover Operator. |
| 2026-11-27T17:00:08 | ACTION_COMPLETED | DR-APP-07 | Failover Operator | success | Simulated repoint_application completed. |
| 2026-11-27T17:00:08 | STEP_COMPLETED | DR-APP-07 | Drill Coordinator | success | DR-APP-07 completed. |
| 2026-11-27T17:00:08 | STEP_READY | DR-DNS-08 | Drill Coordinator | success | DR-DNS-08 ready: Shift Finance DNS to DR load balancer (SIMULATED) (DR-FIN-001 v3.2 section 6.2). |
| 2026-11-27T17:00:08 | APPROVAL_REQUESTED | DR-DNS-08 | Drill Coordinator | pending | Approval required for SIMULATED update_dns on DR-DNS-08. |
| 2026-11-27T17:00:08 | APPROVAL_GRANTED | DR-DNS-08 | Asha | success | Asha approved update_dns. |
| 2026-11-27T17:00:08 | ACTION_DISPATCHED | DR-DNS-08 | Drill Coordinator | pending | Dispatched SIMULATED update_dns to the Failover Operator. |
| 2026-11-27T17:00:08 | ACTION_COMPLETED | DR-DNS-08 | Failover Operator | success | Simulated update_dns completed. |
| 2026-11-27T17:00:08 | STEP_COMPLETED | DR-DNS-08 | Drill Coordinator | success | DR-DNS-08 completed. |
| 2026-11-27T17:00:08 | STEP_READY | DR-APP-09 | Drill Coordinator | success | DR-APP-09 ready: Validate Finance application end to end (DR-FIN-001 v3.2 section 6.3). |
| 2026-11-27T17:00:08 | CHECK_STARTED | DR-APP-09 | Drill Coordinator | success | Read-only SIMULATED check_health (attempt 1). |
| 2026-11-27T17:00:08 | CHECK_COMPLETED | DR-APP-09 | Failover Operator | success | Simulated application health: healthy. |
| 2026-11-27T17:00:08 | VALIDATION_COMPLETED | DR-APP-09 | Drill Coordinator | success | Validate Finance application end to end: passed. |
| 2026-11-27T17:00:08 | STEP_COMPLETED | DR-APP-09 | Drill Coordinator | success | DR-APP-09 completed. |
| 2026-11-27T17:00:08 | STEP_READY | DR-BIZ-10 | Drill Coordinator | success | DR-BIZ-10 ready: Business owner acceptance (DR-FIN-001 v3.2 section 8.1). |
| 2026-11-27T17:00:08 | APPROVAL_REQUESTED | DR-BIZ-10 | Drill Coordinator | pending | Finance Business Owner sign-off requested. |
| 2026-11-27T17:00:08 | SIGNOFF_RECORDED | DR-BIZ-10 | Ravi (Finance owner) | success | Ravi (Finance owner) recorded acceptance. |
| 2026-11-27T17:00:08 | STEP_COMPLETED | DR-BIZ-10 | Drill Coordinator | success | DR-BIZ-10 completed. |
| 2026-11-27T17:00:08 | STEP_READY | DR-COMMS-11 | Drill Coordinator | success | DR-COMMS-11 ready: Record drill completion communication (DR-FIN-001 v3.2 section 8.2). |
| 2026-11-27T17:00:08 | COMMUNICATION_RECORDED | DR-COMMS-11 | Drill Coordinator | success | Draft recorded (not sent). |
| 2026-11-27T17:00:08 | STEP_COMPLETED | DR-COMMS-11 | Drill Coordinator | success | DR-COMMS-11 completed. |
| 2026-11-27T17:00:08 | DRILL_COMPLETED | - | Drill Coordinator | success | All mandatory steps, validations and sign-off recorded. |
| 2026-11-27T17:00:08 | REPORT_GENERATED | - | Drill Coordinator | success | Report generated: Pass. |

## Step execution summary

| Step ID | Step | Owner | Status | Attempts | Duration | Approval | Evidence | Source |
|---|---|---|---|---|---|---|---|---|
| DR-KICKOFF-01 | Record drill kickoff communication | Incident Management | completed | 0 | 0s | - | evidence-comms-DR-KICKOFF-01 | DR-FIN-001 v3.2 section 3.1 |
| DR-REPL-02 | Verify replication health and recovery point | DB On-call | completed | 1 | 15s | - | evidence-chk-60d0f6-DR-REPL-02-1 | DR-FIN-001 v3.2 section 4.1 |
| DR-STOR-03 | Validate DR storage readiness | Backup & Storage | completed | 1 | 12s | - | evidence-chk-60d0f6-DR-STOR-03-1 | DR-FIN-001 v3.2 section 4.2 |
| DR-INFRA-04 | Validate DR compute readiness | Compute Platform | completed | 1 | 12s | - | evidence-chk-60d0f6-DR-INFRA-04-1 | DR-FIN-001 v3.2 section 4.3 |
| DR-DB-05 | Fail over Finance database to DR (SIMULATED) | DB Lead | completed | 1 | 48s | apr-00001 | evidence-60d0f6-act-00001 | DR-FIN-001 v3.2 section 5.1 |
| DR-DB-06 | Validate database at DR | DB Lead | completed | 1 | 12s | - | evidence-chk-60d0f6-DR-DB-06-1 | DR-FIN-001 v3.2 section 5.2 |
| DR-APP-07 | Re-point Finance application to DR database (SIMULATED) | App Lead | completed | 1 | 35s | apr-00002 | evidence-60d0f6-act-00002 | DR-FIN-001 v3.2 section 6.1 |
| DR-DNS-08 | Shift Finance DNS to DR load balancer (SIMULATED) | NetOps | completed | 1 | 20s | apr-00003 | evidence-60d0f6-act-00003 | DR-FIN-001 v3.2 section 6.2 |
| DR-APP-09 | Validate Finance application end to end | SRE On-call | completed | 1 | 12s | - | evidence-chk-60d0f6-DR-APP-09-1 | DR-FIN-001 v3.2 section 6.3 |
| DR-BIZ-10 | Business owner acceptance | Finance Business Owner | completed | 0 | 0s | - | evidence-signoff-DR-BIZ-10 | DR-FIN-001 v3.2 section 8.1 |
| DR-COMMS-11 | Record drill completion communication | Incident Management | completed | 0 | 0s | - | evidence-comms-DR-COMMS-11 | DR-FIN-001 v3.2 section 8.2 |

## Approval record

| Approval | Step | Tool | Approver | Decision | Decided (UTC) | Parameter hash | Rationale |
|---|---|---|---|---|---|---|---|
| apr-00001 | DR-DB-05 | failover_database | Asha | approved | 2026-11-27T17:00:08 | 05409597100c | - |
| apr-00002 | DR-APP-07 | repoint_application | Asha | approved | 2026-11-27T17:00:08 | eb3d67fbdb3e | - |
| apr-00003 | DR-DNS-08 | update_dns | Asha | approved | 2026-11-27T17:00:08 | 4b8e44855cec | - |

## Deviations and issues

_None recorded._

## Rollback

- Rollback required: No
- Reason: -
- Steps rolled back (in order): none
- Not rolled back: none
- Approvals: none
- Result: not applicable

## Lessons learned

**What worked well**

- DR-KICKOFF-01 Record drill kickoff communication
- DR-REPL-02 Verify replication health and recovery point
- DR-STOR-03 Validate DR storage readiness
- DR-INFRA-04 Validate DR compute readiness
- DR-DB-05 Fail over Finance database to DR (SIMULATED)
- DR-DB-06 Validate database at DR
- DR-APP-07 Re-point Finance application to DR database (SIMULATED)
- DR-DNS-08 Shift Finance DNS to DR load balancer (SIMULATED)
- DR-APP-09 Validate Finance application end to end
- DR-BIZ-10 Business owner acceptance
- DR-COMMS-11 Record drill completion communication

**What did not work**

- None recorded.

**Runbook gaps**

- None recorded.

**Coordination gaps**

- None recorded.

**Carried forward from the prior drill**

- Lessons learned: DNS time to live was not lowered before the previous drill, which delayed traffic shift. Verify TTL is 60 seconds before the DNS step. [RPT-FIN-2026-05 v1.0]
- Open actions: Pre-warm the DR application pool before re-pointing. Owner: App Lead. [RPT-FIN-2026-05 v1.0]

## Improvement actions

_None recorded._

## Sign-off

- Drill Coordinator: Asha (ran the drill)
- Business owner: Ravi (Finance owner) at 2026-11-27T17:02:54
- Application owner: NOT RECORDED
- DR lead: NOT RECORDED

## Evidence and sources

- Runbook: DR-FIN-001 v3.2 - knowledge/runbooks/DR-FIN-001_v3.2.json
- Plan content hash: aa068aa96821541b48bf980bb5bd1ed3c901aa45c08be84aa2963539ea28d232
- Event log: 58 events, hash chain VALID
- Event chain head: cc484138817b084736aa87899f2a0a6cf84ff0fbb5a3d3721e2feca3c3114983
- Actions without a matching approval: 0
- Check results: 5; action records: 3; approval decisions: 3
