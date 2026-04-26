---
intent_id: INT-002
owner: agent-state-gate-team
status: active
last_reviewed_at: 2026-04-26
next_review_due: 2026-05-26
---

# agent-state-gate BLUEPRINT

## 1. 目的

Context Graph拡張とState-space Gate統合ハーネスの工程統治統合層として、既存6資産を横断する制御面を提供。

## 2. 背景

既存の Context Graph系実装は「記憶レイヤー」として十分だが、「実行統治レイヤー」には届いていない：
- 義務、権限、証跡、承認、工程遷移、差分、スコープ逸脱、禁忌接近、人間注意の配線

本プロジェクトは、既存資産を奪わず、二つの追加層として統合統治を提供。

## 3. 正本境界

| オブジェクト | 生成者 | 正本保存先 | 主参照者 |
|---|---|---|---|
| Task/Run/ContextBundle | agent-taskstate | agent-taskstate | 本プロジェクト |
| DecisionPacket | agent-gatefield | agent-gatefield | 本プロジェクト |
| Assessment | 本プロジェクト | 本プロジェクト | agent-context-mcp, shipyard-cp |
| Evidence | workflow-cookbook | Evidence store | 本プロジェクト |
| Approval/Waiver | agent-protocols + human workflow | agent-protocols compatible | 本プロジェクト |
| Human Queue Item | 本プロジェクト + agent-gatefield | agent-gatefield + task/run binding | reviewer console |

## 4. 設計制約

### 4.1 言語・環境
- Python 3.11+
- pydantic for data validation
- pytest for testing

### 4.2 接続対象
- agent-gatefield: Python
- memx-resolver: Python/Go
- agent-taskstate: Python
- agent-protocols: TypeScript/JSON Schema
- shipyard-cp: TypeScript/HTTP API
- workflow-cookbook: Markdown/JSON

### 4.3 MCP原則
- read-heavy / write-light / dangerous mutation internal-only
- 明示的 consent と human-in-the-loop

## 5. MVP定義 (P0)

### 5.1 必須機能
1. DecisionPacket ingestion (gatefield_adapter)
2. Assessment assembly (assessment_engine)
3. Verdict transformation (verdict_transformer)
4. Human Attention Queue (human_attention_queue)
5. Approval binding/freshness
6. Evidence.record
7. Attested context snapshot
8. Minimal replay
9. Audit packet v0

### 5.2 MCP Surface
- context.recall
- gate.evaluate
- context.stale_check
- state_gate.assess
- attention.list

### 5.3 成功条件
| 項目 | 条件 |
|---|---|
| Docs resolve | task/action から required docs 返る |
| Stale check | version差分で stale 検出 |
| Gate evaluate | allow/needs_approval/stale_blocked/block 返る |
| State gate | taboo/rejected-case/drift 3軸評価 |
| Human queue | 例外だけ queue 送られる |
| Approval freshness | diff変更後古い approval 無効化 |
| Audit | why/how/which refs 追跡可能 |
| Replay | run単位で過去評価再現 |

### 5.4 Release Stage定義

| Stage | Enforce Mode | Entry Criteria |
|---|---|---|
| **MVP (P0)** | advisory | P0 AC全項目PASS, Coverage >= 80%, Documentation complete |
| **P1** | shadow | P1 AC全項目PASS, Shadow mode >= 14 days, False escalation <= 15% |
| **Production Enforce** | blocking | **以下のentry criteria全項目満たす必要** |

**Production Enforce Entry Criteria (必須)**:
| Criteria | Requirement | Status |
|---|---|---|
| **Auth基盤決定済み** | auth provider選定、token validation、role mapping実装完了 | 未指定 |
| **Tenant境界決定済み** | tenant_id scope、cross-tenant isolation、data residency定義完了 | 未指定 |
| **Retention policy決定済み** | audit/ops/pii-sensitive retention days、purge mechanism定義完了 | 未指定 |
| **Security review approved** | security_reviewer approval取得済み | 未指定 |
| **Operational KPI達成** | SLA compliance >= 95%, Review load reduction >= 30% | 未指定 |
| **Shadow mode validation** | Shadow mode >= 30 days, False positive <= 10% | 未指定 |

**未指定事項の後段選定** (P0/P1完了後に決定):
- Auth provider: OAuth2.0 / SAML / API Key (P0完了後に選定)
- Tenant境界: single-tenant / multi-tenant (P1完了後に選定)
- Retention mechanism: TTL-based purge / manual archive (P1完了後に選定)

**重要: Production Enforceは上記entry criteria全項目満たすまでblocking不可**
- advisory/shadow stageではauth/tenant/retention未指定で動作可能
- blocking stageに移行する前に、運用安全性判定のために全criteria満たす必要

---

## 6. Verdict変換規則 (分岐条件固定)

| gatefield decision | 統合条件 | 外部 verdict | 分岐条件詳細 |
|---|---|---|---|
| pass | staleなし、obligation充足、approval充足 | allow | 全条件満たす → allow確定 |
| pass | required docs/approvalがstale | stale_blocked | stale検出 → stale_blocked確定 (priority最高) |
| pass | evidence不足のみ | needs_approval | evidence_strength < 0.85 → needs_approval |
| pass | obligation不足のみ | require_human | obligation未充足 → severityに応じrequire_human/deny分岐 |
| pass | evidence + obligation双方不足 | needs_approval | evidence不足がprimary → needs_approval |
| warn | self-correction可能 | revise | self_correction_count < 2 → revise |
| warn | 高権限 + uncertainty高 | require_human | permission_level=admin + uncertainty >= 0.15 → require_human |
| warn | reviewer必須 | require_human | required_role指定あり → require_human |
| hold | reviewer判断必要 + approval欠落 | needs_approval | approval_missing → needs_approval |
| hold | reviewer判断必要 + 判断欠落 | require_human | judgment_missing → require_human |
| hold | SLA timeout | deny | sla_deadline exceeded → deny (severity=critical) |
| hold | reviewer reject | deny | resolution.reject → deny |
| block | static hard fail | deny | sast_high > 0 or lint_error > 0 → deny確定 |
| block | taboo critical | deny | taboo_proximity >= 0.88 → deny確定 |
| block | secret found | deny | secret > 0 → deny確定 (hard override) |

**分岐決定フロー**:
```python
def resolve_verdict(
    decision: str,
    stale_summary: StaleSummary,
    obligation_summary: ObligationSummary,
    approval_summary: ApprovalSummary,
    evidence_summary: EvidenceSummary,
    permission_level: str,
    uncertainty_score: float
) -> Verdict:
    """gatefield decision → 外部 verdict変換 (分岐条件固定)"""
    
    # Priority 1: Hard override (block → deny確定)
    if decision == "block":
        return Verdict.DENY
    
    # Priority 2: Stale detection (stale → stale_blocked確定)
    if stale_summary.fresh == False:
        return Verdict.STALE_BLOCKED
    
    # Priority 3: Pass分岐
    if decision == "pass":
        # 3a: Evidence不足 → needs_approval
        if evidence_summary.evidence_strength < 0.85:
            return Verdict.NEEDS_APPROVAL
        
        # 3b: Obligation不足 → severity分岐
        if obligation_summary.fulfillment_rate < 1.0:
            # critical obligation未充足 → deny (安全上重要)
            if obligation_summary.has_critical_unfulfilled:
                return Verdict.DENY
            # high obligation未充足 → require_human
            elif obligation_summary.has_high_unfulfilled:
                return Verdict.REQUIRE_HUMAN
            # medium/low → needs_approval
            else:
                return Verdict.NEEDS_APPROVAL
        
        # 3c: 全充足 → allow
        return Verdict.ALLOW
    
    # Priority 4: Warn分岐
    if decision == "warn":
        # 4a: Self-correction可能 → revise
        if self_correction_count < 2:
            return Verdict.REVISE
        
        # 4b: 高権限 + uncertainty → require_human
        if permission_level == "admin" and uncertainty_score >= 0.15:
            return Verdict.REQUIRE_HUMAN
        
        # 4c: Reviewer必須 → require_human
        if approval_summary.required_approvals:
            return Verdict.REQUIRE_HUMAN
        
        return Verdict.REVISE
    
    # Priority 5: Hold分岐
    if decision == "hold":
        # 5a: Approval欠落 → needs_approval
        if approval_summary.missing_approvals:
            return Verdict.NEEDS_APPROVAL
        
        # 5b: 判断欠落 → require_human
        if uncertainty_score >= 0.25:
            return Verdict.REQUIRE_HUMAN
        
        # 5c: SLA timeout → deny
        if sla_status == "timeout":
            return Verdict.DENY
        
        # 5d: Reviewer pending → needs_approval (default)
        return Verdict.NEEDS_APPROVAL
    
    return Verdict.ALLOW
```

**決定表 (Decision Table)**:
| decision | stale | evidence<0.85 | obligation<1.0 | permission=admin | uncertainty>=0.15 | verdict |
|---|---|---|---|---|---|---|
| pass | false | false | false | - | - | allow |
| pass | true | - | - | - | - | stale_blocked |
| pass | false | true | false | - | - | needs_approval |
| pass | false | false | true(critical) | - | - | deny |
| pass | false | false | true(high) | - | - | require_human |
| pass | false | false | true(medium) | - | - | needs_approval |
| warn | - | - | - | false | <0.15 | revise |
| warn | - | - | - | true | >=0.15 | require_human |
| hold | - | - | - | - | <0.25 | needs_approval |
| hold | - | - | - | - | >=0.25 | require_human |
| block | - | - | - | - | - | deny |

## 7. Adapter契約

| Adapter | 必須インタフェース | 操作種別 |
|---|---|---|
| workflow-cookbook | get_birdseye_caps, get_acceptance_index, get_evidence_report | read-only |
| memx-resolver | resolve_docs, stale_check, resolve_contract | read + append-only ack |
| agent-taskstate | get_task, get_context_bundle, record_read_receipt | read + append-only event |
| agent-protocols | derive_risk_level, derive_required_approvals | read-only |
| shipyard-cp | get_pipeline_stage, hold_for_review | read + controlled mutation |
| agent-gatefield | evaluate, enqueue_review, export_audit | read + append-only decision |

## 8. セキュリティ制約

| 制御 | 既定 | 目的 |
|---|---|---|
| Taint tracking | 必須 | untrusted contextのpolicy上書き防止 |
| Authority hierarchy | 必須 | human policy > repo policy > task contract |
| Secret handling | 必須 | external LLM/storageへ未加工secret渡さない |
| Approval binding | 必須 | 古い承認の使い回し防止 |

## 9. 品質指標

| 指標 | 定義 | 最小ベンチ案 |
|---|---|---|
| Recall precision | required docs正答率 | gold task→docs mapping |
| Invalidation correctness | stale正答率 | version/diff replay |
| Evidence completeness | required evidence比率 | stageごとgold checklist |
| Gate regression impact | policy変更でのverdict変化 | shadow + historical replay |
| Audit reproducibility | replay再現率 | attested snapshot replay |

## 10. ガードレール

- 二重実装禁止: agent-gatefieldのscore再計算を原則行わず、DecisionPacketを読み取って統合判断へ変換
- 正本尊重: 既存資産の責務を奪わない
- MCP surface制限: remember/relate/invalidate/policy mutate/publish apply は内部API

更新日: 2026-04-26