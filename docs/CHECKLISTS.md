---
intent_id: INT-002
owner: agent-state-gate-team
status: active
last_reviewed_at: 2026-04-26
next_review_due: 2026-05-26
---

# agent-state-gate Checklists

## 1. MVP Release Checklist

### 1.1 Code Quality

| Item | Criteria | Status |
|---|---|---|
| Unit tests | `pytest` passes | [ ] |
| Coverage | >= 80% | [ ] |
| Ruff lint | 0 errors | [ ] |
| CLI entry | `agent-state-gate --help` works | [ ] |
| Type hints | All public functions typed | [ ] |

### 1.2 Documentation

| Item | Criteria | Status |
|---|---|---|
| README.md | Exists, references valid | [ ] |
| docs/requirements.md | Exists | [ ] |
| docs/architecture.md | Exists | [ ] |
| docs/api_spec.md | Exists | [ ] |
| docs/adapter_contract.md | Exists | [ ] |
| docs/RUNBOOK.md | Exists, runtime policy documented | [ ] |
| docs/CHECKLISTS.md | This file | [ ] |
| CHANGELOG.md | Updated | [ ] |

### 1.3 Functional Tests

| AC-ID | Criteria | Status |
|---|---|---|
| AC-001 | DecisionPacket ingestion | [ ] |
| AC-002 | Assessment assembly | [ ] |
| AC-003 | Verdict transformation 9 conditions | [ ] |
| AC-004 | Human Queue routing | [ ] |
| AC-005 | SLA enforcement | [ ] |
| AC-006 | typed_ref canonical format | [ ] |
| AC-007 | Waiver process | [ ] |
| AC-008 | Audit packet generation | [ ] |
| AC-009 | Replay reproducibility >= 99% | [ ] |
| AC-014 | Runtime portability: Windows native pgvector buildなしでlocal/CI P0 acceptance実行 | [ ] |

### 1.4 MVP Release Gate

| Gate | Criteria | Status |
|---|---|---|
| Test Gate | 93 passed | [ ] |
| Coverage Gate | >= 80% | [ ] |
| Lint Gate | ruff 0 errors | [ ] |
| CLI Gate | `uv run agent-state-gate --help` works | [ ] |
| Docs Gate | All referenced files exist | [ ] |

---

## 2. Review Checklist

### 2.1 Code Review

| Item | Check |
|---|---|
| Imports | No unused imports |
| Naming | Consistent with conventions |
| Error handling | AdapterUnavailableError for adapter failures |
| Dataclass fields | Required before optional, mutable defaults use field(default_factory) |
| Timestamps | Use utc_now() from common.py |
| IDs | Use generate_id() variants from common.py |
| Hashing | Use hash_dict() from common.py |

### 2.2 Architecture Review

| Item | Check |
|---|---|
| Adapter contract | Follows adapter_contract.md interface |
| Verdict logic | Follows BLUEPRINT.md resolve_verdict flow |
| Assessment structure | Follows architecture.md Assessment definition |
| typed_ref format | 4-segment canonical format |
| SLA handling | Follows architecture.md SLA Enforcement |

### 2.3 Security Review

| Item | Check |
|---|---|
| Secret handling | No secret exposure in logs/exports |
| Approval binding | diff_hash check implemented |
| Taint tracking | Untrusted context no policy override |
| Authority hierarchy | human > repo > task contract |

---

## 3. P1 Release Checklist

### 3.1 Production Enforce Entry Criteria

| Criteria | Requirement | Status |
|---|---|---|
| Auth基盤決定済み | auth provider選定、token validation実装 | [ ] |
| Tenant境界決定済み | tenant_id scope、isolation定義 | [ ] |
| Retention policy決定済み | retention days、purge mechanism | [ ] |
| Security review approved | security_reviewer approval | [ ] |
| Operational KPI達成 | SLA compliance >= 95% | [ ] |
| Shadow mode validation | Shadow >= 30 days, FP <= 10% | [ ] |
| Production runtime | 実 PostgreSQL/pgvector backend、schema migration、health check、backup、retention、failure_policy検証済み | [ ] |

### 3.2 P1 Functional Tests

| AC-ID | Criteria | Status |
|---|---|---|
| AC-010 | Risk derivation thresholds | [ ] |
| AC-011 | Contribution weight sum = 1.0 | [ ] |
| AC-012 | Approval binding invalidation | [ ] |
| AC-013 | Evidence completeness >= 85% | [ ] |

---

## 4. Pre-Commit Checklist

| Item | Command |
|---|---|
| Format code | `ruff format .` |
| Check lint | `ruff check . --fix` |
| Run tests | `pytest tests/` |
| Check coverage | `pytest --cov=src --cov-report=term-missing` |
| Verify CLI | `python -m src.cli --help` |

---

## 5. Deployment Checklist

### 5.1 MVP Advisory Mode

| Item | Check |
|---|---|
| Version tag | v0.x.x in pyproject.toml |
| Dependencies | pydantic, pyyaml, requests installed |
| Adapters | Mock/advisory mode documented |
| Runtime | Dockerized pgvector or mock / in-memory contract profile documented |
| Monitoring | Basic logging enabled |
| Rollback plan | Documented |

### 5.2 Production Blocking Mode

| Item | Check |
|---|---|
| Auth configured | Provider connected |
| Tenant isolation | Verified |
| Retention purge | Scheduled |
| PostgreSQL/pgvector | Real backend, extension, schema, index, backup verified |
| KB unavailable policy | high-risk action does not allow silently |
| Monitoring | Full observability |
| Incident response | Playbook ready |

---

更新日: 2026-04-26
