# Birdseye データセット運用ガイド

Birdseye は、agent-state-gate の仕様・運用・検収ドキュメントを軽量に読むための知識マップです。`index.json`、`hot.json`、`caps/*.json` を第一読者とし、`docs/BIRDSEYE.md` は JSON が読めない場合の人間向けフォールバックとして扱います。

## ディレクトリ構成

- `index.json`: ノード一覧、役割、caps 参照、主要 edges。
- `hot.json`: 初動で読むべき主要ノードのホットリスト。
- `caps/*.json`: 各ノードの要約、依存、リスク、検証観点。
- `README.md`: Birdseye 更新・利用手順。
- `../BIRDSEYE.md`: 人間向けフォールバック。

## 読込順序

1. `docs/birdseye/index.json`
2. `docs/birdseye/hot.json`
3. 必要な `docs/birdseye/caps/*.json`
4. JSON が読めない場合のみ `docs/BIRDSEYE.md`

## 更新方針

- 正本情報は `docs/requirements.md`、`BLUEPRINT.md`、`docs/RUNBOOK.md`、`docs/EVALUATION.md`、`docs/CHECKLISTS.md` に置く。
- Birdseye は正本の複製ではなく、入口・依存・要約を持つ。
- pgvector runtime 方針や Production Enforce 条件を更新した場合は、`docs/requirements.md`、`docs/RUNBOOK.md`、`docs/EVALUATION.md`、`docs/CHECKLISTS.md`、`docs/PRODUCT_ACCEPTANCE_REFACTOR.md` の caps を更新する。
- `generated_at` は 5 桁ゼロ埋めの世代番号として扱う。

更新日: 2026-04-26
