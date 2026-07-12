# v0.5 Release Checklist

- [ ] `uv run pytest --cov=agent_state_gate --cov-fail-under=90 -q`
- [ ] Ruff and mypy are clean on Python 3.11–3.13.
- [ ] Alembic upgrade and downgrade are tested against the target database.
- [ ] PostgreSQL backup/restore and retention purge evidence is attached.
- [ ] OIDC issuer, audience, JWKS, claim mapping, and role mapping are verified.
- [ ] Cross-tenant assessment, queue, audit, approval, and replay queries are isolated.
- [ ] Production profile rejects SQLite, disabled adapters, and unauthenticated principals.
- [ ] Adapter failures produce degraded evidence and a non-allow failure policy.
- [ ] Raw diffs, tokens, secrets, and evidence bodies are absent from logs and persisted payloads.
- [ ] Replay status is `verified`, `mismatch`, or `unavailable`; no placeholder verification is accepted.
- [ ] Shadow has met the 30-day entry criteria and the 99% replay / 10% escalation / 95% SLA thresholds.
- [ ] Enforce stage owner, rollback owner, and incident contact are recorded.
- [ ] Release artifacts contain `agent_state_gate` and the one-release `src` compatibility shim only.
- [ ] sdist is free of caches, coverage files, `.venv`, and internal research material.
- [ ] Security review and changelog entry are complete.

The release manager signs this checklist before publishing the tag.
