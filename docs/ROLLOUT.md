# Production Shadow / Enforce Rollout

## Entry criteria

- Run Production Shadow for 30 days with PostgreSQL, OIDC, adapter health, audit retention, and replay enabled.
- Promote only when replay agreement is at least 99%, false escalation is at most 10%, SLA adherence is at least 95%, and cross-tenant leakage is zero.
- Record daily counts for unsafe allows, degraded evaluations, queue backlog/SLA, overrides, and replay mismatches.

## Staged rollout

Production Enforce is enabled in four stages: 5%, 25%, 50%, then 100%. Hold each stage for at least 24 hours and review the evidence packet before advancing.

## Rollback

Immediately return to Shadow when an unsafe allow, tenant boundary violation, rising replay mismatch, or threshold breach is detected. Preserve the audit packet and purge manifest, stop the promotion, and open an incident.

## Profile rules

- `local_advisory` and `ci_contract` may use development principals and SQLite.
- `staging_enforce` requires PostgreSQL and external migrations.
- `production_shadow` records the enforce verdict without changing the protected action.
- `production_enforce` blocks or queues the protected action according to the final verdict.

The rollout owner signs the release checklist after each stage. Any exception must include an expiry, approver role, tenant, diff hash, context hash, and policy version.
