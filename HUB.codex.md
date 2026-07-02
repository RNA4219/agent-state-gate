---
intent_id: INT-002
owner: agent-state-gate-team
status: active
last_reviewed_at: 2026-04-26
next_review_due: 2026-05-26
---

# agent-state-gate HUB

`HUB_SCOPE_DECLARATION`: 本ファイルは `agent-state-gate/` repo 内で作業するエージェント向けの入口である。

`agent-state-gate` は、既存 repo の判定・状態・文書鮮度・承認・証跡を束ね、最終 verdict と監査証跡を作る統合 gate 層。新しい State-space Gate 判定エンジンではない。

## 1. 最短理解

この repo が答える問い:

- この agent action を進めてよいか
- 人間の approval が必要か
- stale context や evidence 不足で止めるべきか
- 後で監査・再現できるだけの情報が残っているか

この repo が作るもの:

- `Assessment`
- `HumanQueueItem`
- `AuditPacket`
- MCP facade / CLI から返す統合 verdict

この repo が作らないもの:

- State-space score の再計算
- Task / Run / ContextBundle の正本
- Evidence store の正本
- Approval 契約の正本

## 2. 初動読み順

### 変更前に必ず読む

1. `AGENTS.md`
2. `README.md`
3. `GUARDRAILS.md`
4. `docs/requirements.md`

### 低コストに把握したいとき

1. `docs/birdseye/index.json`
2. `docs/birdseye/hot.json`
3. 変更対象に近い `docs/birdseye/caps/*.json`
4. 詳細が必要になったら正本 Markdown に戻る

### 実装領域別

| 触る場所 | 先に読む |
|---|---|
| `src/core/*` | `docs/requirements.md`, `docs/architecture.md`, `config/gate_config.yaml` |
| `src/adapters/*` | `docs/adapter_contract.md`, `GUARDRAILS.md` |
| `src/api/mcp_surface.py` | `docs/api_spec.md`, `GUARDRAILS.md` |
| `src/queue/*` | `docs/architecture.md`, `docs/requirements.md` |
| `src/audit/*` | `docs/requirements.md`, `docs/EVALUATION.md` |
| CLI / tests | `README.md`, `docs/RUNBOOK.md`, `CHANGELOG.md` |

## 3. 正本境界

| 対象 | 正本 | この repo の扱い |
|---|---|---|
| Task / Run / ContextBundle | `agent-taskstate` | 参照し、Assessment に link する |
| DecisionPacket | `agent-gatefield` | 受け取り、統合判断へ変換する |
| Evidence / Acceptance | `workflow-cookbook` | summary と evidence ref を扱う |
| Approval / Risk 契約 | `agent-protocols` | approval 要件を導出・検証する |
| Stage / publish hold | `shipyard-cp` | stage 取得と hold 接続を行う |
| Assessment / HumanQueueItem / AuditPacket | `agent-state-gate` | この repo の正本 |

## 4. 公開 surface

| Surface | 実体 | 用途 |
|---|---|---|
| CLI | `src/cli.py` | local debug、queue/audit/gate の手動確認 |
| MCP facade | `src/api/mcp_surface.py` | agent-context-mcp からの統合 gate 呼び出し |
| Core | `src/core/*` | Assessment assembly、verdict 変換、衝突解決 |
| Adapters | `src/adapters/*` | 外部 repo との契約境界 |
| Queue | `src/queue/human_attention_queue.py` | 人間レビュー待ちの管理 |
| Audit | `src/audit/*` | audit packet と evidence record |

MCP surface の公開 tool:

- `context.recall`
- `gate.evaluate`
- `context.stale_check`
- `state_gate.assess`
- `attention.list`
- `run.replay_context`

## 5. Verdict 変換の要点

入力側:

- `pass`
- `warn`
- `hold`
- `block`

出力側:

- `allow`
- `needs_approval`
- `stale_blocked`
- `deny`
- 内部判断として `require_human` / `revise` を扱う箇所がある

優先順位:

```text
critical static fail
> taboo block / secret / compliance block
> approval or stale hard block
> require_human
> revise
> warn
> pass
```

高リスク action で adapter / KB / approval / evidence が不明な場合、検出不能のまま `allow` にしない。

## 6. 現在の状態

v0.4.3 時点の実装状態:

- core engine 実装済み
- adapters 実装済み
- Human Attention Queue 実装済み
- Audit / Evidence recorder 実装済み
- MCP facade 実装済み
- CLI 実装済み
- unit tests / golden fixtures あり

重要な注意:

- adapter が実接続されていない場面では advisory mode の fallback がある。
- production blocking mode は、実 `agent-gatefield` DecisionPacket 連携、PostgreSQL/pgvector backend、migration、health check、backup、retention、failure_policy 検証後にのみ扱う。
- mock / in-memory は local / CI の contract test 用であり、本番代替ではない。

## 7. よくある作業と入口

| 依頼 | 入口 |
|---|---|
| README や説明をわかりやすくする | `README.md`, `AGENTS.md`, このファイル |
| verdict 変換を直す | `src/core/verdict_transformer.py`, `tests/unit/test_verdict_transformer.py` |
| Assessment を直す | `src/core/assessment_engine.py`, `tests/unit/test_assessment_engine.py` |
| adapter 契約を直す | `docs/adapter_contract.md`, `src/adapters/*`, `tests/unit/test_adapters.py` |
| MCP tool を直す | `docs/api_spec.md`, `src/api/mcp_surface.py`, `tests/unit/test_mcp_surface.py` |
| queue を直す | `src/queue/human_attention_queue.py`, `tests/unit/test_human_attention_queue.py` |
| audit / evidence を直す | `src/audit/*`, `tests/unit/test_audit_packet.py`, `tests/unit/test_evidence_recorder.py` |
| 検収やリリース判断 | `docs/EVALUATION.md`, `docs/CHECKLISTS.md`, `docs/PRODUCT_ACCEPTANCE_REFACTOR.md` |

## 8. 確認コマンド

標準:

```bash
uv run pytest
uv run ruff check .
uv run agent-state-gate --help
```

fallback:

```bash
pip install -e .
pytest tests/
agent-state-gate --help
```

## 9. 更新ルール

- README を変えたら `AGENTS.md` とこの HUB の導線が矛盾しないか確認する。
- 正本仕様を変えたら `docs/requirements.md` を先に更新し、関連する architecture / API / adapter docs を同期する。
- Birdseye を更新する場合は `docs/birdseye/index.json`、`docs/birdseye/hot.json`、該当 `caps/*.json` を一緒に整える。
- CHANGELOG は実装・検証の履歴として扱い、未来の計画表の代わりにしない。

## 10. 禁止事項

- `agent-gatefield` の score や state vector をこの repo で再計算する
- 他 repo の正本をこの repo に移して再定義する
- MCP から dangerous mutation を直接公開する
- 古い `diff_hash` / `context_hash` の approval を再利用する
- mock / in-memory を production enforce の代替にする
