---
document_id: DR-POL-001
version: 2.0
title: Enterprise DR Strategy and Policy
document_type: dr_plan
application: ALL
approval_status: approved
owner: Platform Resilience
last_reviewed: 2026-08-01
---
## 1 Recovery objectives
Tier 1 applications target a recovery time objective (RTO) of 4 hours and a recovery point objective (RPO) of 30 minutes.

## 2 Approvals
Every state-changing recovery action requires explicit approval from the drill coordinator. Rollback is a state-changing action and needs its own approval. Ambiguous replies such as continue or looks good are not approval.

## 3 Drill success
A drill may be declared successful only when all mandatory steps, validations and the business sign-off are complete.
