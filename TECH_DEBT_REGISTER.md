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

### 1.2 src/core/assessment_engine.py (581 lines)

**現状**: Assessment engine orchestrates 5 verdict transformations.

**分割計画**:
| 新モジュール | 内容 | 行数見積 |
|---|---|---|
| `assessment/verdict_transformer.py` | Verdict transformation logic | ~200 |
| `assessment/conflict_resolver.py` | Conflict resolution | ~150 |
| `assessment/evidence_assembler.py` | Evidence assembly | ~150 |
| `assessment/__init__.py` | Engine class, public API | ~100 |

**優先度**: Low (Q3) - acceptable complexity for core engine

### 1.3 src/queue/human_attention_queue.py (607 lines)

**現状**: Human Attention Queue handles 4 priority levels with persistence.

**分割計画**:
| 新モジュール | 内容 | 行数見積 |
|---|---|---|
| `queue/priority_handlers.py` | Priority-specific handlers | ~200 |
| `queue/persistence.py` | Queue persistence logic | ~150 |
| `queue/dispatch.py` | Queue dispatch logic | ~150 |
| `queue/__init__.py` | Queue class, public API | ~100 |

**優先度**: Low (Q3) - when queue grows beyond 800 lines

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