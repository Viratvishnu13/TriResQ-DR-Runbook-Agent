---
document_id: RPT-FIN-2026-05
version: 1.0
title: Prior Finance DR Drill Report (May 2026)
document_type: prior_drill_report
application: FINANCE-PROD
approval_status: approved
owner: DR Lead
last_reviewed: 2026-05-28
---
## Lessons learned
DNS time to live was not lowered before the previous drill, which delayed traffic shift. Verify TTL is 60 seconds before the DNS step.

## Open actions
Pre-warm the DR application pool before re-pointing. Owner: App Lead.
