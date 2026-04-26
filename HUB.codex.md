---
intent_id: INT-002
owner: agent-state-gate-team
status: active
last_reviewed_at: 2026-04-26
next_review_due: 2026-05-26
---

# agent-state-gate HUB

リポジトリ内の仕様・運用MDを集約し、エージェントがタスクを自動分割できるようにするハブ定義。

## 1. 目的

- リポジトリ配下の計画資料から作業ユニットを抽出し、優先度順に配列
- 生成されたタスクリストを Task Seed へマッピング
- ドキュメント間の依存関係を明確化

## 2. 入力ファイル分類

| ファイル | 役割 | 優先度 |
|---------|------|-------|
| `BLUEPRINT.md` | 要件・制約・背景 | 高 |
| `GUARDRAILS.md` | ガードレール/行動指針 | 高 |
| `docs/RUNBOOK.md` | 開発フロー・手順 | 中 |
| `docs/EVALUATION.md` | 受け入れ基準・品質指標 | 中 |
| `docs/CHECKLISTS.md` | リリース/レビュー確認項目 | 低 |
| `docs/requirements.md` | 要件定義正本 | 高 |
| `docs/architecture.md` | アーキテクチャ設計 | 高 |
| `docs/api_spec.md` | API仕様 | 高 |
| `docs/adapter_contract.md` | Adapter契約 | 高 |

補完資料:

- `README.md`: リポジトリ概要と参照リンク
- `CHANGELOG.md`: 完了タスクと履歴の記録

更新日: 2026-04-26

## 3. ドキュメント依存関係

```
BLUEPRINT.md (要件)
    │
    ├──→ docs/requirements.md (詳細要件)
    │        │
    │        ├──→ docs/architecture.md (アーキテクチャ)
    │        │
    │        ├──→ docs/api_spec.md (API仕様)
    │        │
    │        └──→ docs/adapter_contract.md (Adapter契約)
    │
    ├──→ docs/EVALUATION.md (受入基準)
    │
    └──→ docs/RUNBOOK.md (開発フロー)
             │
             └──→ docs/CHECKLISTS.md (チェックリスト)

GUARDRAILS.md (行動指針)
    │
    └──→ 全ドキュメントに適用
```

## 4. タスク分割フロー

1. **スキャン**: ルートと `docs/` 配下を再帰探索
2. **優先度抽出**: Front matter の `priority`, `status` を確認
3. **依存解決**: ドキュメント間の参照関係を解析
4. **粒度調整**: 作業ユニットを `<= 0.5d` 目安に分割
5. **テンプレート投影**: `TASK.codex.md` 形式へ変換
6. **出力整形**: 優先度・依存順にソート

## 5. Task Status & Blockers

```yaml
許容ステータス:
  - [] or [ ]: 未着手・未割り振り
  - planned: バックログ
  - active: 優先キュー入り（担当/期日付き）
  - in_progress: 着手中
  - reviewing: レビュー待ち
  - blocked: ブロック中
  - done: 完了

標準遷移:
  planned → active → in_progress → reviewing → done

例外遷移:
  in_progress → blocked → in_progress
```

## 6. 実装ロードマップと工数見積

### Phase 1: プロジェクト初期化 ✅ DONE

| Task | Estimate | Status |
|---|---:|---|
| プロジェクト構造作成 | 0.5d | done |
| README.md, BLUEPRINT.md, HUB.codex.md 作成 | 0.5d | done |
| docs/architecture.md 作成 | 1d | done |
| docs/api_spec.md 作成 | 1d | done |
| docs/adapter_contract.md 作成 | 1d | done |
| config/gate_config.yaml 作成 | 0.5d | done |
| pyproject.toml 作成 | 0.25d | done |
| **Phase 1 Total** | **4.25d** | **done** |

### Phase 2: Adapter実装

| Adapter | Estimate | Key Tasks | Dependencies |
|---|---:|---|---|
| gatefield_adapter | 2d | DecisionPacket接続、evaluate(), enqueue_review() | agent-gatefield DATA_TYPES_SPEC |
| taskstate_adapter | 2d | Task/Run/ContextBundle接続、typed_ref正規化 | agent-taskstate typed_ref.py |
| protocols_adapter | 1.5d | risk derivation, approval derivation | agent-protocols schemas |
| memx_adapter | 1.5d | docs resolve, stale_check, ack | memx-resolver interfaces |
| shipyard_adapter | 1d | stage取得, hold_for_review() | shipyard-cp api-contract |
| workflow_adapter | 1d | evidence_report, acceptance_index | workflow-cookbook generate_evidence_report.py |
| AdapterRegistry | 0.5d | register, health_check_all | 全Adapter |
| **Phase 2 Total** | **8d** | | |

### Phase 3: Core Engine実装

| Component | Estimate | Key Tasks | Dependencies |
|---|---:|---|---|
| assessment_engine | 2d | Assessment assembly, causal_trace生成 | DecisionPacket + 全Adapter |
| verdict_transformer | 1.5d | 9条件変換ロジック, threshold適用 | BLUEPRINT Verdict変換規則 |
| conflict_resolver | 1d | authority_hierarchy適用, 衝突解決 | gate_config.yaml authority |
| typed_ref_domain_ext | 0.5d | KNOWN_DOMAINS拡張 | agent-taskstate typed_ref.py |
| **Phase 3 Total** | **5d** | | |

### Phase 4: Human Attention Queue

| Component | Estimate | Key Tasks | Dependencies |
|---|---:|---|---|
| human_attention_queue | 2d | enqueue, take, resolve, escalate | architecture.md HumanQueueItem |
| sla_enforcement | 1d | SLA期限監視, auto_block, escalation | architecture.md SLA Enforcement |
| waiver_process | 1d | waiver申請/審査/無効化フロー | gate_config.yaml waiver |
| reviewer_routing | 0.5d | required_role → reviewer mapping | gate_config.yaml reviewer_roles |
| **Phase 4 Total** | **4.5d** | | |

### Phase 5: Audit & Evidence

| Component | Estimate | Key Tasks | Dependencies |
|---|---:|---|---|
| audit_packet_generator | 1.5d | AuditPacket生成, JSONL/OTLP export | architecture.md AuditPacket |
| evidence_recorder | 1d | evidence.record, attested snapshot | workflow-cookbook evidence_bridge |
| replay_engine | 1d | run.replay_context, decision_diff | agent-taskstate export |
| retention_policy | 0.5d | retention_class適用, expires_at計算 | gate_config.yaml audit.retention |
| **Phase 5 Total** | **4d** | | |

### Phase 6: MCP Surface API

| API | Estimate | Key Tasks | Dependencies |
|---|---:|---|---|
| context.recall | 1d | memx + taskstate routing, RecallResult | Phase 2 adapters |
| gate.evaluate | 1.5d | 全adapter統合, EvaluateResult | Phase 3 assessment_engine |
| context.stale_check | 0.5d | memx stale_check routing | memx_adapter |
| state_gate.assess | 1d | gatefield + assessment routing | gatefield_adapter + assessment_engine |
| attention.list | 0.5d | Human Queue routing | Phase 4 human_attention_queue |
| run.replay_context | 0.5d | audit + taskstate routing | Phase 5 replay_engine |
| MCP Error handling | 0.5d | error types, HTTP equivalent mapping | api_spec.md Error Types |
| **Phase 6 Total** | **5.5d** | | |

### 総工数見積

| Phase | Estimate | Buffer (20%) | Total |
|---|---:|---:|---:|
| Phase 1 | 4.25d | done | done |
| Phase 2 | 8d | 1.6d | 9.6d |
| Phase 3 | 5d | 1d | 6d |
| Phase 4 | 4.5d | 0.9d | 5.4d |
| Phase 5 | 4d | 0.8d | 4.8d |
| Phase 6 | 5.5d | 1.1d | 6.6d |
| **MVP Total** | **32d** | **6.4d** | **38.4d** (~8 weeks) |

---

## 7. 現在のタスク状態

### 完了 (Phase 1)

- [x] プロジェクト構造作成
- [x] README.md, BLUEPRINT.md, HUB.codex.md 作成
- [x] docs/architecture.md 作成 (Gap解消含む)
- [x] docs/api_spec.md 作成
- [x] docs/adapter_contract.md 作成 (Gap解消含む)
- [x] config/gate_config.yaml 作成 (Waiverプロセス追加)
- [x] pyproject.toml 作成
- [x] 仕様書完成度検収 PASS (90/100)
- [x] GAP-001: typed_ref実装状況確認 ✅ agent-taskstate実装済み
- [x] GAP-002: CausalStep contribution_weight計算ロジック追加
- [x] GAP-003: Risk derivation閾値定義追加
- [x] GAP-006: Waiver審査プロセス追加

### 未着手 (Phase 2-6)

- [ ] Phase 2: Adapter実装 (9.6d)
- [ ] Phase 3: Core Engine実装 (6d)
- [ ] Phase 4: Human Attention Queue (5.4d)
- [ ] Phase 5: Audit & Evidence (4.8d)
- [ ] Phase 6: MCP Surface API (6.6d)

## 7. 出力例（Task Seed）

```yaml
- task_id: 20260426-01
  source: docs/architecture.md#Phase1
  objective: gatefield_adapter 実装
  scope:
    in: [src/adapters/gatefield_adapter.py]
    out: [src/core/assessment_engine.py]
  requirements:
    behavior:
      - DecisionPacket ingestion
      - evaluate() 接続
    constraints:
      - BLUEPRINT 4.3準拠
  commands:
    - pytest tests/adapters/test_gatefield_adapter.py -v
  dependencies: []
```