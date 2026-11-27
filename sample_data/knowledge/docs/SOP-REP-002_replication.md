---
document_id: SOP-REP-002
version: 3.0
title: Storage and Database Replication SOP
document_type: sop
application: FINANCE-PROD
approval_status: approved
owner: Backup & Storage
last_reviewed: 2026-09-02
---
## 1 Replication lag
Replication lag is the delay between source and target data. The lag threshold for a failover decision is set per drill scenario. If lag is above the threshold, wait and re-check; if it does not recover, pause and escalate.

## 2 Replication group
Finance data volumes and the Finance database replicate in replication group finance-rg.
