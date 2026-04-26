# CHANGELOG

All notable changes to agent-state-gate will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

### Added - 実装検収準備完了

- **adapter_contract.md 実API照合表** (Section 10-11)
  - GatefieldAdapter: evaluate, enqueue_review, export_audit API mapping
  - TaskstateAdapter: get_task, get_context_bundle, record_read_receipt API mapping
  - ProtocolsAdapter: derive_risk_level, derive_required_approvals API mapping
  - MemxAdapter: resolve_docs, stale_check, resolve_contract API mapping
  - ShipyardAdapter: get_pipeline_stage, hold_for_review API mapping
  - WorkflowAdapter: get_birdseye_caps, get_acceptance_index, get_evidence_report API mapping
  - Error Type Mapping table追加

- **Golden Fixtures AC-001 through AC-009**
  - tests/fixtures/golden/AC-001_decision_packet_ingestion.json
  - tests/fixtures/golden/AC-002_assessment_assembly.json
  - tests/fixtures/golden/AC-003_verdict_transformation.json (9 verdict cases)
  - tests/fixtures/golden/AC-004_human_queue_routing.json (4 routing cases)
  - tests/fixtures/golden/AC-005_sla_enforcement.json (4 SLA cases)
  - tests/fixtures/golden/AC-006_typed_ref_canonical.json (8 format cases)
  - tests/fixtures/golden/AC-007_waiver_process.json (3-step flow + invalidation)
  - tests/fixtures/golden/AC-008_audit_packet.json (AuditPacket structure)
  - tests/fixtures/golden/AC-009_replay_reproducibility.json (Replay >= 99%)

### Verified

- **Complete Go** ✅ 実装検収準備完了
- adapter_contract.md 実API照合表完了
- golden fixture 9件作成完了
- 仕様書→実装のtraceability確保

## [0.2.0] - 2026-04-26

### Fixed - Conditional Go → Complete Go

**[P1] Assessment正本境界固定**:
- architecture.md: 正本境界定義 section追加
- **決定**: Assessment正本は **agent-state-gate Assessment Store**、agent-taskstateはlinked refのみ
- 責任境界理由: Replay再現性、Audit完全性、MCP参照効率、Shipyard連携
- 禁止パターン3項目追加 (正本重複、DecisionPacket混在、cross-repo fetch)

**[P1] Verdict変換分岐条件固定**:
- BLUEPRINT.md: Verdict変換規則分岐条件詳細追加
- **決定**: evidence不足 → needs_approval確定、obligation不足 → severity分岐、判断欠落 → require_human
- resolve_verdict関数5段priorityフロー追加
- Decision Table 12行追加 (全条件組み合わせ)

**[P2] Production Enforce Entry Criteria明記**:
- BLUEPRINT.md: Release Stage定義追加 (MVP advisory → P1 shadow → Production blocking)
- **決定**: Production Enforceにはauth基盤/tenant境界/retention policy決定済み必須
- 未指定事項の後段選定時期明記 (P0/P1完了後)
- **重要**: blocking stage移行前に運用安全性判定全criteria満たす必要

### Verified

- Conditional Go → **Complete Go** ✅
- 3つの懸念点全解消完了
- 実装前のoracle割れ回避確認

## [0.1.3] - 2026-04-26

### Added - 残り5点埋め (Rubric Full Score達成)

- **Ownership Context定義** (+2点)
  - architecture.md: HumanQueueItemにtask_owner, task_owner_type, ownership_context追加
  - OwnershipContext dataclass定義
  - Ownership Check Rules 4条件追加

- **Invalid Transition Detection定義** (+2点)
  - architecture.md: State Transition Validation section追加
  - VALID/INVALID_TRANSITIONS for Task, HumanQueue, Assessment
  - detect_invalid_transition関数、InvalidTransitionError定義
  - Invalid Transition Handling table

- **Waiver審査SLA定義** (+1点)
  - gate_config.yaml: waiver.sla追加 (review_ack_hours, decision_hours等)

- **Oracle Reference Matrix**
  - EVALUATION.md: 検証テスト仕様 section追加
  - Oracle Ref, Observable Expected, Trace To table 9項目
  - EXPECTED_AC001, EXPECTED_AC002, EXPECTED_AC003 concrete definitions
  - Trace Reference Chain diagram

### Verified

- Rubric Score: **100 / 100** ✅ Full Score達成
- Automatic Fail Conditions全項目PASS

## [0.1.2] - 2026-04-26

### Added - 仕様補完推奨事項解消

- **GAP-001: typed_ref実装状況確認**
  - adapter_contract.md: agent-taskstate `src/typed_ref.py` 実装確認
  - KNOWN_DOMAINS拡張方法追加 (agent-gatefield, shipyard-cp)

- **GAP-002: CausalStep contribution_weight計算ロジック**
  - architecture.md: SOURCE_BASE_WEIGHTS, VERDICT_IMPACT, RULE_SEVERITY_MODIFIER定義
  - calculate_contribution_weight関数、正規化ロジック追加
  - Example trace table追加

- **GAP-003: Risk derivation閾値定義**
  - architecture.md: DATA_TYPES_SPEC CalibrationProfile thresholds準拠
  - 12 threshold values (taboo_warn=0.80, taboo_block=0.88, etc.)
  - Hard Override Rules 3項目定義
  - calculate_risk_score関数追加

- **GAP-004: 実装工数見積**
  - HUB.codex.md: Phase 1-6 詳細工数見積追加
  - 各Adapter/Component工数、Buffer 20%、Total 38.4d (~8 weeks)
  - MVP Total 32d + 6.4d buffer

- **GAP-005: 探索テストtimebox**
  - docs/EVALUATION.md: 探索テストチャーター9項目定義
  - 各charterにtimebox指定 (1h-2h)、総Timebox 12h (1.5d)
  - State Gate, Human Queue, Adapter Integration探索領域

- **GAP-006: Waiver審査プロセス**
  - config/gate_config.yaml: waiver request_flow 3-step定義
  - waiver types 4種類 (policy_override, stale_approval_usage, evidence_missing_accept, gate_bypass)
  - invalidation条件4項目、audit設定追加

### Created

- docs/EVALUATION.md: 受入基準、探索テスト、品質指標、Gate判定基準

### Verified

- 仕様書完成度再検収: **PASS (95/100)** - 全GAP解消完了

## [0.1.1] - 2026-04-26

### Fixed
- **Gap 1: typed_ref format不一致解消**
  - adapter_contract.md: 4セグメントcanonical format `<domain>:<entity_type>:<provider>:<entity_id>` 採用
  - memx-resolver interfaces.md準拠、3セグメント入力の互換layer参照追加
  
- **Gap 2: DecisionPacket schema詳細化**
  - adapter_contract.md: DATA_TYPES_SPEC v1.0.0完全版に準拠したschema定義
  - Required/Optional fields、ScoreFactor/ExemplarRef/ActionRecommendation structure追加
  - agent-gatefield DATA_TYPES_SPEC lines 779-1141参照
  
- **Gap 3: EvidenceReport schema整合**
  - adapter_contract.md: workflow-cookbook generate_evidence_report.py実装準拠
  - EvidenceReport, AcceptanceSummary, EvidenceSummary structure追加

### Added
- architecture.md: Assessment詳細型定義追加
  - CausalStep, Counterfactual, StaleSummary, ObligationSummary, ApprovalSummary, EvidenceSummary
- architecture.md: SLA Enforcement Logic追加
  - enforce_sla関数、SLAAction enum、escalation chain logic

## [0.1.0] - 2026-04-26

### Added
- Initial project structure
- README.md with project overview
- BLUEPRINT.md with requirements and design constraints
- HUB.codex.md for task management
- GUARDRAILS.md with behavioral guidelines
- docs/architecture.md with layer and data flow design
- docs/api_spec.md with MCP surface API specification
- docs/adapter_contract.md with adapter interface contracts
- config/gate_config.yaml template
- pyproject.toml with dependencies
- Python package structure (src/core, src/adapters, src/queue, src/audit, src/api)

### Documentation
- Requirements document from deep-research-report (9).md
- Verdict transformation rules
- Adapter failure policies
- Human Attention Queue SLA definitions

### Next Steps
- Phase 2: Adapter implementations
- Phase 3: Core Engine implementations
- Phase 4: Human Attention Queue
- Phase 5: Audit & Evidence
- Phase 6: MCP Surface