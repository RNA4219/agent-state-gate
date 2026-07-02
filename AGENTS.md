# AGENTS.md

この repo では日本語で記載する。

## まず読む

1. `README.md`
2. `HUB.codex.md`
3. `GUARDRAILS.md`
4. `docs/requirements.md`
5. 変更対象に近い `docs/birdseye/caps/*.json`

仕様や運用判断で迷ったら、`docs/requirements.md` を正本として扱う。作業導線や読む順番で迷ったら `HUB.codex.md` を使う。

## この repo の役割

`agent-state-gate` は統合 gate 層であり、判定エンジン本体ではない。

- `agent-gatefield` の DecisionPacket を受け取る
- stale / obligation / approval / evidence を束ねて Assessment を作る
- verdict を `allow / needs_approval / stale_blocked / deny` へ変換する
- Human Attention Queue と AuditPacket を管理する

## 正本境界

| 対象 | 正本 |
|---|---|
| Task / Run / ContextBundle | `agent-taskstate` |
| DecisionPacket | `agent-gatefield` |
| Evidence / Acceptance | `workflow-cookbook` |
| Approval / Risk 契約 | `agent-protocols` |
| Assessment / HumanQueueItem / AuditPacket | `agent-state-gate` |

他 repo の正本をこの repo に複製して再定義しない。

## 実装時の注意

- `agent-gatefield` の score、state vector、threshold 判定を再実装しない。
- adapter は既存 repo の契約に合わせる。仮実装や mock を本番経路として扱わない。
- high-risk action で外部 dependency が unavailable の場合、検出不能のまま `allow` に倒さない。
- approval / waiver は現在の `diff_hash` と `context_hash` に束縛する。
- dangerous mutation は MCP surface に直接出さない。
- mock / in-memory は local / contract test 用。本番代替にしない。

## よく触る場所

- `src/core/assessment_engine.py`: Assessment の組み立て
- `src/core/verdict_transformer.py`: verdict 変換
- `src/core/conflict_resolver.py`: 衝突解決
- `src/adapters/`: 外部 repo との接続
- `src/queue/human_attention_queue.py`: Human Attention Queue
- `src/audit/`: AuditPacket と Evidence recorder
- `src/api/mcp_surface.py`: MCP facade
- `src/cli.py`: CLI

## 確認コマンド

```bash
uv run pytest
uv run ruff check .
uv run agent-state-gate --help
```

`uv` が使えない環境では、editable install 後に `pytest` を実行する。

```bash
pip install -e .
pytest tests/
```

## ドキュメント更新

README を更新したら、必要に応じて以下も同期する。

- `HUB.codex.md`
- `docs/birdseye/index.json`
- `docs/birdseye/hot.json`
- 変更対象の `docs/birdseye/caps/*.json`

Birdseye JSON が古い場合は、少なくとも `last_verified_at` と該当 capsule の要約が README / HUB の内容と矛盾しないようにする。
