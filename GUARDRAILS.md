# agent-state-gate GUARDRAILS

## 行動指針

本プロジェクトは「統合統治層」であり、「新規判定エンジン」ではない。以下のガードレールを遵守。

## 1. 二重実装禁止

- agent-gatefield の score (taboo/drift/anomaly/uncertainty) を再計算しない
- DecisionPacket の factors、exemplar_refs、threshold_version を読み取って統合判断へ変換する
- 状態ベクトル生成は agent-gatefield に委譲する

## 2. 正本尊重

- Task/Run/ContextBundle の正本は agent-taskstate にある
- DecisionPacket の正本は agent-gatefield にある
- Evidence の正本は workflow-cookbook/Evidence store にある
- Approval の正本は agent-protocols compatible store にある

本プロジェクトはこれらを読み取り、Assessment を生成する。

## 3. MCP Surface 制限

### 公開API（MCP Tools）
- context.recall
- gate.evaluate
- context.stale_check
- state_gate.assess
- attention.list
- run.replay_context

### 内部API（明示的 consent または human-in-the-loop 必須）
- remember / relate / invalidate
- policy mutate
- publish apply
- approval create / waiver create

## 4. 判定優先順位

```
critical static fail
> taboo block / secret / compliance block
> approval or stale hard block
> require_human
> revise
> warn
> pass
```

## 5. 人間介入原則

- 人間は全文レビューではなく、例外だけを見る
- Human Attention Queue は first-class object
- Override/Waiver は常態化禁止
- Approval は current diff + current context hash に束縛

## 6. セキュリティ原則

- Taint tracking: untrusted context が policy を上書きしない
- Authority hierarchy: human policy > repo policy > task contract > agent summary
- Secret handling: external LLM/storage へ未加工 secret を渡さない
- Approval binding: diff/context hash で freshness 管理

## 7. Adapter失敗時の既定

| Adapter | 失敗時既定 |
|---|---|
| workflow-cookbook | required evidence 不明なら needs_approval |
| memx-resolver | required docs/stale 不明なら stale_blocked |
| agent-taskstate | task/run/context 不明なら deny |
| agent-protocols | risk/approval 不明なら needs_approval |
| shipyard-cp | hold 不能なら high-risk は deny |
| agent-gatefield | unavailable なら high-risk は require_human、publish は deny |

## 8. 出力契約

### plan 出力形式
- node_id と role を明示（Birdseye 連携）
- 依存関係を明示
- 制約を明示

### Assessment 出力形式
```json
{
  "assessment_id": "uuid",
  "decision_packet_ref": "uuid",
  "task_id": "uuid",
  "run_id": "uuid",
  "stage": "string",
  "final_verdict": "allow|needs_approval|stale_blocked|deny",
  "stale_summary": {...},
  "obligation_summary": {...},
  "approval_summary": {...},
  "evidence_summary": {...},
  "causal_trace": [...],
  "counterfactuals": [...],
  "audit_packet_ref": "uuid"
}
```

## 9. 開発フロー

- タスクは独立性が保てる粒度まで分割
- 変更は小さく・短時間で終わるブランチ
- 早めの rebase で最新に追従
- リスクがある場合は Task Seeds に記載

## 10. 禁止事項

- 既存repoの責務を奪う実装
- MCP から dangerous mutation を直接公開
- Approval を diff 変更後に再利用
- Override/Waiver の常態化
- Raw prompt/payload の外部保存