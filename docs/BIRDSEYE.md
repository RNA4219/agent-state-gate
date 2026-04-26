---
intent_id: INT-002
owner: agent-state-gate-team
status: active
last_reviewed_at: 2026-04-26
next_review_due: 2026-05-26
---

# agent-state-gate Birdseye

Birdseye は、agent-state-gate の仕様・運用・検収ドキュメントを軽量に読むための知識マップです。最新状態は `docs/birdseye/index.json`、`docs/birdseye/hot.json`、`docs/birdseye/caps/*.json` を第一読者とし、このファイルは JSON が読めない場合のフォールバックです。

## Hot List

- `README.md`: repo の目的、責務、runtime 方針、参照ドキュメント。
- `HUB.codex.md`: ドキュメント依存、実装フェーズ、タスク分割。
- `docs/requirements.md`: P0 機能、Runtime / Deployment 要件、正本境界。
- `BLUEPRINT.md`: 責務境界、Release Stage、Production Enforce entry criteria、verdict 変換。
- `docs/RUNBOOK.md`: local / CI / staging / production の運用手順、pgvector 障害時挙動。
- `GUARDRAILS.md`: 二重実装禁止、Runtime 境界、MCP surface 制限。
- `docs/adapter_contract.md`: 既存 OSS adapter の接続・failure_policy・実 API 照合。
- `docs/EVALUATION.md`: Runtime portability と Production runtime readiness を含む受入基準。
- `docs/CHECKLISTS.md`: リリース前確認と Production Enforce チェック。
- `docs/PRODUCT_ACCEPTANCE_REFACTOR.md`: プロダクト検収結果、No-Go 理由、リファクタ台帳。

## 主要 Edges

- `README.md` → `HUB.codex.md`, `BLUEPRINT.md`, `docs/requirements.md`, `docs/RUNBOOK.md`, `docs/EVALUATION.md`
- `HUB.codex.md` → `BLUEPRINT.md`, `GUARDRAILS.md`, `docs/requirements.md`, `docs/RUNBOOK.md`, `docs/CHECKLISTS.md`
- `docs/requirements.md` → `docs/architecture.md`, `docs/api_spec.md`, `docs/adapter_contract.md`, `docs/RUNBOOK.md`
- `BLUEPRINT.md` → `docs/requirements.md`, `docs/EVALUATION.md`, `docs/CHECKLISTS.md`
- `docs/RUNBOOK.md` → `docs/requirements.md`, `docs/CHECKLISTS.md`
- `docs/EVALUATION.md` → `docs/CHECKLISTS.md`
- `docs/PRODUCT_ACCEPTANCE_REFACTOR.md` → `docs/EVALUATION.md`, `docs/CHECKLISTS.md`, `docs/RUNBOOK.md`
- `deep-research-report (9).md` → `docs/requirements.md`

## Runtime 要点

- Local / CI は Dockerized pgvector を標準経路、mock / in-memory を contract 検収経路にできる。
- Production Shadow / Production Enforce は実 PostgreSQL/pgvector backend、schema migration、health check、backup、retention、failure_policy を必須にする。
- Windows ネイティブ pgvector ビルドは標準導入経路でも本番稼働要件でもない。
- Production Enforce では KB unavailable のまま high-risk action を `allow` しない。

## 更新手順

1. 正本ドキュメントを更新する。
2. 変更対象の caps を更新する。
3. `docs/birdseye/index.json` と `docs/birdseye/hot.json` の node / edge / generated_at を同期する。
4. `docs/BIRDSEYE.md` の Hot List と Runtime 要点が JSON と矛盾しないことを確認する。

更新日: 2026-04-26
