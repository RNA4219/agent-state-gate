---
intent_id: INT-002
owner: agent-state-gate-team
status: active
last_reviewed_at: 2026-04-26
next_review_due: 2026-05-26
---

# agent-state-gate RUNBOOK

## 1. 目的

agent-state-gate を local / CI / staging / production で運用するための手順をまとめる。詳細仕様の正本は `docs/requirements.md`、設計制約は `BLUEPRINT.md`、検収結果とリファクタ台帳は `docs/PRODUCT_ACCEPTANCE_REFACTOR.md`、リリース確認は `docs/CHECKLISTS.md` を参照する。

## 2. ランタイム方針

Windows ネイティブ pgvector ビルドは標準サポートパスにしない。開発者端末では Dockerized pgvector または mock / in-memory を使い、本番では実 PostgreSQL/pgvector backend を使う。

| 環境 | runtime | 用途 |
|---|---|---|
| Local dev | Dockerized pgvector 推奨、mock / in-memory 可 | evaluate / replay の手元確認、adapter 契約開発 |
| CI | Dockerized pgvector または test container | schema migration、vector search、golden verdict 検証 |
| Staging enforce | 実 PostgreSQL/pgvector backend | 本番相当 latency、health check、failure_policy 検証 |
| Production shadow | 実 PostgreSQL/pgvector backend | mirror traffic で誤検知率、漏れ、queue backlog を測定 |
| Production enforce | HA / backup / retention 付き PostgreSQL/pgvector backend | high-risk action の blocking、監査、復旧 |

mock / in-memory は本番代替ではない。Production Shadow / Production Enforce では使用不可とする。

## 3. Local Dev 手順

1. 依存関係を入れる。

```bash
pip install -e .
```

2. Dockerized pgvector を使う場合は、`agent-gatefield` 側の Docker Compose を起動する。

```bash
cd ../agent-gatefield
docker compose up -d postgres
```

3. agent-state-gate のテストを実行する。

```bash
cd ../agent-state-gate
pytest tests/
```

4. Docker が使えない端末では mock / in-memory profile で contract test と UI / adapter 開発だけを行う。本番相当の gate 品質判定や Production Enforce 判定には使わない。

## 4. CI 手順

CI は次を必須にする。

| Check | 必須 |
|---|---|
| Unit tests | Yes |
| Adapter contract tests | Yes |
| Dockerized pgvector または test container | Yes for DB integration |
| Golden verdict replay | Yes |
| docs reference validation | Yes |

mock / in-memory のみで CI を通す場合は、DB 非依存 contract test として扱い、Production runtime readiness は未達にする。

## 5. Staging / Production 手順

Production Shadow / Production Enforce に進む前に次を確認する。

| 項目 | 判定 |
|---|---|
| PostgreSQL/pgvector backend | 接続、extension、schema、index が health check 済み |
| Migration | schema migration が適用済みで rollback 手順がある |
| Backup / retention | backup、retention、purge が設定済み |
| Failure policy | KB unavailable、adapter timeout、partial unavailable の挙動が確認済み |
| Replay | golden fixture と shadow traffic で verdict 再現性を確認済み |
| Security | auth、tenant、retention、secret handling が承認済み |

検収時は `docs/PRODUCT_ACCEPTANCE_REFACTOR.md` の `REF-P0-*` と `REF-P1-*` を順に潰し、`docs/CHECKLISTS.md` の Production runtime / KB unavailable policy と整合していることを確認する。

## 6. pgvector 障害時の挙動

本番で pgvector backend が利用不能な場合、semantic similarity 系 signal は degraded として記録する。Production Enforce では検出不能なまま `allow` しない。

| 状況 | 挙動 |
|---|---|
| low-risk action かつ hard rule 充足 | degraded warn を付与して継続可 |
| high-risk action | `require_human` |
| publish / destructive action | `deny` または shipyard-cp hold |
| audit | `kb_unavailable`, `unavailable_axes`, failure_policy を記録 |

## 7. Rollback

1. Production Enforce を停止し、Production Shadow または advisory に戻す。
2. 直近の policy / adapter / schema change を audit packet と changelog で特定する。
3. golden fixture replay を実行し、verdict 差分を確認する。
4. PostgreSQL/pgvector の schema migration が原因の場合は、事前定義された rollback 手順で戻す。
5. 復旧後も 24 時間は Production Shadow で観測する。

## 8. Incident Triage

| 事象 | 初動 |
|---|---|
| 誤 block 増加 | Production Enforce を Shadow に戻し、false positive と threshold_version を確認 |
| 漏れ疑い | 対象 run の Assessment、DecisionPacket、audit packet、context hash を収集 |
| KB unavailable | pgvector health check、connection pool、index、replication lag を確認 |
| queue backlog | reviewer routing、SLA、required_role の偏りを確認 |

## 9. 検収連携

1. 変更を加えたら `docs/PRODUCT_ACCEPTANCE_REFACTOR.md` に検収結果を追記する。
2. P0 は `REF-P0-001` から `REF-P0-010` の順で潰す。
3. P1 は `REF-P1-001` から `REF-P1-010` を Production Shadow 準備として扱う。
4. `docs/CHECKLISTS.md` の Production runtime 行が `No-Go` なら Production Enforce へ進めない。
5. `docs/requirements.md` の Runtime / Deployment 要件を変えたら RUNBOOK と台帳の両方を更新する。

更新日: 2026-04-26
