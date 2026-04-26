# agent-state-gate

工程統治統合層 - Context Graph拡張とState-space Gate統合ハーネス

## 概要

本プロジェクトは既存6資産を横断する統合工程統治層として実装：

- `workflow-cookbook`: Birdseye/Codemap、Acceptance、Evidence
- `memx-resolver`: docs resolve、stale、contract
- `agent-taskstate`: task/state/decision/context_bundle/run
- `agent-protocols`: 契約、approval rules
- `shipyard-cp`: orchestration、publish gate
- `agent-gatefield`: State-space Gate判定エンジン

## 主責務

1. DecisionPacket ingestion: `agent-gatefield` の判定結果を受け取る
2. Assessment assembly: 判定 + obligation + stale + approval + evidence を束ねる
3. Verdict transformation: pass/warn/hold/block → allow/needs_approval/stale_blocked/deny
4. Human Attention Queue: 人間レビューキューの管理
5. Approval binding/freshness: diff/context hash による承認束縛
6. Evidence summary: 証跡の集約と参照

## MCP Surface (agent-context-mcp)

本プロジェクト内の `src/api/mcp_surface.py` として実装：

- `context.recall`: task/action起点の文書解決
- `gate.evaluate`: 統合gate評価
- `context.stale_check`: stale判定
- `state_gate.assess`: State-space gate評価
- `attention.list`: Human Attention Queue一覧

## 構成

```
agent-state-gate/
├── src/
│   ├── core/           # Assessment engine, verdict transformer
│   ├── adapters/       # 既存資産接続adapter
│   ├── queue/          # Human Attention Queue
│   ├── audit/          # Audit packet生成
│   ├── api/            # MCP façade
│   └── config/         # 設定ファイル
├── docs/               # 設計ドキュメント
├── tests/              # テストスイート
└── pyproject.toml
```

## 参照ドキュメント

- `docs/requirements.md` - 要件定義書（詳細）
- `docs/architecture.md` - アーキテクチャ設計
- `docs/api_spec.md` - API仕様
- `docs/adapter_contract.md` - Adapter契約

## MVP (P0) スコープ

1. DecisionPacket ingestion
2. Assessment assembly
3. Verdict transformation
4. Human Attention Queue
5. Approval binding/freshness
6. Evidence.record
7. Attested context snapshot
8. Minimal replay
9. Audit packet v0

## 開発開始

```bash
pip install -e .
pytest tests/
```

## 関連リポジトリ

- [agent-gatefield](../agent-gatefield) - State-space Gate判定エンジン
- [agent-taskstate](../agent-taskstate) - 状態正本化
- [agent-protocols](../agent-protocols) - 契約システム
- [shipyard-cp](../shipyard-cp) - Orchestration制御面
- [memx-resolver](../memx-resolver) - 文書resolver
- [workflow-cookbook](../workflow-cookbook) - Evidence/Acceptance

## Source of Truth

[docs/requirements.md](docs/requirements.md) が正本仕様。