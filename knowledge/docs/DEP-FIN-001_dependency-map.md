---
document_id: DEP-FIN-001
version: 1.2
title: Finance Recovery Dependency Map
document_type: dependency_map
application: FINANCE-PROD
approval_status: approved
owner: App Lead
last_reviewed: 2026-08-20
---
## 1 Recovery order
Storage, then compute, then database, then application, then DNS and web access, then business validation.

## 2 Rollback order
Rollback runs in the reverse of the order in which actions were applied: DNS first, then application configuration, then database.
