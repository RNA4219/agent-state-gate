---
intent_id: INT-002
owner: agent-state-gate-team
status: active
last_reviewed_at: 2026-04-26
next_review_due: 2026-05-26
---

# agent-state-gate Evaluation

## 1. 受入基準 (Acceptance Criteria)

### P0 MVP必須

| AC-ID | 条件 | 検証方法 |
|---|---|---|
| AC-001 | DecisionPacket ingestion正常動作 | gatefield_adapter.evaluate() → DecisionPacket schema valid |
| AC-002 | Assessment assembly正常動作 | assessment_engine.assemble_assessment() → Assessment valid |
| AC-003 | Verdict transformation 9条件正確 | verdict_transformer.transform() → verdict match expected |
| AC-004 | Human Queue routing正確 | HumanQueueItem severity → required_role mapping |
| AC-005 | SLA enforcement動作 | enforce_sla() → SLAAction AUTO_BLOCK on timeout |
| AC-006 | typed_ref canonical出力 | 全adapter出力 typed_ref 4-segment format |
| AC-007 | Waiver審査プロセス動作 | waiver.request → review → approve/reject |
| AC-008 | Audit packet生成 | audit_packet_generator.generate() → AuditPacket valid |
| AC-009 | Replay再現性 >= 99% | run.replay_context() → historical decision match |

### P1 Production enforce必須

| AC-ID | 条件 | 検証方法 |
|---|---|---|
| AC-010 | Risk derivation閾値適用 | thresholds.taboo_warn >= 0.80 → needs_approval |
| AC-011 | Contribution weight計算 | causal_trace sum contribution_weight = 1.0 |
| AC-012 | Approval binding | diff_hash変更 → 既存approval無効化 |
| AC-013 | Evidence completeness >= 85% | evidence_summary.evidence_strength >= 0.85 |

---

## 2. 探索テストチャーター (Exploratory Test Charters)

### 2.1 State Gate探索

| Charter-ID | Scope | Questions | Timebox |
|---|---|---|---|
| CHARTER-001 | DecisionPacket edge cases | 1. taboo_proximity = 0.79時のverdict? 2. factors空配列時の動作? 3. hard_override同時発火時のpriority? | **2h** |
| CHARTER-002 | Stale check race condition | 1. stale_check中にversion更新されたら? 2. doc_id不存在時のfallback? 3. stale_reasons複数時のpriority? | **1.5h** |
| CHARTER-003 | Verdict transformation conflict | 1. pass + stale + missing approval → verdict? 2. warn + high privilege + reviewer → verdict? 3. hold + SLA timeout → verdict? | **2h** |

### 2.2 Human Queue探索

| Charter-ID | Scope | Questions | Timebox |
|---|---|---|---|
| CHARTER-004 | SLA escalation chain | 1. critical → governance_board通知条件? 2. escalation_level超過時の動作? 3. reviewer不在時のfallback? | **1.5h** |
| CHARTER-005 | Waiver invalidation edge | 1. expiry_date + diff_hash同時変更? 2. policy_version更新中のwaiver? 3. waiver審査中のblocker追加? | **1.5h** |
| CHARTER-006 | Multi-reviewer conflict | 1. 2 reviewers同時take? 2. resolution不一致時? 3. escalate後のresolution priority? | **1h** |

### 2.3 Adapter Integration探索

| Charter-ID | Scope | Questions | Timebox |
|---|---|---|---|
| CHARTER-007 | Adapter timeout handling | 1. gatefield timeout時のfail-closed動作? 2. 複数adapter同時timeout? 3. timeout中のpartial result? | **1.5h** |
| CHARTER-008 | typed_ref unknown domain | 1. agent-gatefield domain未登録時? 2. provider=local以外のresolve? 3. entity_id形式不一致? | **1h** |
| CHARTER-009 | Adapter health check cascade | 1. health_check失敗連鎖? 2. partial unavailable時の動作? 3. recovery後のstate復帰? | **1h** |

**探索テスト総Timebox**: **12h** (1.5d)

---

## 3. 検証テスト仕様 (Verification Test Specs)

### 3.1 Oracle Reference Matrix

| AC-ID | Oracle Ref | Observable Expected | Trace To |
|---|---|---|---|
| AC-001 | DATA_TYPES_SPEC DecisionPacket schema (lines 779-1141) | decision_id valid UUID, factors non-empty, verdict in enum | adapter_contract.md:97-173 |
| AC-002 | architecture.md Assessment structure (lines 129-225) | assessment_id valid, causal_trace sum = 1.0, verdict valid | architecture.md:129-225 |
| AC-003 | BLUEPRINT.md Verdict変換規則 (lines 84-95) | 9条件各verdict match expected table | BLUEPRINT.md:84-95 |
| AC-004 | architecture.md Ownership Check Rules (lines 388-394) | required_role match severity mapping | architecture.md:388-394 |
| AC-005 | architecture.md SLA Enforcement Logic (lines 396-440) | SLAAction AUTO_BLOCK on critical timeout | architecture.md:396-440 |
| AC-006 | adapter_contract.md typed_ref format (lines 9-40) | 4-segment output, provider=local fallback | adapter_contract.md:9-40 |
| AC-007 | gate_config.yaml waiver.request_flow (lines 104-112) | submit → review → approve/reject sequence | gate_config.yaml:104-112 |
| AC-008 | architecture.md AuditPacket structure (lines 295-322) | trace_id/span_id valid, retention_class valid | architecture.md:295-322 |
| AC-009 | architecture.md Replay logic (pending) | historical decision match >= 99% | architecture.md:replay_engine |

### 3.2 Observable Expected Results

```python
# AC-001: DecisionPacket ingestion
EXPECTED_AC001 = {
    "schema_version": "1.0.0",
    "decision_id": UUID_PATTERN,       # uuid format
    "run_id": UUID_PATTERN,
    "decision": IN_ENUM(["pass", "warn", "hold", "block"]),
    "factors": NON_EMPTY_ARRAY,        # len >= 1
    "composite_score": IN_RANGE(0.0, 1.0),
    "threshold_version": SHA256_HASH_PATTERN,
}

# AC-002: Assessment assembly
EXPECTED_AC002 = {
    "assessment_id": UUID_PATTERN,
    "decision_packet_ref": TYPED_REF_4SEGMENT,
    "task_id": TYPED_REF_4SEGMENT,
    "final_verdict": IN_ENUM(["allow", "needs_approval", "stale_blocked", "deny"]),
    "causal_trace": {
        "sum_contribution_weight": 1.0,  # exact sum
        "each_weight": IN_RANGE(0.0, 1.0),
    },
}

# AC-003: Verdict transformation 9 conditions
EXPECTED_AC003 = [
    {"input": {"gatefield": "pass", "stale": false, "obligation": true}, "output": "allow"},
    {"input": {"gatefield": "pass", "stale": true}, "output": "stale_blocked"},
    {"input": {"gatefield": "pass", "evidence": false}, "output": "needs_approval"},
    {"input": {"gatefield": "warn", "self_correction": true}, "output": "revise"},
    {"input": {"gatefield": "warn", "high_privilege": true}, "output": "require_human"},
    {"input": {"gatefield": "hold", "reviewer_needed": true}, "output": "needs_approval"},
    {"input": {"gatefield": "hold", "sla_timeout": true}, "output": "deny"},
    {"input": {"gatefield": "block", "static_fail": true}, "output": "deny"},
    {"input": {"gatefield": "block", "taboo_critical": true}, "output": "deny"},
]
```

### 3.3 Trace Reference Chain

```
gate.evaluate(task_id, action, capabilities)
    │
    ├──→ gatefield_adapter.evaluate()
    │       └──→ DecisionPacket (DATA_TYPES_SPEC:779-1141)
    │
    ├──→ memx_adapter.resolve_docs()
    │       └──→ ResolveDocsResult (adapter_contract:309-322)
    │
    ├──→ taskstate_adapter.get_context_bundle()
    │       └──→ ContextBundle (adapter_contract:232-256)
    │
    ├──→ assessment_engine.assemble_assessment()
    │       └──→ Assessment (architecture:129-225)
    │           └──→ causal_trace: List[CausalStep]
    │                   └──→ contribution_weight calculation (architecture:section 4.1)
    │
    └──→ verdict_transformer.transform()
            └──→ Verdict (BLUEPRINT:84-95)
                └──→ EvaluateResult (api_spec:88-98)
```

---

## 4. 品質指標 (Quality Metrics)

### 3.1 Gate判定品質

| Metric | Target | Measurement |
|---|---:|---|
| Recall precision | >= 95% | gold task → docs mapping 正答率 |
| Invalidation correctness | >= 99% | stale検出 正答率 |
| Verdict consistency | >= 99% | same input → same verdict (replay) |

### 3.2 Human Queue品質

| Metric | Target | Measurement |
|---|---:|---|
| SLA compliance | >= 95% | critical ACK within 15min |
| False escalation rate | <= 15% | escalated items not requiring escalation |
| Resolution within deadline | >= 90% | all severity decision deadlines |

### 3.3 Audit品質

| Metric | Target | Measurement |
|---|---:|---|
| Trace completeness | 100% | trace_id/span_id coverage |
| Audit reproducibility | >= 99% | historical replay match rate |
| Evidence strength | >= 85% | collected / required ratio |

---

## 4. 回帰テスト観点

### 4.1 Policy変更影響

| Test-ID | Scenario | Expected |
|---|---|---|
| REG-001 | thresholds.taboo_warn 0.80 → 0.75 | previously needs_approval → allow? |
| REG-002 | authority_hierarchy変更 | conflict resolution priority変化確認 |
| REG-003 | reviewer_roles追加 | routing mapping更新確認 |

### 4.2 Adapterバージョン更新

| Test-ID | Scenario | Expected |
|---|---|---|
| REG-004 | gatefield DATA_TYPES_SPEC更新 | DecisionPacket schema migration |
| REG-005 | taskstate typed_ref拡張 | domain extension動作確認 |
| REG-006 | workflow-cookbook evidence format変更 | EvidenceReport parsing確認 |

---

## 5. Gate判定基準

### 5.1 MVP Release Gate

| Check | Required | Evidence |
|---|---|---|
| P0 AC全項目PASS | Yes | test results |
| Coverage >= 80% | Yes | pytest --cov report |
| 探索テストtimebox完了 | Yes | charter log |
| Regression test PASS | Yes | REG-001~REG-006 |
| Documentation complete | Yes | docs/ validation |

### 5.2 Production Enforce Gate

| Check | Required | Evidence |
|---|---|---|
| P0 + P1 AC全項目PASS | Yes | test results |
| Quality metrics全項目達成 | Yes | metrics dashboard |
| Shadow mode >= 14 days | Yes | shadow log analysis |
| False escalation <= 15% | Yes | escalation audit |
| Security review approved | Yes | security_reviewer approval |

---

更新日: 2026-04-26