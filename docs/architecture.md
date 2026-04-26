# Architecture

agent-state-gateのアーキテクチャ設計。

## 1. レイヤ構成

```
┌─────────────────────────────────────────────────┐
│                 MCP Surface                      │
│         (src/api/mcp_surface.py)                 │
├─────────────────────────────────────────────────┤
│               Core Engine                        │
│  ┌─────────────┬─────────────────────────────┐  │
│  │ Assessment  │ Verdict Transformer        │  │
│  │ Engine      │ (verdict_transformer.py)   │  │
│  │ (assessment │                             │  │
│  │ _engine.py) │ Conflict Resolver          │  │
│  │             │ (conflict_resolver.py)     │  │
│  └─────────────┴─────────────────────────────┘  │
├─────────────────────────────────────────────────┤
│               Adapters                           │
│  ┌────────┬────────┬────────┬────────┬────────┐ │
│  │gatefield│taskstate│protocols│memx  │shipyard│ │
│  │adapter │adapter │adapter │adapter│adapter │ │
│  └────────┴────────┴────────┴────────┴────────┘ │
├─────────────────────────────────────────────────┤
│           Human Attention Queue                  │
│         (src/queue/human_attention_queue.py)    │
├─────────────────────────────────────────────────┤
│               Audit Layer                        │
│  ┌─────────────┬─────────────────────────────┐  │
│  │ Audit       │ Evidence                   │  │
│  │ Packet      │ Recorder                   │  │
│  │ (audit_     │ (evidence_recorder.py)     │  │
│  │ packet.py)  │                             │  │
│  └─────────────┴─────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

## 2. データフロー

```
┌────────────┐    DecisionPacket    ┌─────────────┐
│ agent-     │ ───────────────────→ │ gatefield   │
│ gatefield  │                      │ adapter     │
└────────────┘                      └──────┬──────┘
                                           │
                                           ↓
┌────────────┐    Task/Run/Context ┌─────────────┐
│ agent-     │ ──────────────────→ │ taskstate   │
│ taskstate  │                     │ adapter     │
└────────────┘                     └──────┬──────┘
                                          │
                                          ↓
                          ┌─────────────────────────┐
                          │   Assessment Engine     │
                          │   (assessment_engine.py)│
                          └──────┬──────────────────┘
                                 │
                                 ↓
┌────────────┐    Stale/Obligation ┌─────────────┐
│ memx-      │ ──────────────────→ │ memx        │
│ resolver   │                     │ adapter     │
└────────────┘                     └──────┬──────┘
                                          │
                                          ↓
┌────────────┐    Risk/Approval    ┌─────────────┐
│ agent-     │ ─────────────────→ │ protocols   │
│ protocols  │                    │ adapter     │
└────────────┘                    └──────┬──────┘
                                         │
                                         ↓
                          ┌─────────────────────────┐
                          │   Verdict Transformer   │
                          │   (verdict_transformer.py│
                          └──────┬──────────────────┘
                                 │
                                 ↓
                          ┌─────────────────────────┐
                          │   Final Assessment      │
                          │   (allow/needs_approval │
                          │    stale_blocked/deny)  │
                          └──────┬──────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    ↓            ↓            ↓
           ┌───────────┐ ┌───────────┐ ┌───────────┐
           │ Human     │ │ Audit     │ │ shipyard  │
           │ Attention │ │ Packet    │ │ adapter   │
           │ Queue     │ │           │ │ (hold)    │
           └─────┬─────┘ └─────┬─────┘ └─────┬─────┘
                 │           │           │
                 ↓           ↓           ↓
           Reviewer      SIEM        Control Plane
```

## 3. Adapter構成

### 3.1 Base Adapter Interface

```python
class BaseAdapter(ABC):
    name: str
    capability: str
    operation_mode: str  # read-only | append-only | controlled-mutation
    idempotency_key: Optional[str]
    timeout_ms: int
    failure_policy: str  # fail-closed | fail-open | needs-approval
    
    @abstractmethod
    def health_check(self) -> bool
    
    @abstractmethod
    def get_metadata(self) -> AdapterMetadata
```

### 3.2 Adapter Registry

```python
class AdapterRegistry:
    adapters: Dict[str, BaseAdapter]
    
    def register(self, adapter: BaseAdapter) -> None
    def get(self, name: str) -> Optional[BaseAdapter]
    def get_all(self) -> List[BaseAdapter]
    def health_check_all(self) -> Dict[str, bool]
```

## 4. Assessment構造

### 4.0 正本境界定義 (Ownership Boundary)

Assessmentの保存・参照責任境界を以下のように固定：

| Entity | 正本保存先 | 参照可能 | 参照方法 |
|---|---|---|---|
| **Assessment** | **agent-state-gate Assessment Store** | agent-context-mcp, shipyard-cp, audit subsystem | `assessment_id` typed_ref |
| DecisionPacket | agent-gatefield | agent-state-gate | `decision_packet_ref` typed_ref |
| Task/Run/ContextBundle | agent-taskstate | agent-state-gate | `task_id`, `run_id`, `context_bundle_ref` typed_ref |
| Evidence | workflow-cookbook Evidence Store | agent-state-gate | `evidence_ref` typed_ref |

**重要: agent-taskstateはAssessmentのlinked refのみ保持**
```python
# agent-taskstate側: linked refのみ
@dataclass
class TaskState:
    ...
    assessment_ref: Optional[str]  # typed_ref: agent-state-gate:assessment:local:{id}
    # Assessment本体は保持しない

# agent-state-gate側: 正本保存
class AssessmentStore:
    def save(self, assessment: Assessment) -> str:
        """Assessment正本をagent-state-gate DBに保存"""
        assessment_id = generate_uuid()
        self.db.insert(assessment)
        return format_ref("agent-state-gate", "assessment", "local", assessment_id)
    
    def get(self, assessment_ref: str) -> Assessment:
        """typed_refからAssessment正本を取得"""
        parsed = parse_ref(assessment_ref)
        assert parsed.domain == "agent-state-gate"
        return self.db.query_by_id(parsed.entity_id)
```

**責任境界の理由**:
1. **Replay再現性**: Assessment本体がagent-state-gate内で一元管理されることで、threshold_version + context_hashによる再現性保証が可能
2. **Audit完全性**: Audit packet生成時にAssessment正本への直接アクセスが可能、外部参照不整合を回避
3. **MCP参照効率**: context.recall/gate.evaluateがAssessment正本を直接返却可能、cross-repo fetchを最小化
4. **Shipyard連携**: hold_for_review時のAssessment参照が単一path、race condition回避

**禁止パターン**:
- ❌ agent-taskstateにAssessment本体を保存 (正本重複)
- ❌ agent-gatefieldにAssessmentを保存 (DecisionPacketと混在)
- ❌ MCP surfaceがagent-taskstate経由でAssessment取得 (遅延・不整合)

---

```python
@dataclass
class Assessment:
    assessment_id: str
    decision_packet_ref: str         # agent-gatefield DecisionPacket ID
    task_id: str                     # agent-taskstate task_id (typed_ref format)
    run_id: str                      # agent-taskstate run_id (typed_ref format)
    stage: str                       # shipyard-cp stage
    context_bundle_ref: str          # agent-taskstate context_bundle_id (typed_ref)
    
    stale_summary: StaleSummary
    obligation_summary: ObligationSummary
    approval_summary: ApprovalSummary
    evidence_summary: EvidenceSummary
    
    final_verdict: Verdict           # allow | needs_approval | stale_blocked | deny
    causal_trace: List[CausalStep]   # 判断根拠の連鎖
    counterfactuals: List[Counterfactual]  # 代替条件
    
    audit_packet_ref: str            # Audit packet ID
    threshold_version: str           # 設定バージョン (sha256 hash)
    created_at: datetime
```

### 4.1 CausalStep構造

```python
@dataclass
class CausalStep:
    step_id: str
    source: str                      # gatefield | stale_check | obligation_check | approval_check | evidence_check
    rule_id: str                     # 適用ルールID
    input_state: Dict                # 入力状態snapshot
    output_state: Dict               # 出力状態snapshot
    contribution_weight: float       # 最終判定への寄与度 0.0-1.0
    rationale: str                   # 判断理由
```

**Contribution Weight Calculation**:
```python
def calculate_contribution_weight(
    step: CausalStep,
    final_verdict: Verdict,
    all_steps: List[CausalStep]
) -> float:
    """各stepの最終判定への寄与度を計算"""
    
    # Base weight by source type
    SOURCE_BASE_WEIGHTS = {
        "gatefield": 0.40,           # DecisionPacket is primary driver
        "stale_check": 0.20,         # Stale can override pass to stale_blocked
        "obligation_check": 0.15,    # Obligation gaps trigger needs_approval
        "approval_check": 0.15,      # Missing approvals trigger needs_approval
        "evidence_check": 0.10       # Evidence gaps lower confidence
    }
    
    base_weight = SOURCE_BASE_WEIGHTS.get(step.source, 0.05)
    
    # Verdict impact multiplier
    VERDICT_IMPACT = {
        Verdict.DENY: 1.5,           # Blocking decisions have higher weight
        Verdict.STALE_BLOCKED: 1.2,
        Verdict.NEEDS_APPROVAL: 1.0,
        Verdict.ALLOW: 0.8
    }
    
    impact_multiplier = VERDICT_IMPACT.get(final_verdict, 1.0)
    
    # Rule severity modifier (if step triggered a rule)
    if step.rule_id:
        RULE_SEVERITY_MODIFIER = {
            "critical": 1.5,
            "high": 1.2,
            "medium": 1.0,
            "low": 0.8
        }
        severity = extract_rule_severity(step.rule_id)
        severity_modifier = RULE_SEVERITY_MODIFIER.get(severity, 1.0)
    else:
        severity_modifier = 1.0
    
    # Normalize across all steps (sum should be 1.0)
    raw_weight = base_weight * impact_multiplier * severity_modifier
    total_raw = sum(calculate_raw_weight(s, final_verdict) for s in all_steps)
    
    return raw_weight / total_raw if total_raw > 0 else 0.0
```

**Example Trace**:
| step_id | source | rule_id | contribution_weight | rationale |
|---|---|---|---:|---|
| STEP-001 | gatefield | taboo_warn | 0.42 | taboo_proximity 0.85 >= 0.80 threshold |
| STEP-002 | stale_check | doc_version_changed | 0.24 | required_doc v2 != expected v1 |
| STEP-003 | approval_check | missing_security | 0.18 | security_reviewer approval missing |
| STEP-004 | evidence_check | test_coverage_low | 0.16 | coverage 0.72 < 0.85 target |

### 4.2 Counterfactual構造

```python
@dataclass
class Counterfactual:
    counterfactual_id: str
    condition: str                   # 代替条件 "if X were Y"
    alternative_verdict: Verdict     # 代替条件下の判定
    required_action: str             # 条件達成に必要なアクション
    feasibility: str                 # easy | medium | hard | impossible
```

### 4.3 StaleSummary構造

```python
@dataclass
class StaleSummary:
    fresh: bool
    stale_items: List[StaleItem]
    stale_reasons: List[str]         # doc_version_changed | approval_expired | contract_updated
    last_check_at: datetime
```

### 4.4 ObligationSummary構造

```python
@dataclass
class ObligationSummary:
    obligations: List[Obligation]
    fulfilled: List[str]             # fulfilled obligation IDs
    unfulfilled: List[str]           # unfulfilled obligation IDs
    partial: List[str]               # partially fulfilled IDs
    fulfillment_rate: float          # 0.0-1.0
```

### 4.5 ApprovalSummary構造

```python
@dataclass
class ApprovalSummary:
    required_approvals: List[ApprovalRef]
    obtained_approvals: List[ApprovalRef]
    missing_approvals: List[str]     # missing approver roles
    expired_approvals: List[str]     # expired approval IDs
    approval_binding_hash: str       # diff_hash + context_hash for binding
```

### 4.6 EvidenceSummary構造

```python
@dataclass
class EvidenceSummary:
    required_evidence: List[EvidenceRef]
    collected_evidence: List[EvidenceRef]
    missing_evidence: List[str]      # missing evidence types
    evidence_strength: float         # 0.0-1.0
    confidence_level: str            # high | medium | low
```

### 4.7 Risk Derivation Thresholds (DATA_TYPES_SPEC準拠)

agent-gatefield DATA_TYPES_SPEC CalibrationProfile thresholds準拠。

| Threshold | Default | Range | Description |
|---|---:|---|---|
| `taboo_warn` | 0.80 | 0.0-1.0 | Taboo proximity similarity threshold for warn |
| `taboo_block` | 0.88 | 0.0-1.0 | Taboo proximity similarity threshold for block |
| `negative_similarity_warn` | 0.75 | 0.0-1.0 | Rejected-case similarity warn threshold |
| `negative_similarity_block` | 0.85 | 0.0-1.0 | Rejected-case similarity block threshold |
| `drift_warn` | 0.15 | 0.0-1.0 | EWMA drift from accepted baseline warn |
| `drift_block` | 0.25 | 0.0-1.0 | EWMA drift block threshold |
| `anomaly_warn_percentile` | 95 | 90-99 | Isolation Forest contamination percentile warn |
| `anomaly_block_percentile` | 99 | 95-99 | Anomaly block percentile |
| `judge_std_warn` | 0.15 | 0.0-1.0 | Evaluator disagreement standard deviation warn |
| `judge_std_block` | 0.25 | 0.0-1.0 | Judge disagreement block threshold |
| `tool_failure_rate_warn` | 0.10 | 0.0-1.0 | Tool execution failure rate warn |
| `tool_failure_rate_block` | 0.25 | 0.0-1.0 | Tool failure rate block threshold |

**Hard Override Rules**:
| Rule | Default | Description |
|---|---:|---|
| `block_if_secret_found` | true | Secret detection triggers immediate block |
| `block_if_prod_write_and_taboo_warn` | true | Production write + taboo_warn = block |
| `hold_if_high_privilege_and_uncertain` | true | High privilege + uncertainty = hold for review |

**Risk Score Calculation**:
```python
def calculate_risk_score(
    factors: List[ScoreFactor],
    thresholds: Dict[str, float]
) -> Tuple[Verdict, Severity]:
    """Risk scoreからverdict/severityを導出"""
    
    # Hard override check (priority 1)
    if factors.get("secret", 0) > 0:
        return Verdict.DENY, Severity.CRITICAL
    
    if factors.get("prod_write", 0) == 1 and factors.get("taboo_proximity", 0) >= thresholds["taboo_warn"]:
        return Verdict.DENY, Severity.CRITICAL
    
    if factors.get("permission_level") == "admin" and factors.get("uncertainty_score", 0) >= thresholds["judge_std_warn"]:
        return Verdict.NEEDS_APPROVAL, Severity.HIGH
    
    # Threshold check (priority 2)
    if factors.get("taboo_proximity", 0) >= thresholds["taboo_block"]:
        return Verdict.DENY, Severity.HIGH
    
    if factors.get("taboo_proximity", 0) >= thresholds["taboo_warn"]:
        return Verdict.NEEDS_APPROVAL, Severity.HIGH
    
    # ... (continue for each factor)
    
    return Verdict.ALLOW, Severity.LOW
```

**参照**: agent-gatefield DATA_TYPES_SPEC CalibrationProfile lines 2135-2285

## 5. Human Attention Queue構造

```python
@dataclass
class HumanQueueItem:
    item_id: str
    assessment_id: str
    task_id: str
    run_id: str
    
    reason_code: ReasonCode          # taboo | rejected_case | high_risk | stale | approval_missing
    severity: Severity               # critical | high | medium | low
    required_role: str               # security_reviewer | project_lead | release_manager
    
    # Ownership Context (権限feature必須)
    task_owner: str                  # task作成者
    task_owner_type: str             # human | agent | system
    ownership_context: Dict          # owner権限範囲
    
    due_at: datetime
    sla: SLADefinition
    
    suggested_actions: List[str]
    exemplar_refs: List[str]
    
    status: QueueStatus              # pending | taken | resolved | escalated
    assigned_to: Optional[str]
    taken_at: Optional[datetime]
    resolved_at: Optional[datetime]
    resolution: Optional[Resolution]
```

**Ownership Context Structure**:
```python
@dataclass
class OwnershipContext:
    owner_id: str                    # owner identifier
    owner_role: str                  # owner primary role
    permission_scope: List[str]      # ["read", "write"] etc.
    data_classification_access: List[str]  # ["internal", "confidential"] etc.
    service_scope: List[str]         # ["service-a", "service-b"] etc.
    approval_authority_level: int    # 1-4 hierarchy level
```

**Ownership Check Rules**:
| Condition | Required Check |
|---|---|
| required_role != task_owner_role | Cross-owner approval required |
| permission_scope includes "admin" | Higher authority review required |
| data_classification_access mismatch | Security reviewer required |
| service_scope cross-boundary | Architecture reviewer required |

### 5.0 State Transition Validation (Invalid Transition Detection)

stateful entityのinvalid transition検出ルール。

**Task Status Transitions** (agent-taskstate準拠):
```python
VALID_TASK_TRANSITIONS = {
    "draft": ["ready", "archived"],
    "ready": ["in_progress", "archived"],
    "in_progress": ["blocked", "review", "done"],
    "blocked": ["in_progress"],
    "review": ["in_progress", "done"],
    "done": ["archived", "in_progress"],  # reopen allowed
    "archived": []  # terminal state
}

INVALID_TASK_TRANSITIONS = [
    ("draft", "in_progress"),      # draft -> ready 必須
    ("ready", "done"),             # in_progress 必須
    ("blocked", "done"),           # unblock必須
    ("review", "blocked"),         # invalid
]

def validate_task_transition(from_status: str, to_status: str) -> bool:
    """Task status遷移validation"""
    allowed = VALID_TASK_TRANSITIONS.get(from_status, [])
    return to_status in allowed
```

**Human Queue Status Transitions**:
```python
VALID_QUEUE_TRANSITIONS = {
    "pending": ["taken", "escalated"],
    "taken": ["resolved", "escalated"],
    "escalated": ["taken", "resolved"],
    "resolved": []  # terminal state
}

INVALID_QUEUE_TRANSITIONS = [
    ("pending", "resolved"),       # take必須
    ("escalated", "pending"),      # escalation不可逆
    ("resolved", "taken"),         # terminal不可逆
]
```

**Assessment Verdict Transitions**:
```python
VALID_VERDICT_TRANSITIONS = {
    "allow": ["needs_approval", "stale_blocked"],  # condition change
    "needs_approval": ["allow", "stale_blocked", "deny"],
    "stale_blocked": ["needs_approval", "allow"],  # stale解消
    "deny": []  # terminal (require override)
}

INVALID_VERDICT_TRANSITIONS = [
    ("deny", "allow"),             # override必須
    ("allow", "deny"),             # hard block不可逆
    ("stale_blocked", "deny"),     # stale解消前にblock不可
]
```

**Invalid Transition Detection Logic**:
```python
def detect_invalid_transition(
    entity_type: str,
    from_state: str,
    to_state: str,
    context: Dict
) -> Optional[InvalidTransitionError]:
    """Invalid遷移検出"""
    
    transition_rules = {
        "task": VALID_TASK_TRANSITIONS,
        "human_queue": VALID_QUEUE_TRANSITIONS,
        "assessment": VALID_VERDICT_TRANSITIONS,
    }
    
    valid_transitions = transition_rules.get(entity_type, {})
    allowed = valid_transitions.get(from_state, [])
    
    if to_state not in allowed:
        return InvalidTransitionError(
            entity_type=entity_type,
            from_state=from_state,
            to_state=to_state,
            reason=f"Transition {from_state} -> {to_state} not allowed",
            allowed_transitions=allowed,
            context=context
        )
    
    return None
```

**Invalid Transition Handling**:
| Entity | Invalid Transition | Handling |
|---|---|---|
| Task | draft -> in_progress | Block, require ready status |
| HumanQueue | pending -> resolved | Block, require take first |
| Assessment | deny -> allow | Block, require waiver approval |

### 5.1 SLA Enforcement Logic

```python
def enforce_sla(item: HumanQueueItem, now: datetime) -> SLAAction:
    """SLA期限監視とアクション判定"""
    
    # ACK期限チェック
    ack_deadline = item.taken_at or item.created_at + item.sla.ack_deadline
    if item.status == "pending" and now > ack_deadline:
        return SLAAction.ESCALATE_ACK_TIMEOUT
    
    # Decision期限チェック
    decision_deadline = item.due_at
    if item.status in ["pending", "taken"] and now > decision_deadline:
        if item.severity == "critical":
            return SLAAction.AUTO_BLOCK
        elif item.severity == "high":
            return SLAAction.ESCALATE_DECISION_TIMEOUT
        else:
            return SLAAction.MOVE_TO_BACKLOG
    
    # Escalation chainチェック
    if item.status == "escalated":
        escalation_level = calculate_escalation_level(item, now)
        if escalation_level > len(item.sla.escalation_chain):
            return SLAAction.GOVERNANCE_BOARD_NOTIFY
    
    return SLAAction.NONE

class SLAAction(Enum):
    NONE = "none"
    ESCALATE_ACK_TIMEOUT = "escalate_ack_timeout"
    ESCALATE_DECISION_TIMEOUT = "escalate_decision_timeout"
    AUTO_BLOCK = "auto_block"
    MOVE_TO_BACKLOG = "move_to_backlog"
    GOVERNANCE_BOARD_NOTIFY = "governance_board_notify"
```

**参照**: gate_config.yaml human_queue.sla lines 57-76

## 6. Audit Packet構造

```python
@dataclass
class AuditPacket:
    packet_id: str
    trace_id: str                    # OTel trace ID
    span_id: str                     # OTel span ID
    
    assessment_id: str
    run_id: str
    
    decision_packet: Dict            # gatefield DecisionPacket (hashed)
    stale_check_result: Dict
    obligation_check_result: Dict
    approval_check_result: Dict
    evidence_check_result: Dict
    
    final_verdict: Verdict
    verdict_reason: str
    causal_trace: List[str]
    
    context_hash: str                # context snapshot hash
    diff_hash: str                   # artifact diff hash
    threshold_version: str
    
    created_at: datetime
    retention_class: str             # audit | ops | pii-sensitive
```

## 7. MCP Surface API構成

| API | 入力 | 出力 | 内部ルーティング |
|---|---|---|---|
| context.recall | task_id, action, feature | required docs, stale summary | memx_adapter, taskstate_adapter |
| gate.evaluate | task_id, action, capabilities | verdict, required evidence | 全adapter, assessment_engine |
| context.stale_check | task_id | stale status, stale reasons | memx_adapter, taskstate_adapter |
| state_gate.assess | artifact refs, diff, run_id | state-space assessment | gatefield_adapter, assessment_engine |
| attention.list | reviewer_role, status | pending queue items | human_attention_queue |
| run.replay_context | run_id | historical context, decision diff | taskstate_adapter, audit_packet |

## 8. 設定ファイル構造

```yaml
# config/gate_config.yaml
version: 0.1.0
environment: local | ci | staging | production

adapters:
  gatefield:
    enabled: true
    endpoint: ${AGENT_GATEFIELD_URL}
    timeout_ms: 5000
    failure_policy: fail-closed
  taskstate:
    enabled: true
    endpoint: ${AGENT_TASKSTATE_URL}
    timeout_ms: 3000
    failure_policy: fail-closed
  protocols:
    enabled: true
    schema_path: ${AGENT_PROTOCOLS_SCHEMAS}
    timeout_ms: 2000
    failure_policy: needs-approval
  memx:
    enabled: true
    endpoint: ${MEMX_RESOLVER_URL}
    timeout_ms: 3000
    failure_policy: stale-blocked
  shipyard:
    enabled: true
    endpoint: ${SHIPYARD_CP_URL}
    timeout_ms: 5000
    failure_policy: fail-closed
  workflow:
    enabled: true
    docs_path: ${WORKFLOW_COOKBOOK_PATH}
    timeout_ms: 2000
    failure_policy: needs-approval

verdict:
  thresholds:
    stale_blocked_on_required_docs: true
    needs_approval_on_missing_evidence: true
  
  authority_hierarchy:
    human_policy: 4
    repo_policy: 3
    task_contract: 2
    agent_summary: 1

human_queue:
  sla:
    critical: { ack: 15min, decision: 60min }
    high: { ack: 60min, decision: 240min }
    medium: { ack: 8h, decision: 24h }
    low: { ack: null, decision: backlog }
  
  escalation:
    critical: [project_lead, governance_board]
    high: [project_lead]
    medium: [owner]

audit:
  retention:
    audit: 365d
    ops: 90d
    pii-sensitive: 30d
  export_format: jsonl | otlp
```