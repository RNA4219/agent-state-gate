---
intent_id: INT-002
owner: agent-state-gate-team
status: active
last_reviewed_at: 2026-04-26
next_review_due: 2026-05-26
---

# agent-state-gate Requirements

## Overview

Context Graph拡張とState-space Gate統合ハーネスの工程統治統合層として、既存6資産を横断する制御面を提供。

## Source Documents

このドキュメントは以下の正本から要件を抽出：
- `deep-research-report (9).md`: 要件定義書（外部）
- `BLUEPRINT.md`: 設計制約・MVP定義

## MVP (P0) 必須機能

### 1. DecisionPacket Ingestion

**AC-001**: gatefield_adapter.evaluate() がDecisionPacketを正常取得

| 項目 | 仕様 |
|---|---|
| 入力 | task_id, run_id, context_bundle_ref |
| 出力 | DecisionPacket (decision_id, decision, factors, composite_score) |
| 正本 | agent-gatefield DATA_TYPES_SPEC |
| 制約 | CLI/API接続、timeout 3秒以内 |

### 2. Assessment Assembly

**AC-002**: assessment_engine.assemble_assessment() がAssessmentを正常生成

| 項目 | 仕様 |
|---|---|
| 入力 | DecisionPacket + stale + obligation + approval + evidence |
| 出力 | Assessment (assessment_id, verdict, causal_trace) |
| 正本 | architecture.md Assessment構造 |
| 制約 | causal_trace.contribution_weight sum = 1.0 |

### 3. Verdict Transformation

**AC-003**: verdict_transformer.resolve_verdict() が9条件変換を正確実行

| decision | 条件 | verdict |
|---|---|---|
| pass | staleなし、充足 | allow |
| pass | staleあり | stale_blocked |
| pass | evidence不足 | needs_approval |
| pass | obligation(critical)不足 | deny |
| pass | obligation(high)不足 | require_human |
| warn | self-correction可能 | revise |
| warn | admin + uncertainty高 | require_human |
| hold | approval欠落 | needs_approval |
| block | - | deny |

### 4. Human Attention Queue

**AC-004**: severity → required_role routing正確

| severity | required_role |
|---|---|
| critical | security_reviewer |
| high | domain_reviewer |
| medium | peer_reviewer |
| low | peer_reviewer |

**AC-005**: SLA enforcement動作

| 条件 | action |
|---|---|
| ack timeout (critical) | AUTO_BLOCK |
| decision timeout (critical) | AUTO_BLOCK + escalate |
| decision timeout (high) | ESCALATE |

### 5. Approval Binding/Freshness

**AC-012**: diff_hash変更 → 既存approval無効化

| 条件 | action |
|---|---|
| diff_hash一致 | approval有効 |
| diff_hash変更 | approval.invalidate |
| context_hash変更 | waiver.invalidate |

### 6. Evidence.record

EvidenceRecorderがappend-only証跡記録

| evidence_type | 内容 |
|---|---|
| test_result | CI test pass/fail |
| approval | human approval record |
| artifact | build artifact hash |

### 7. Attested Context Snapshot

run.replay_context用snapshot生成

| 項目 | 仕様 |
|---|---|
| 内容 | DecisionPacket + context_bundle + threshold version |
| hash | SHA256 context_hash |
| 保存 | audit_packet.attested_snapshot_ref |

### 8. Minimal Replay

**AC-009**: historical decision再現 >= 99%

| 項目 | 仕様 |
|---|---|
| 入力 | run_id, historical context |
| 出力 | replay Assessment |
| 条件 | verdict match >= 99% |

### 9. Audit Packet v0

**AC-008**: AuditPacket生成

| 項目 | 仕様 |
|---|---|
| trace_id | OTel format (32 hex) |
| span_id | OTel format (16 hex) |
| retention_class | audit/ops/pii-sensitive |

## MCP Surface API

### context.recall

task/action起点のrequired docs解決

| 入力 | 出力 |
|---|---|
| task_id, action_type | RecallResult (docs, context_bundle_ref) |

### gate.evaluate

統合gate評価

| 入力 | 出力 |
|---|---|
| task_id, run_id | EvaluateResult (verdict, assessment_ref) |

### context.stale_check

stale判定

| 入力 | 出力 |
|---|---|
| task_id, versions | StaleCheckResult (fresh, stale_items) |

### state_gate.assess

State-space gate評価

| 入力 | 出力 |
|---|---|
| task_id, diff | AssessResult (taboo_proximity, scope_drift) |

### attention.list

Human Queue一覧

| 入力 | 出力 |
|---|---|
| status filter | AttentionListResult (items) |

## Adapter契約

| Adapter | 必須インタフェース | 操作種別 |
|---|---|---|
| workflow-cookbook | get_evidence_report, get_acceptance_index | read-only |
| memx-resolver | resolve_docs, stale_check, ack_reads | read + append-only |
| agent-taskstate | get_task, get_context_bundle, record_read_receipt | read + append-only |
| agent-protocols | derive_risk_level, derive_required_approvals | read-only |
| shipyard-cp | get_pipeline_stage, hold_for_review | read + controlled mutation |
| agent-gatefield | evaluate, enqueue_review, export_audit | read + append-only |

## Runtime / Deployment 要件

`agent-gatefield` の Judgment KB / state vector / gate decision store は PostgreSQL/pgvector を既定 runtime とする。Windows ネイティブ pgvector ビルドは標準導入経路でも本番稼働要件でもない。

| 環境 | 必須 runtime | 受入アウトカム | mock / in-memory |
|---|---|---|---|
| Local dev | Dockerized pgvector 推奨 | 開発者が Windows native build なしで evaluate / replay を確認できる | 契約検証と UI / adapter 開発のみ可 |
| CI | Dockerized pgvector または test container | schema migration、vector search、DecisionPacket ingestion、golden verdict が通る | DB 非依存 contract test のみ可 |
| Staging enforce | 実 PostgreSQL/pgvector backend | production 相当の latency、health check、failure_policy、replay を検証する | 障害注入以外不可 |
| Production shadow | 実 PostgreSQL/pgvector backend | mirror traffic で誤検知率、漏れ、queue backlog、audit completeness を測る | 不可 |
| Production enforce | HA / backup / retention 付き PostgreSQL/pgvector backend | high-risk action をブロックでき、復旧・監査・再現が可能 | 不可 |

Production Shadow / Production Enforce の entry criteria には、実 PostgreSQL/pgvector backend、schema migration、health check、backup、retention、failure_policy の検証完了を含める。本番で pgvector backend が利用不能な場合は `kb_unavailable` と `unavailable_axes` を audit packet に記録し、高リスク action は検出不能のまま `allow` せず `require_human` または `deny` に倒す。

## 正本境界

| オブジェクト | 生成者 | 正本保存先 |
|---|---|---|
| Task/Run/ContextBundle | agent-taskstate | agent-taskstate |
| DecisionPacket | agent-gatefield | agent-gatefield |
| Assessment | agent-state-gate | agent-state-gate |
| Evidence | workflow-cookbook | Evidence store |
| HumanQueueItem | agent-state-gate | agent-state-gate |

`agent-taskstate` は Assessment の linked ref と task/run/context bundle の参照先のみを持ち、Assessment 本体の保存先にはしない。

## 品質基準

| 指標 | 条件 |
|---|---|
| Unit test coverage | >= 80% |
| Ruff lint | 0 errors |
| CLI起動 | `agent-state-gate --help` 正常動作 |
| Docs complete | README参照ドキュメント全存在 |

更新日: 2026-04-26
