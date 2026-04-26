# agent-state-gate

`agent-state-gate` は、エージェントの作業を「進めてよいか」「人間の確認が必要か」「止めるべきか」に変換する統合 gate 層です。

単体で新しい判定エンジンを作る repo ではありません。`agent-gatefield` の State-space Gate 判定、`agent-taskstate` の task/run/context、`memx-resolver` の stale 判定、`agent-protocols` の approval 契約、`workflow-cookbook` の Evidence を束ね、最終 verdict と監査証跡を作ります。

## 何に使うか

- エージェント作業の実行前に、必要な文書・承認・証跡が揃っているか確認する
- `pass / warn / hold / block` の判定を、運用で使える `allow / revise / needs_approval / require_human / stale_blocked / deny` に変換する
- 人間が見るべき例外だけを Human Attention Queue に積む
- approval を `diff_hash` と `context_hash` に束縛し、古い承認の再利用を防ぐ
- 後から再現できる audit packet と evidence summary を残す

## 位置づけ

| Repo | 役割 | agent-state-gate から見た扱い |
|---|---|---|
| `agent-gatefield` | State-space Gate 判定エンジン | DecisionPacket の正本 |
| `agent-taskstate` | Task / Run / ContextBundle | task state の正本 |
| `memx-resolver` | docs resolve / stale check | 文書鮮度の正本 |
| `agent-protocols` | approval / risk 契約 | 承認要件の正本 |
| `workflow-cookbook` | Evidence / Acceptance | 証跡の正本 |
| `shipyard-cp` | orchestration / publish gate | 実行段階と hold の接続先 |

この repo が持つ正本は `Assessment`、`HumanQueueItem`、`AuditPacket` です。

## 主要機能

- DecisionPacket ingestion
- Assessment assembly
- Verdict transformation
- Human Attention Queue
- Approval binding / freshness check
- Evidence summary
- Attested context snapshot
- Minimal replay
- Audit packet v0
- MCP surface facade

## MCP Surface

MCP facade は `src/api/mcp_surface.py` にあります。

| Tool | 用途 |
|---|---|
| `context.recall` | task/action 起点で必要文書と context bundle を解決する |
| `gate.evaluate` | 統合 gate を評価し、最終 verdict を返す |
| `context.stale_check` | stale 判定を実行する |
| `state_gate.assess` | State-space Gate 評価を統合層から呼ぶ |
| `attention.list` | Human Attention Queue を一覧する |
| `run.replay_context` | 過去 run の replay 用 context を扱う |

## いまの実装状態

v0.4.3 時点では、core / adapters / queue / audit / MCP facade / CLI の MVP 実装と unit tests が入っています。

注意点:

- `gate evaluate` は adapter 接続がない場合、advisory mode の結果を返します。
- production blocking mode には、実 `agent-gatefield` DecisionPacket 連携と PostgreSQL/pgvector backend の検証が必要です。
- mock / in-memory は contract test とローカル開発用です。本番代替にはしません。

## クイックスタート

```bash
pip install -e .
agent-state-gate --help
agent-state-gate gate evaluate --task TASK-1 --run RUN-1 --output json
pytest tests/
```

`uv` を使う場合:

```bash
uv run agent-state-gate --help
uv run pytest
uv run ruff check .
```

## ディレクトリ構成

```text
agent-state-gate/
├── src/
│   ├── core/       # Assessment engine, verdict transformer, conflict resolver
│   ├── adapters/   # 既存 repo との接続 adapter
│   ├── queue/      # Human Attention Queue
│   ├── audit/      # Audit packet と Evidence recorder
│   ├── api/        # MCP facade
│   └── common.py   # 共通 utility
├── config/         # gate 設定
├── docs/           # 仕様、運用、検収、Birdseye
├── tests/          # unit tests と golden fixtures
└── pyproject.toml
```

## 最初に読むもの

人間が概要を掴むなら、この順で読んでください。

1. `README.md`
2. `docs/requirements.md`
3. `docs/RUNBOOK.md`
4. `docs/EVALUATION.md`

エージェントが作業に入るなら、この順です。

1. `AGENTS.md`
2. `HUB.codex.md`
3. `docs/birdseye/index.json`
4. `docs/birdseye/hot.json`
5. 変更対象に近い `docs/birdseye/caps/*.json`

## 正本ドキュメント

- `docs/requirements.md`: 要件定義の正本
- `docs/architecture.md`: アーキテクチャ
- `docs/api_spec.md`: API 仕様
- `docs/adapter_contract.md`: adapter 契約
- `docs/RUNBOOK.md`: local / CI / staging / production 運用
- `docs/EVALUATION.md`: 受入基準
- `docs/PRODUCT_ACCEPTANCE_REFACTOR.md`: 検収・リファクタ台帳
- `GUARDRAILS.md`: 守るべき境界と禁止事項
- `HUB.codex.md`: エージェント向けナビゲーション

## 変更時の基本ルール

- `agent-gatefield` の score や state vector を再計算しない
- 他 repo の正本データをこの repo に移さない
- MCP surface から危険な mutation を直接公開しない
- approval は現在の `diff_hash` と `context_hash` にだけ有効とする
- production enforce では mock / in-memory を使わない

詳細は `GUARDRAILS.md` を参照してください。
