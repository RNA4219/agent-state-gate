# API Specification

agent-state-gate MCP Surface API仕様。

## Contract Levels

| Level | Description |
|---|---|
| P0 | MVP必須。未実装でMVP release block。 |
| P1 | Production enforce必須。block enforce前に必須。 |
| P2 | Enhancement。実装時期は柔軟。 |

---

## 1. MCP Surface API

**Module**: `src/api/mcp_surface.py`

**Contract Level**: P0 (all methods)

### 1.1 context.recall

```python
def context_recall(
    task_id: str,
    action: str,
    feature: Optional[str] = None,
    touched_paths: Optional[List[str]] = None,
    limit: int = 10
) -> RecallResult
```

**Description**: task/action起点でrequired docsを解決。

**Parameters**:
| Name | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `task_id` | `str` | Yes | UUID format | Task ID |
| `action` | `str` | Yes | - | Action type (edit_repo, install_deps, etc.) |
| `feature` | `str` | No | - | Feature context |
| `touched_paths` | `List[str]` | No | - | Target file paths |
| `limit` | `int` | No | 1-100, default 10 | Max results |

**Returns**: `RecallResult`

```python
@dataclass
class RecallResult:
    required_docs: List[DocRef]
    recommended_docs: List[DocRef]
    contract_refs: List[ContractRef]
    stale_summary: StaleSummary
    ack_required: bool
```

**Errors**:
| Error | Condition |
|---|---|
| `TaskNotFoundError` | task_id does not exist |
| `AdapterUnavailableError` | memx_adapter unavailable |

---

### 1.2 gate.evaluate

```python
def gate_evaluate(
    task_id: str,
    action: str,
    capabilities: List[str],
    risk_hints: Optional[Dict] = None,
    touched_paths: Optional[List[str]] = None
) -> EvaluateResult
```

**Description**: 統合gate評価。

**Parameters**:
| Name | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `task_id` | `str` | Yes | UUID format | Task ID |
| `action` | `str` | Yes | - | Action type |
| `capabilities` | `List[str]` | Yes | - | Requested capabilities |
| `risk_hints` | `Dict` | No | - | Additional risk context |
| `touched_paths` | `List[str]` | No | - | Target file paths |

**Returns**: `EvaluateResult`

```python
@dataclass
class EvaluateResult:
    verdict: Verdict  # allow | needs_approval | stale_blocked | deny
    required_evidence: List[EvidenceRef]
    required_approvals: List[ApprovalRef]
    missing_approvals: List[str]
    assessment_id: str
    causal_trace: List[str]
```

**Verdict Logic**:
| Return | Condition |
|---|---|
| `allow` | All conditions met, no stale, no blockers |
| `needs_approval` | Missing approval or evidence |
| `stale_blocked` | Required docs or approval stale |
| `deny` | Hard block condition |

---

### 1.3 context.stale_check

```python
def context_stale_check(task_id: str) -> StaleCheckResult
```

**Description**: stale判定。

**Parameters**:
| Name | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `task_id` | `str` | Yes | UUID format | Task ID |

**Returns**: `StaleCheckResult`

```python
@dataclass
class StaleCheckResult:
    fresh: bool
    stale_items: List[StaleItem]
    stale_reasons: List[str]
    last_check_at: datetime
```

**StaleItem Schema**:
```python
@dataclass
class StaleItem:
    item_type: str  # doc | approval | acceptance | contract
    item_id: str
    current_version: str
    expected_version: str
    stale_reason: str
```

---

### 1.4 state_gate.assess

```python
def state_gate_assess(
    artifact_refs: List[str],
    diff: str,
    run_id: str,
    stage: str
) -> StateGateAssessResult
```

**Description**: State-space gate評価。

**Parameters**:
| Name | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `artifact_refs` | `List[str]` | Yes | - | Artifact references |
| `diff` | `str` | Yes | Redacted | Diff content |
| `run_id` | `str` | Yes | UUID format | Run ID |
| `stage` | `str` | Yes | - | Current stage |

**Returns**: `StateGateAssessResult`

```python
@dataclass
class StateGateAssessResult:
    assessment_id: str
    decision_packet_ref: str
    scores: Dict[str, float]  # taboo, drift, anomaly, uncertainty
    recommendation: str
    human_queue_required: bool
    exemplar_refs: List[str]
    threshold_version: str
```

---

### 1.5 attention.list

```python
def attention_list(
    queue_scope: str = "all",
    reviewer_role: Optional[str] = None,
    status: Optional[str] = None
) -> AttentionListResult
```

**Description**: Human Attention Queue一覧。

**Parameters**:
| Name | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `queue_scope` | `str` | No | all | mine | pending | Scope filter |
| `reviewer_role` | `str` | No | security_reviewer etc. | Role filter |
| `status` | `str` | No | pending | taken | resolved | Status filter |

**Returns**: `AttentionListResult`

```python
@dataclass
class AttentionListResult:
    items: List[HumanQueueItem]
    total_pending: int
    by_severity: Dict[str, int]
    sla_status: Dict[str, SLAStatus]
```

---

### 1.6 run.replay_context

```python
def run_replay_context(
    run_id: str,
    as_of: Optional[datetime] = None
) -> ReplayContextResult
```

**Description**: Historical context snapshot replay。

**Parameters**:
| Name | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `run_id` | `str` | Yes | UUID format | Run ID |
| `as_of` | `datetime` | No | - | Historical timestamp |

**Returns**: `ReplayContextResult`

```python
@dataclass
class ReplayContextResult:
    run_id: str
    context_snapshot: Dict
    decision_packet: Dict
    assessment: Dict
    audit_packet_ref: str
    attestation_hash: str
    decision_diff: Optional[Dict]  # If current differs from historical
```

---

## 2. Core Engine API

### 2.1 AssessmentEngine

```python
class AssessmentEngine:
    def __init__(self, adapter_registry: AdapterRegistry, config: Dict)
    
    def assemble_assessment(
        self,
        decision_packet: Dict,
        task_id: str,
        run_id: str,
        stage: str
    ) -> Assessment
```

**Description**: DecisionPacket + 各状態を統合してAssessment生成。

---

### 2.2 VerdictTransformer

```python
class VerdictTransformer:
    def __init__(self, config: Dict)
    
    def transform(
        self,
        decision: str,  # pass | warn | hold | block
        stale_summary: StaleSummary,
        obligation_summary: ObligationSummary,
        approval_summary: ApprovalSummary,
        evidence_summary: EvidenceSummary
    ) -> Verdict
```

**Description**: gatefield decision → 外部 verdict変換。

---

### 2.3 ConflictResolver

```python
class ConflictResolver:
    def resolve(
        self,
        decision_packet: Dict,
        stale_result: Dict,
        obligation_result: Dict,
        approval_result: Dict
    ) -> ConflictResolution
```

**Description**: 判定衝突解決。

---

## 3. Queue API

### 3.1 HumanAttentionQueue

```python
class HumanAttentionQueue:
    def enqueue(self, item: HumanQueueItem) -> str
    def take(self, reviewer_role: str) -> Optional[HumanQueueItem]
    def resolve(self, item_id: str, resolution: Resolution) -> None
    def escalate(self, item_id: str) -> None
    def get_pending(self) -> List[HumanQueueItem]
    def get_stats(self) -> QueueStats
```

---

## 4. Audit API

### 4.1 AuditPacketGenerator

```python
class AuditPacketGenerator:
    def generate(
        self,
        assessment: Assessment,
        decision_packet: Dict,
        trace_id: str,
        span_id: str
    ) -> AuditPacket
    
    def export_jsonl(self) -> str
    def export_otlp(self) -> List[Dict]
```

---

## 5. Error Types

| Error Type | HTTP Equivalent | Description |
|---|---|---|
| `TaskNotFoundError` | 404 | Task does not exist |
| `RunNotFoundError` | 404 | Run does not exist |
| `AdapterUnavailableError` | 503 | Adapter unavailable |
| `StaleCheckError` | 500 | Stale check failed |
| `AssessmentError` | 500 | Assessment assembly failed |
| `QueueCapacityError` | 503 | Queue exceeds capacity |
| `UnauthorizedReviewerError` | 403 | Reviewer not authorized |

---

## 6. Verdict Types

```python
class Verdict(Enum):
    ALLOW = "allow"
    NEEDS_APPROVAL = "needs_approval"
    STALE_BLOCKED = "stale_blocked"
    DENY = "deny"
    REVISE = "revise"
    REQUIRE_HUMAN = "require_human"
```

---

## 7. Severity Types

```python
class Severity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
```

---

## 8. Reason Codes for Human Queue

```python
class ReasonCode(Enum):
    TABOO_PROXIMITY = "taboo"
    REJECTED_CASE_SIMILARITY = "rejected_case"
    HIGH_RISK_CAPABILITY = "high_risk"
    STALE_UNRESOLVED = "stale"
    APPROVAL_MISSING = "approval_missing"
    EVIDENCE_MISSING = "evidence_missing"
    ANOMALY_HIGH = "anomaly"
    OVERRIDE_REQUESTED = "override"
    POLICY_CONFLICT = "policy_conflict"
```

---

## 9. Version History

| Version | Date | Changes |
|---|---|---|
| 0.1.0 | 2026-04-26 | Initial API specification |