---
intent_id: DOC-LEGACY
owner: infrastructure
status: active
last_reviewed_at: 2026-05-02
next_review_due: 2026-06-02
---

# Technical Debt Register

code-to-gate 分析で検出された技術的債務の記録と対応計画。

## 検出日: 2026-05-02

## 1. LARGE_MODULE - モジュール肥大化

### 1.1 src/api/mcp_surface.py → mcp/ package (分割済み: 2026-05-03)

**分割後**:
| Module | 行数 | 内容 |
|---|---|---|
| mcp/types.py | 145 | Result dataclasses (DocRef, RecallResult, etc.) |
| mcp/surface.py | 560 | MCPSurface class (6 tool implementations) |

**判定**: 進行中 - surface.py still above 500 lines
**次段階**: Consider further method extraction if needed

### 1.2 src/core/assessment_engine.py → assessment/ package (分割済み: 2026-05-03)

**分割後**:
| Module | 行数 | 内容 |
|---|---|---|
| assessment/types.py | 91 | CausalStep, Counterfactual, Assessment dataclasses |
| assessment/store.py | 96 | AssessmentStore class |
| assessment/engine.py | 379 | AssessmentEngine class |
| assessment/__init__.py | 19 | Package exports |

**判定**: 完了 - all modules under 500 lines

### 1.3 src/queue/human_attention_queue.py → human_attention/ package (分割済み: 2026-05-03)

**分割後**:
| Module | 行数 | 内容 |
|---|---|---|
| human_attention/types.py | 185 | Enums, dataclasses, default configs |
| human_attention/queue.py | 395 | HumanAttentionQueue class |
| human_attention/routing.py | 89 | Routing functions |
| human_attention/__init__.py | 44 | Package exports |

**判定**: 完了 - all modules under 500 lines

## 2. UNSAFE_DELETE - 妥当性確認済み

### 2.1 src/adapters/registry.py

**判定**: False Positive
- `AdapterRegistry.clear()` is in-memory registry cleanup for test/dev reset
- Not actual data deletion

**対応**: 抑制設定 `.ctg/suppressions.yaml` で false positive 記録

## 3. 定期再評価

次回 code-to-gate 実行: 2026-06-02 (月次)

```bash
code-to-gate scan . --out .qh
code-to-gate analyze . --from .qh --out .qh --policy .ctg/policy.yaml
```