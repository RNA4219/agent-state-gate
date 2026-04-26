---
intent_id: INT-002
owner: agent-state-gate-team
status: active
last_reviewed_at: 2026-04-26
next_review_due: 2026-05-03
---

# Product Acceptance / Refactor Backlog

## 1. 目的

agent-state-gate を本番プロダクトとして検収する前に、仕様・実装・テスト・運用・Birdseye のズレを一箇所に集約する。ここでは「すぐ直す作業」だけでなく、Production Enforce へ進むために必要な設計固定、テスト証跡、運用証跡も扱う。

RUNBOOK は実行手順の正本であり、この台帳はその実行結果と是正事項の正本である。

## 2. 現時点の判定

| 判定 | 結果 |
|---|---|
| MVP Advisory | Conditional Go。主要 unit の大半は動くが MCP surface の契約ズレが残る |
| P0 Release | No-Go。`uv run pytest -q` が 6 件 fail |
| Production Shadow | No-Go。実 adapter / runtime / replay / observability 証跡が不足 |
| Production Enforce | No-Go。auth / tenant / retention / pgvector backend / fail-safe / audit replay が未検収 |

## 3. 検収証跡

2026-04-26 時点で `uv run pytest -q` を実行した結果は次の通り。

| 項目 | 結果 |
|---|---|
| collected | 269 |
| passed | 263 |
| failed | 6 |
| failure area | `tests/unit/test_mcp_surface.py` |

失敗概要:

- `gate_evaluate` の引数契約が test / docs と実装で不一致。
- `context_stale_check` の引数契約が test / docs と実装で不一致。
- `state_gate_assess` の引数契約が test / docs と実装で不一致。
- `attention_list` が queue mock の `list_items` ではなく `get_pending_items` 前提になっている。
- `HumanQueueItem` の dataclass が test / API 期待の `reason` を受け付けない。
- `run_replay_context` が NotImplemented ではなく placeholder を返し、MagicMock を hash して JSON serialize に失敗する。

## 4. Blocker / P0 リファクタ

| ID | 優先度 | 領域 | 問題 | 必要アウトカム | 受入条件 |
|---|---|---|---|---|---|
| REF-P0-001 | P0 | MCP surface | API spec / tests / 実装のメソッド引数が不一致 | MCP surface の公開契約を一つに固定 | `test_mcp_surface.py` の契約ズレ 3 件が解消 |
| REF-P0-002 | P0 | MCP surface | `gate.evaluate` が gatefield adapter 未接続でも advisory allow 相当に進み得る | adapter 不在時の failure_policy を明示し、P0 advisory と production readiness を分離 | gatefield 必須モードでは `AdapterUnavailableError`、advisory profile では degraded verdict |
| REF-P0-003 | P0 | MCP surface | `run.replay_context` が placeholder DecisionPacket を返し、replay 成果物と誤認される | replay 未実装 / advisory replay / production replay を別状態で返す | placeholder を production replay として扱わない test がある |
| REF-P0-004 | P0 | Human Queue | `HumanQueueItem` の API 期待と dataclass が不一致 | queue item schema を API / docs / tests で統一 | `reason` または `reason_code` の正規化ルールが固定 |
| REF-P0-005 | P0 | Queue API | `attention.list` が queue 実装と mock/test の `list_items` 契約に合っていない | queue repository interface を固定 | empty/list/filter の unit test が pass |
| REF-P0-006 | P0 | Assessment Store | Assessment 正本が in-memory のみ | P0 advisory でも永続化方式または明示的 ephemeral profile を固定 | process restart で失われる profile が本番不可として検出される |
| REF-P0-007 | P0 | CLI | `gate evaluate` が `mock_evaluation` を返すだけ | CLI から MCP surface / adapter profile を呼べる | `agent-state-gate gate evaluate --task --run --output json` が契約済み verdict を返す |
| REF-P0-008 | P0 | Tests | CHECKLISTS の Test Gate が `93 passed` の旧値 | 実テスト数に追随する検収表へ更新 | CHECKLISTS が 269 件基準または自動生成基準になる |
| REF-P0-009 | P0 | Artifact hygiene | `__pycache__` と `.coverage` が未追跡で混在 | 生成物を git 対象から除外 | `.gitignore` または cleanup 方針があり status が読みやすい |
| REF-P0-010 | P0 | Birdseye | 新規 Product Acceptance doc が Birdseye に未登録だと次回見落とす | Birdseye index / hot / caps から本台帳へ到達可能 | `missing_caps=[]`, `unknown_hot=[]`, `edge_unknown=[]` |

## 5. P1 / Production Shadow リファクタ

| ID | 優先度 | 領域 | 問題 | 必要アウトカム | 受入条件 |
|---|---|---|---|---|---|
| REF-P1-001 | P1 | Adapter integration | 各 adapter が実 repo API と完全には照合されていない | `actual_endpoint_or_function` 付き contract test を整備 | adapter ごとの golden fixture がある |
| REF-P1-002 | P1 | Gatefield integration | DecisionPacket schema の runtime validation が薄い | agent-gatefield DATA_TYPES_SPEC と変換 layer を固定 | schema mismatch で validation error |
| REF-P1-003 | P1 | Failure policy | adapter timeout / partial unavailable の統合挙動が scattered | failure_policy matrix を runtime に適用 | fail-open / fail-closed / needs_approval の fixture がある |
| REF-P1-004 | P1 | Replay | `replay reproducibility >= 99%` の測定器が未整備 | frozen snapshot と replay comparator を実装 | AC-009 が実測で判定可能 |
| REF-P1-005 | P1 | Audit | audit packet と Evidence chain の chain-of-custody が弱い | audit packet から DecisionPacket / Assessment / Evidence / approval を辿れる | audit packet sample が再現可能 |
| REF-P1-006 | P1 | Approval binding | diff/context hash と approval freshness の実装検収が不足 | approval invalidation を adapter / core / tests で固定 | diff_hash 変更で stale approval が無効化 |
| REF-P1-007 | P1 | Runtime profile | local / CI / staging / production の profile がコードで表現されていない | config に `runtime_profile` と禁止事項を持つ | production profile で mock / in-memory が起動不可 |
| REF-P1-008 | P1 | Observability | queue backlog、override rate、adapter health、runtime degraded が測れない | metrics / structured log / health endpoint を設計 | dashboard / log sample がある |
| REF-P1-009 | P1 | Security | auth / tenant / retention が production entry criteria のまま未実装 | Production Shadow 前に security boundary を固定 | auth、tenant、retention の minimum contract がある |
| REF-P1-010 | P1 | Docs | docs/requirements と deep-research-report の役割差がまだ読者依存 | deep research は検討ログ、requirements は正本と全入口で明記 | README / HUB / Birdseye / caps が同じ導線 |

## 6. P2 / 保守性リファクタ

| ID | 優先度 | 領域 | 問題 | 必要アウトカム |
|---|---|---|---|
| REF-P2-001 | P2 | Package layout | top-level package 名が `src` で、公開 package として分かりにくい | `agent_state_gate` package への移行検討 |
| REF-P2-002 | P2 | Type model | dataclass と dict が混在し schema drift が起きやすい | pydantic model または dataclass boundary を固定 |
| REF-P2-003 | P2 | Error model | adapter error と assessment error の外部 response mapping が弱い | MCP / CLI / internal error mapping を一本化 |
| REF-P2-004 | P2 | Config | `config/gate_config.yaml` と runtime 方針の接続が弱い | runtime profile と adapter enablement を config から生成 |
| REF-P2-005 | P2 | Docs freshness | Birdseye を手動更新しており、自動 freshness check がない | Birdseye validation script を追加 |
| REF-P2-006 | P2 | CLI UX | `gate`, `queue`, `audit` の subcommand と MCP tool 名が微妙にズレる | CLI 名と MCP tool 名の対応表を README / help に出す |
| REF-P2-007 | P2 | Test naming | AC と test module の対応が一部暗黙 | AC-ID と test-id の traceability を fixture で管理 |
| REF-P2-008 | P2 | Release evidence | CHANGELOG / CHECKLISTS / test result の紐付けが手動 | release evidence packet を生成 |

## 7. Product Acceptance Gate

### MVP Advisory Gate

| Check | 判定 |
|---|---|
| Unit tests all pass | No-Go |
| MCP surface contract stable | No-Go |
| docs complete | Conditional Go |
| Birdseye complete | Conditional Go |
| mock / in-memory is clearly non-production | Go |

### Production Shadow Gate

| Check | 判定 |
|---|---|
| Real gatefield DecisionPacket path | No-Go |
| Real adapter contract tests | No-Go |
| Replay comparator | No-Go |
| Audit chain completeness | No-Go |
| Runtime profile enforcement | No-Go |

### Production Enforce Gate

| Check | 判定 |
|---|---|
| PostgreSQL/pgvector production backend readiness | No-Go |
| auth / tenant / retention fixed | No-Go |
| high-risk fail-safe verified | No-Go |
| security review approved | No-Go |
| rollback and incident drill | No-Go |

## 8. 推奨実行順

1. REF-P0-001 から REF-P0-005 を直し、`uv run pytest -q` を全 pass にする。
2. REF-P0-006 / REF-P0-007 で P0 advisory と production readiness の境界を実装に入れる。
3. REF-P0-008 / REF-P0-009 / REF-P0-010 で検収表・生成物・Birdseye を整える。
4. REF-P1-001 から REF-P1-004 で adapter / DecisionPacket / replay を本番前提に寄せる。
5. REF-P1-007 / REF-P1-009 で Production Shadow の entry criteria を満たす。
6. RUNBOOK の runtime checklist を更新したら、この台帳の該当 REF を完了へ移す。

更新日: 2026-04-26
