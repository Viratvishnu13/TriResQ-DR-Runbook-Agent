# Disaster Recovery Drill Report

> **SIMULATION ONLY. Every check and action result in this report comes from scenario files or from simulated conditions a person set, which are listed. Nothing here proves that real infrastructure can be recovered.**

## Executive summary

- Drill ID: drill-20261127-220ed4
- Application: FINANCE-PROD
- Scenario: DNS timeout - reverse-order rollback (`dns_failure_rollback`)
- Drill date: 2026-11-27 (UTC)
- Runbook: DR-FIN-001 v3.2 (approved)
- Conditions set by a person during the drill: 0
- **Overall result: Fail**
- Steps completed: 5/11; deviations: 1; retries: 0

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
| Database | 2h 0m 0s | 1m 39s | 1m 0s | rolled_back |
| Application | 3h 0m 0s | not measured | not measured | rolled_back |
| Business service | 4h 0m 0s | not measured | not measured | not_measured |

| Metric | Target | Observed | Status |
|---|---|---|---|
| Overall RTO | 4h 0m 0s | not measured | not_measured |
| RPO | 30m 0s | 10m 0s | met |
| Drill completion time | 4h 0m 0s | 5m 45s | rolled_back |

Tiers run in sequence in this runbook, so no tier durations overlap.

Approval wait 0s; simulated action time 4m 53s; validation time 12s.

## Timeline

| Timestamp (UTC) | Event | Step | Actor | Result | Summary |
|---|---|---|---|---|---|
| 2026-11-27T17:00:07 | DRILL_CREATED | - | Asha | success | Drill created for FINANCE-PROD, scenario dns_failure_rollback. |
| 2026-11-27T17:00:07 | RUNBOOK_RETRIEVED | - | Drill Coordinator | success | Retrieved DR-FIN-001 v3.2 from the local knowledge base. |
| 2026-11-27T17:00:07 | RUNBOOK_VALIDATED | - | Drill Coordinator | success | Runbook is approved, current and complete. |
| 2026-11-27T17:00:07 | PLAN_CONFIRMED | - | Asha | success | Plan of 11 steps confirmed. |
| 2026-11-27T17:00:07 | DRILL_AUTHORIZED | - | Asha | success | Drill authorization and simulation-only nature confirmed. |
| 2026-11-27T17:00:07 | DRILL_STARTED | - | Asha | success | SIMULATED drill started. RTO clock running. |
| 2026-11-27T17:00:07 | STEP_READY | DR-KICKOFF-01 | Drill Coordinator | success | DR-KICKOFF-01 ready: Record drill kickoff communication (DR-FIN-001 v3.2 section 3.1). |
| 2026-11-27T17:00:07 | COMMUNICATION_RECORDED | DR-KICKOFF-01 | Drill Coordinator | success | Draft recorded (not sent). |
| 2026-11-27T17:00:07 | STEP_COMPLETED | DR-KICKOFF-01 | Drill Coordinator | success | DR-KICKOFF-01 completed. |
| 2026-11-27T17:00:07 | STEP_READY | DR-REPL-02 | Drill Coordinator | success | DR-REPL-02 ready: Verify replication health and recovery point (DR-FIN-001 v3.2 section 4.1). |
| 2026-11-27T17:00:07 | CHECK_STARTED | DR-REPL-02 | Drill Coordinator | success | Read-only SIMULATED check_replication (attempt 1). |
| 2026-11-27T17:00:07 | CHECK_COMPLETED | DR-REPL-02 | Failover Operator | success | Lag 4.2s (threshold 10s); recovery point age 600s; RPO met. |
| 2026-11-27T17:00:07 | STEP_COMPLETED | DR-REPL-02 | Drill Coordinator | success | DR-REPL-02 completed. |
| 2026-11-27T17:00:07 | STEP_READY | DR-STOR-03 | Drill Coordinator | success | DR-STOR-03 ready: Validate DR storage readiness (DR-FIN-001 v3.2 section 4.2). |
| 2026-11-27T17:00:07 | CHECK_STARTED | DR-STOR-03 | Drill Coordinator | success | Read-only SIMULATED check_health (attempt 1). |
| 2026-11-27T17:00:07 | CHECK_COMPLETED | DR-STOR-03 | Failover Operator | success | Simulated storage health: healthy. |
| 2026-11-27T17:00:07 | STEP_COMPLETED | DR-STOR-03 | Drill Coordinator | success | DR-STOR-03 completed. |
| 2026-11-27T17:00:07 | STEP_READY | DR-INFRA-04 | Drill Coordinator | success | DR-INFRA-04 ready: Validate DR compute readiness (DR-FIN-001 v3.2 section 4.3). |
| 2026-11-27T17:00:07 | CHECK_STARTED | DR-INFRA-04 | Drill Coordinator | success | Read-only SIMULATED check_health (attempt 1). |
| 2026-11-27T17:00:07 | CHECK_COMPLETED | DR-INFRA-04 | Failover Operator | success | Simulated compute health: healthy. |
| 2026-11-27T17:00:07 | STEP_COMPLETED | DR-INFRA-04 | Drill Coordinator | success | DR-INFRA-04 completed. |
| 2026-11-27T17:00:07 | STEP_READY | DR-DB-05 | Drill Coordinator | success | DR-DB-05 ready: Fail over Finance database to DR (SIMULATED) (DR-FIN-001 v3.2 section 5.1). |
| 2026-11-27T17:00:07 | APPROVAL_REQUESTED | DR-DB-05 | Drill Coordinator | pending | Approval required for SIMULATED failover_database on DR-DB-05. |
| 2026-11-27T17:00:07 | APPROVAL_GRANTED | DR-DB-05 | Asha | success | Asha approved failover_database. |
| 2026-11-27T17:00:07 | ACTION_DISPATCHED | DR-DB-05 | Drill Coordinator | pending | Dispatched SIMULATED failover_database to the Failover Operator. |
| 2026-11-27T17:00:07 | ACTION_COMPLETED | DR-DB-05 | Failover Operator | success | Simulated failover_database completed. |
| 2026-11-27T17:00:07 | STEP_COMPLETED | DR-DB-05 | Drill Coordinator | success | DR-DB-05 completed. |
| 2026-11-27T17:00:07 | STEP_READY | DR-DB-06 | Drill Coordinator | success | DR-DB-06 ready: Validate database at DR (DR-FIN-001 v3.2 section 5.2). |
| 2026-11-27T17:00:07 | CHECK_STARTED | DR-DB-06 | Drill Coordinator | success | Read-only SIMULATED check_health (attempt 1). |
| 2026-11-27T17:00:07 | CHECK_COMPLETED | DR-DB-06 | Failover Operator | success | Simulated database health: healthy. |
| 2026-11-27T17:00:07 | VALIDATION_COMPLETED | DR-DB-06 | Drill Coordinator | success | Validate database at DR: passed. |
| 2026-11-27T17:00:07 | STEP_COMPLETED | DR-DB-06 | Drill Coordinator | success | DR-DB-06 completed. |
| 2026-11-27T17:00:07 | STEP_READY | DR-APP-07 | Drill Coordinator | success | DR-APP-07 ready: Re-point Finance application to DR database (SIMULATED) (DR-FIN-001 v3.2 section 6.1). |
| 2026-11-27T17:00:07 | APPROVAL_REQUESTED | DR-APP-07 | Drill Coordinator | pending | Approval required for SIMULATED repoint_application on DR-APP-07. |
| 2026-11-27T17:00:07 | APPROVAL_GRANTED | DR-APP-07 | Asha | success | Asha approved repoint_application. |
| 2026-11-27T17:00:07 | ACTION_DISPATCHED | DR-APP-07 | Drill Coordinator | pending | Dispatched SIMULATED repoint_application to the Failover Operator. |
| 2026-11-27T17:00:07 | ACTION_COMPLETED | DR-APP-07 | Failover Operator | success | Simulated repoint_application completed. |
| 2026-11-27T17:00:07 | STEP_COMPLETED | DR-APP-07 | Drill Coordinator | success | DR-APP-07 completed. |
| 2026-11-27T17:00:07 | STEP_READY | DR-DNS-08 | Drill Coordinator | success | DR-DNS-08 ready: Shift Finance DNS to DR load balancer (SIMULATED) (DR-FIN-001 v3.2 section 6.2). |
| 2026-11-27T17:00:07 | APPROVAL_REQUESTED | DR-DNS-08 | Drill Coordinator | pending | Approval required for SIMULATED update_dns on DR-DNS-08. |
| 2026-11-27T17:00:07 | APPROVAL_GRANTED | DR-DNS-08 | Asha | success | Asha approved update_dns. |
| 2026-11-27T17:00:07 | ACTION_DISPATCHED | DR-DNS-08 | Drill Coordinator | pending | Dispatched SIMULATED update_dns to the Failover Operator. |
| 2026-11-27T17:00:07 | ACTION_TIMED_OUT | DR-DNS-08 | Failover Operator | timed_out | Simulated DNS propagation timed out; record is partially propagated. |
| 2026-11-27T17:00:07 | ROLLBACK_REQUESTED | DR-DNS-08 | Drill Coordinator | pending | Reverse-order rollback: DR-DNS-08 -> DR-APP-07 -> DR-DB-05. Each step needs approval. |
| 2026-11-27T17:00:07 | APPROVAL_REQUESTED | DR-DNS-08 | Drill Coordinator | pending | Approval required for SIMULATED rollback_step on DR-DNS-08. |
| 2026-11-27T17:00:07 | ROLLBACK_APPROVED | DR-DNS-08 | Asha | success | Asha approved rollback_step. |
| 2026-11-27T17:00:07 | ACTION_DISPATCHED | DR-DNS-08 | Drill Coordinator | pending | Dispatched SIMULATED rollback_step to the Failover Operator. |
| 2026-11-27T17:00:07 | ROLLBACK_COMPLETED | DR-DNS-08 | Failover Operator | success | DR-DNS-08 rolled back. Simulated rollback_step completed. |
| 2026-11-27T17:00:07 | APPROVAL_REQUESTED | DR-APP-07 | Drill Coordinator | pending | Approval required for SIMULATED rollback_step on DR-APP-07. |
| 2026-11-27T17:00:07 | ROLLBACK_APPROVED | DR-APP-07 | Asha | success | Asha approved rollback_step. |
| 2026-11-27T17:00:07 | ACTION_DISPATCHED | DR-APP-07 | Drill Coordinator | pending | Dispatched SIMULATED rollback_step to the Failover Operator. |
| 2026-11-27T17:00:07 | ROLLBACK_COMPLETED | DR-APP-07 | Failover Operator | success | DR-APP-07 rolled back. Simulated rollback_step completed. |
| 2026-11-27T17:00:07 | APPROVAL_REQUESTED | DR-DB-05 | Drill Coordinator | pending | Approval required for SIMULATED rollback_step on DR-DB-05. |
| 2026-11-27T17:00:08 | ROLLBACK_APPROVED | DR-DB-05 | Asha | success | Asha approved rollback_step. |
| 2026-11-27T17:00:08 | ACTION_DISPATCHED | DR-DB-05 | Drill Coordinator | pending | Dispatched SIMULATED rollback_step to the Failover Operator. |
| 2026-11-27T17:00:08 | ROLLBACK_COMPLETED | DR-DB-05 | Failover Operator | success | DR-DB-05 rolled back. Simulated rollback_step completed. |
| 2026-11-27T17:00:08 | VALIDATION_COMPLETED | - | Drill Coordinator | success | Rollback validation: simulated environment matches its pre-drill action state. |
| 2026-11-27T17:00:08 | DRILL_COMPLETED | - | Drill Coordinator | failed | Drill ended after rollback. Recovery NOT achieved. |
| 2026-11-27T17:00:08 | REPORT_GENERATED | - | Drill Coordinator | success | Report generated: Fail. |

## Step execution summary

| Step ID | Step | Owner | Status | Attempts | Duration | Approval | Evidence | Source |
|---|---|---|---|---|---|---|---|---|
| DR-KICKOFF-01 | Record drill kickoff communication | Incident Management | completed | 0 | 0s | - | evidence-comms-DR-KICKOFF-01 | DR-FIN-001 v3.2 section 3.1 |
| DR-REPL-02 | Verify replication health and recovery point | DB On-call | completed | 1 | 15s | - | evidence-chk-220ed4-DR-REPL-02-1 | DR-FIN-001 v3.2 section 4.1 |
| DR-STOR-03 | Validate DR storage readiness | Backup & Storage | completed | 1 | 12s | - | evidence-chk-220ed4-DR-STOR-03-1 | DR-FIN-001 v3.2 section 4.2 |
| DR-INFRA-04 | Validate DR compute readiness | Compute Platform | completed | 1 | 12s | - | evidence-chk-220ed4-DR-INFRA-04-1 | DR-FIN-001 v3.2 section 4.3 |
| DR-DB-05 | Fail over Finance database to DR (SIMULATED) | DB Lead | rolled_back | 1 | 48s | apr-00001, apr-00006 | evidence-220ed4-act-00001, evidence-220ed4-act-00006 | DR-FIN-001 v3.2 section 5.1 |
| DR-DB-06 | Validate database at DR | DB Lead | completed | 1 | 12s | - | evidence-chk-220ed4-DR-DB-06-1 | DR-FIN-001 v3.2 section 5.2 |
| DR-APP-07 | Re-point Finance application to DR database (SIMULATED) | App Lead | rolled_back | 1 | 35s | apr-00002, apr-00005 | evidence-220ed4-act-00002, evidence-220ed4-act-00005 | DR-FIN-001 v3.2 section 6.1 |
| DR-DNS-08 | Shift Finance DNS to DR load balancer (SIMULATED) | NetOps | rolled_back | 1 | not measured | apr-00003, apr-00004 | evidence-220ed4-act-00003, evidence-220ed4-act-00004 | DR-FIN-001 v3.2 section 6.2 |
| DR-APP-09 | Validate Finance application end to end | SRE On-call | pending | 0 | not measured | - | - | DR-FIN-001 v3.2 section 6.3 |
| DR-BIZ-10 | Business owner acceptance | Finance Business Owner | pending | 0 | not measured | - | - | DR-FIN-001 v3.2 section 8.1 |
| DR-COMMS-11 | Record drill completion communication | Incident Management | pending | 0 | not measured | - | - | DR-FIN-001 v3.2 section 8.2 |

## Approval record

| Approval | Step | Tool | Approver | Decision | Decided (UTC) | Parameter hash | Rationale |
|---|---|---|---|---|---|---|---|
| apr-00001 | DR-DB-05 | failover_database | Asha | approved | 2026-11-27T17:00:07 | 05409597100c | - |
| apr-00002 | DR-APP-07 | repoint_application | Asha | approved | 2026-11-27T17:00:07 | eb3d67fbdb3e | - |
| apr-00003 | DR-DNS-08 | update_dns | Asha | approved | 2026-11-27T17:00:07 | 4b8e44855cec | - |
| apr-00004 | DR-DNS-08 | rollback_step | Asha | approved | 2026-11-27T17:00:07 | 5405822d9a80 | - |
| apr-00005 | DR-APP-07 | rollback_step | Asha | approved | 2026-11-27T17:00:07 | 7d4fde01c4ff | - |
| apr-00006 | DR-DB-05 | rollback_step | Asha | approved | 2026-11-27T17:00:08 | f3e412f21b9b | - |

## Deviations and issues

| ID | Step | Description | Impact | Severity | Resolution |
|---|---|---|---|---|---|
| DEV-01 | DR-DNS-08 | Shift Finance DNS to DR load balancer (SIMULATED): Simulated DNS propagation timed out; record is partially propagated. | Drill left the nominal path. | high | Open |

## Rollback

- Rollback required: Yes
- Reason: Automatic rollback: Simulated DNS propagation timed out; record is partially propagated.
- Steps rolled back (in order): DR-DNS-08, DR-APP-07, DR-DB-05
- Not rolled back: none
- Approvals: apr-00004, apr-00005, apr-00006
- Result: success

## Lessons learned

**What worked well**

- DR-KICKOFF-01 Record drill kickoff communication
- DR-REPL-02 Verify replication health and recovery point
- DR-STOR-03 Validate DR storage readiness
- DR-INFRA-04 Validate DR compute readiness
- DR-DB-06 Validate database at DR

**What did not work**

- DR-DNS-08: Shift Finance DNS to DR load balancer (SIMULATED): Simulated DNS propagation timed out; record is partially propagated.

**Runbook gaps**

- None recorded.

**Coordination gaps**

- None recorded.

**Carried forward from the prior drill**

- Lessons learned: DNS time to live was not lowered before the previous drill, which delayed traffic shift. Verify TTL is 60 seconds before the DNS step. [RPT-FIN-2026-05 v1.0]
- Open actions: Pre-warm the DR application pool before re-pointing. Owner: App Lead. [RPT-FIN-2026-05 v1.0]

## Improvement actions

| Action | Priority | Owner | Target date | Status |
|---|---|---|---|---|
| Investigate and remediate DEV-01 (DR-DNS-08): Shift Finance DNS to DR load balancer (SIMULATED): Simulated DNS propagation timed out; record is partially propagated. | P1 | NetOps | 2026-12-11 | Open |

## Sign-off

- Drill Coordinator: Asha (ran the drill)
- Business owner: NOT RECORDED
- Application owner: NOT RECORDED
- DR lead: NOT RECORDED

## Evidence and sources

- Runbook: DR-FIN-001 v3.2 - knowledge/runbooks/DR-FIN-001_v3.2.json
- Plan content hash: aa068aa96821541b48bf980bb5bd1ed3c901aa45c08be84aa2963539ea28d232
- Event log: 59 events, hash chain VALID
- Event chain head: bb71d8f1ced49c08d54f1dbe6a1107447d09c4fa12e6f92739eab8d2c5c9b37e
- Actions without a matching approval: 0
- Check results: 4; action records: 6; approval decisions: 6
