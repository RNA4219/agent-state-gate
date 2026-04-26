# Adapter Contract

agent-state-gate Adapter契約定義。

## Adapter共通契約

すべてのAdapterは `BaseAdapter` インタフェースを実装。

### typed_ref Canonical Format

agent-state-gateはmemx-resolverの4セグメントcanonical formatを採用:

```text
<domain>:<entity_type>:<provider>:<entity_id>
```

| セグメント | 説明 | 例 |
|---|---|---|
| `domain` | システム領域 | memx, agent-taskstate, tracker, agent-gatefield |
| `entity_type` | エンティティ種別 | evidence, artifact, task, decision, run |
| `provider` | データソース | local, jira, github, linear |
| `entity_id` | 一意識別子 | UUIDまたはシステム固有ID |

**互換性**: 3セグメント入力 `<domain>:<entity_type>:<id>` は `provider=local` として正規化。

**実装状況**:
| System | Implementation | KNOWN_DOMAINS |
|---|---|---|
| memx-resolver | 4-segment canonical | memx |
| agent-taskstate | `src/typed_ref.py` (4-segment, 3-segment legacy compatible) | agent-taskstate, memx, tracker |
| agent-state-gate | agent-taskstate typed_ref module使用 | agent-taskstate, memx, tracker, agent-gatefield (追加必要) |

**Domain Extension (agent-state-gate)**:
```python
# src/typed_ref_domain_ext.py
KNOWN_DOMAINS_AGENT_STATE_GATE = KNOWN_DOMAINS | {"agent-gatefield", "shipyard-cp"}
```

**参照**: 
- memx-resolver interfaces.md lines 197-245
- agent-taskstate src/typed_ref.py (format_ref, parse_ref, canonicalize_ref)

```python
@dataclass
class AdapterMetadata:
    name: str
    capability: str
    operation_mode: str  # read-only | append-only | controlled-mutation
    idempotency_key: Optional[str]
    timeout_ms: int
    failure_policy: str  # fail-closed | fail-open | needs-approval
    audit_required: bool

class BaseAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str
    
    @property
    @abstractmethod
    def capability(self) -> str
    
    @abstractmethod
    def health_check(self) -> bool
    
    @abstractmethod
    def get_metadata(self) -> AdapterMetadata
```

---

## 1. GatefieldAdapter

**Target**: `agent-gatefield`

**Operation Mode**: read + append-only decision

**Module**: `src/adapters/gatefield_adapter.py`

### 1.1 Required Methods

```python
class GatefieldAdapter(BaseAdapter):
    def evaluate(
        self,
        artifact: Dict,
        trace: Dict,
        rule_results: Dict
    ) -> Dict  # DecisionPacket
    
    def enqueue_review(
        self,
        review_item: Dict
    ) -> str  # review_id
    
    def export_audit(
        self,
        run_id: str
    ) -> Dict  # audit_events
    
    def get_decision_packet(
        self,
        decision_id: str
    ) -> Dict
    
    def get_state_vector(
        self,
        run_id: str
    ) -> Dict
```

### 1.2 DecisionPacket Schema (DATA_TYPES_SPEC v1.0.0準拠)

gatefield_adapterのDecisionPacketはagent-gatefield DATA_TYPES_SPEC完全版に準拠。

**Required Fields** (全28項目):
| Field | Type | Description |
|---|---|---|
| `schema_version` | string const "1.0.0" | Schema version for replay reproducibility |
| `decision_id` | uuid | Unique decision identifier |
| `run_id` | uuid | Run identifier |
| `artifact_id` | uuid | Artifact identifier |
| `decision` | enum: pass/warn/hold/block | Gate decision state |
| `composite_score` | number 0.0-1.0 | Weighted composite score |
| `factors` | array[ScoreFactor] | Top contributing factors (min 1, max 10) |
| `exemplar_refs` | array[ExemplarRef] | Top 5 nearest exemplars from KB |
| `action` | ActionRecommendation | Recommended action |
| `threshold_version` | string sha256 hash | Threshold config hash for reproducibility |
| `policy_version` | string | Policy version identifier |
| `artifact_ref` | object | Artifact URI plus `diff_hash` for approval binding |
| `diff_hash` | string | Top-level mirror for adapter compatibility |
| `static_gate_summary` | StaticGateSummary | Summary of static gate results |
| `created_at` | datetime RFC3339 | Decision timestamp |

**Optional Fields**:
| Field | Type | Description |
|---|---|---|
| `hard_override` | enum: secret_found/prod_write_taboo/tool_policy_deny/high_privilege_uncertain | Hard override rule triggered |
| `self_correction_count` | integer 0-2 | Self-correction attempts |
| `review_override` | ReviewOverride | Human review override |
| `trace_id` | string 32 hex chars | OTel trace ID for correlation |
| `state_vector_ref` | string state:// URI | Reference to full state vector |

**ScoreFactor Structure**:
```json
{
  "name": "taboo_proximity",
  "value": 0.85,
  "weight": 0.30,
  "contribution": 0.255,
  "threshold": 0.80,
  "threshold_type": "warn"
}
```
Factor names: constitution_alignment, taboo_proximity, accept_similarity, reject_similarity, direction_score, drift_score, anomaly_score, uncertainty_score, rule_violation, test_evidence

**ExemplarRef Structure**:
```json
{
  "doc_id": "uuid",
  "axis_type": "taboo",
  "similarity": 0.85,
  "version": "v1",
  "text_excerpt": "string (max 500)"
}
```
axis_type: constitution, taboo, accepted, rejected, judgment_log

**ActionRecommendation Structure**:
```json
{
  "action_type": "hold_for_review",
  "correction_target": "string",
  "correction_details": {},
  "checkpoint_ref": "checkpoint://..."
}
```
action_type: continue, self_correct, hold_for_review, block, artifact_correction, process_correction, prompt_correction

**StaticGateSummary Structure**:
```json
{
  "gates_executed": ["lint", "sast", "secret_scan"],
  "all_passed": true,
  "hard_failures": [],
  "warnings": [{"gate_name": "lint", "count": 2}]
}
```

**参照**: DATA_TYPES_SPEC完全版は `agent-gatefield/docs/spec/DATA_TYPES_SPEC.md` lines 779-1141
```

### 1.3 Failure Policy

| Condition | Default Action |
|---|---|
| unavailable | high-risk → require_human, publish → deny |
| timeout | fail-closed for production, fail-open for dev |

---

## 2. TaskstateAdapter

**Target**: `agent-taskstate`

**Operation Mode**: read + append-only event

**Module**: `src/adapters/taskstate_adapter.py`

### 2.1 Required Methods

```python
class TaskstateAdapter(BaseAdapter):
    def get_task(
        self,
        task_id: str
    ) -> Dict  # Task
    
    def get_run(
        self,
        run_id: str
    ) -> Dict  # Run
    
    def get_context_bundle(
        self,
        bundle_id: str
    ) -> Dict  # ContextBundle
    
    def record_read_receipt(
        self,
        task_id: str,
        doc_id: str,
        version: str,
        chunk_ids: List[str]
    ) -> str  # receipt_id
    
    def append_state_event(
        self,
        task_id: str,
        event: Dict
    ) -> str  # event_id
    
    def list_decisions(
        self,
        task_id: str
    ) -> List[Dict]
```

### 2.2 Task Schema

```json
{
  "task_id": "uuid",
  "objective": "string",
  "scope": {...},
  "owner": "string",
  "current_state": "string",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

### 2.3 ContextBundle Schema

```json
{
  "bundle_id": "uuid",
  "purpose": "string",
  "summary": "string",
  "sources": [...],
  "state_snapshot": {...},
  "decision_digest": {...}
}
```

### 2.4 Failure Policy

| Condition | Default Action |
|---|---|
| task/run not found | deny |
| bundle not found | needs_approval |
| append failed | fail-closed |

---

## 3. ProtocolsAdapter

**Target**: `agent-protocols`

**Operation Mode**: read-only

**Module**: `src/adapters/protocols_adapter.py`

### 3.1 Required Methods

```python
class ProtocolsAdapter(BaseAdapter):
    def derive_risk_level(
        self,
        capabilities: List[str],
        context: Dict
    ) -> str  # low | medium | high | critical
    
    def derive_required_approvals(
        self,
        risk_level: str,
        capabilities: List[str]
    ) -> List[str]  # approver roles
    
    def resolve_definition_of_done(
        self,
        contract_type: str
    ) -> Dict
    
    def resolve_publish_requirements(
        self,
        target: str
    ) -> Dict
    
    def validate_contract(
        self,
        contract: Dict,
        contract_type: str
    ) -> bool
```

### 3.2 Risk Level Derivation

```
IF production_data_access OR external_secret OR rollback_impossible:
  risk_level = critical
ELSE IF install_deps OR network_access OR read_secrets OR publish_release IN capabilities:
  risk_level = high
ELSE IF write_repo IN capabilities:
  risk_level = medium
ELSE:
  risk_level = low
```

### 3.3 Approval Rules

| risk_level | required_approvals | auto_approved |
|---|---|---|
| low | [] | true |
| medium | [] | true |
| high | [project_lead, security_reviewer] | false |
| critical | [project_lead, security_reviewer, release_manager] | false |

### 3.4 Failure Policy

| Condition | Default Action |
|---|---|
| schema validation failed | needs_approval |
| risk/approval derivation failed | needs_approval |

---

## 4. MemxAdapter

**Target**: `memx-resolver`

**Operation Mode**: read + append-only ack

**Module**: `src/adapters/memx_adapter.py`

### 4.1 Required Methods

```python
class MemxAdapter(BaseAdapter):
    def resolve_docs(
        self,
        task_id: str,
        action: str,
        feature: Optional[str] = None,
        touched_paths: Optional[List[str]] = None
    ) -> Dict  # required_docs, recommended_docs
    
    def get_chunks(
        self,
        doc_id: str,
        chunk_ids: List[str]
    ) -> List[Dict]
    
    def ack_reads(
        self,
        task_id: str,
        doc_id: str,
        version: str,
        chunk_ids: List[str]
    ) -> str  # ack_ref
    
    def stale_check(
        self,
        task_id: str
    ) -> Dict  # stale_items, stale_reasons
    
    def resolve_contract(
        self,
        contract_type: str,
        context: Dict
    ) -> Dict
```

### 4.2 ResolveDocsResult Schema

```json
{
  "required_docs": [
    {"doc_id": "...", "version": "...", "priority": "required"}
  ],
  "recommended_docs": [
    {"doc_id": "...", "version": "...", "priority": "recommended"}
  ],
  "contract_refs": [...],
  "stale_summary": {...}
}
```

### 4.3 StaleCheckResult Schema

```json
{
  "fresh": false,
  "stale_items": [
    {
      "item_type": "doc",
      "item_id": "...",
      "current_version": "v2",
      "expected_version": "v1",
      "stale_reason": "version_changed"
    }
  ],
  "stale_reasons": ["doc_version_changed"]
}
```

### 4.4 Failure Policy

| Condition | Default Action |
|---|---|
| docs not found | stale_blocked |
| stale detection failed | stale_blocked |
| ack failed | needs_approval |

---

## 5. ShipyardAdapter

**Target**: `shipyard-cp`

**Operation Mode**: read + controlled-mutation

**Module**: `src/adapters/shipyard_adapter.py`

### 5.1 Required Methods

```python
class ShipyardAdapter(BaseAdapter):
    def get_pipeline_stage(
        self,
        run_id: str
    ) -> Dict  # stage, status, blocked_reason
    
    def hold_for_review(
        self,
        run_id: str,
        assessment_id: str,
        reason: str
    ) -> str  # hold_id
    
    def resume_from_review(
        self,
        run_id: str,
        hold_id: str,
        resolution: str
    ) -> bool
    
    def get_worker_capabilities(
        self,
        worker_id: str
    ) -> List[str]
    
    def record_transition(
        self,
        run_id: str,
        from_stage: str,
        to_stage: str,
        reason: str
    ) -> str  # transition_id
```

### 5.2 Stage Schema

```json
{
  "run_id": "uuid",
  "stage": "plan | dev | acceptance | integrate | publish",
  "status": "running | blocked | completed | failed",
  "blocked_reason": "optional",
  "started_at": "datetime",
  "expected_next": "optional"
}
```

### 5.3 State Machine

```
plan → dev → acceptance → integrate → publish
            ↓              ↓
         rework ←──── blocked
            ↑              ↑
            └───────────── publish_pending_approval
```

### 5.4 Failure Policy

| Condition | Default Action |
|---|---|
| hold failed | high-risk → deny |
| resume failed | fail-closed |
| stage not found | needs_approval |

---

## 6. WorkflowAdapter

**Target**: `workflow-cookbook`

**Operation Mode**: read-only

**Module**: `src/adapters/workflow_adapter.py`

### 6.1 Required Methods

```python
class WorkflowAdapter(BaseAdapter):
    def get_birdseye_caps(
        self,
        repo_path: str
    ) -> Dict  # capabilities, roles
    
    def get_acceptance_index(
        self,
        task_id: str
    ) -> Dict  # acceptance_criteria
    
    def get_governance_policy(
        self,
        policy_id: str
    ) -> Dict
    
    def get_evidence_report(
        self,
        task_id: str,
        stage: str
    ) -> Dict  # required_evidence, collected_evidence
    
    def get_codemap(
        self,
        scope: str
    ) -> Dict
```

### 6.2 EvidenceReport Schema (workflow-cookbook generate_evidence_report.py準拠)

workflow-cookbookの`tools/ci/generate_evidence_report.py`実装に準拠。

```json
{
  "acceptances": [
    {
      "id": "AC-20260410-01",
      "task_id": "TASK-001",
      "status": "active"
    }
  ],
  "evidences": [
    {
      "id": "EV-001",
      "task_id": "TASK-001",
      "model": "claude-opus-4"
    }
  ],
  "linked": [
    {
      "acceptance_id": "AC-20260410-01",
      "task_id": "TASK-001",
      "evidence_id": "EV-001",
      "evidence_file": ".workflow-cache/evidence.json"
    }
  ],
  "unlinked_acceptances": [],
  "unlinked_evidences": []
}
```

**EvidenceReport Fields**:
| Field | Type | Description |
|---|---|---|
| `acceptances` | array[AcceptanceSummary] | Acceptance records from docs/acceptance/ |
| `evidences` | array[EvidenceSummary] | Evidence files from .workflow-cache/ |
| `linked` | array[dict] | Linked acceptance-evidence pairs by task_id |
| `unlinked_acceptances` | array[AcceptanceSummary] | Acceptances without matching evidence |
| `unlinked_evidences` | array[EvidenceSummary] | Evidences without matching acceptance |

**参照**: workflow-cookbook `tools/ci/generate_evidence_report.py` lines 26-49
```

### 6.3 Failure Policy

| Condition | Default Action |
|---|---|
| evidence not found | needs_approval |
| acceptance not found | needs_approval |
| governance policy not found | needs_approval |

---

## 7. Adapter Registry

```python
class AdapterRegistry:
    adapters: Dict[str, BaseAdapter]
    
    def register(self, adapter: BaseAdapter) -> None
    def get(self, name: str) -> Optional[BaseAdapter]
    def get_all(self) -> List[BaseAdapter]
    def health_check_all(self) -> Dict[str, bool]
    def get_by_capability(self, capability: str) -> List[BaseAdapter]
```

---

## 8. Adapter Initialization Sequence

```python
def initialize_adapters(config: Dict) -> AdapterRegistry:
    registry = AdapterRegistry()
    
    # Gatefield (required for state-space gate)
    if config.get("adapters", {}).get("gatefield", {}).get("enabled"):
        registry.register(GatefieldAdapter(config["adapters"]["gatefield"]))
    
    # Taskstate (required for task/run)
    if config.get("adapters", {}).get("taskstate", {}).get("enabled"):
        registry.register(TaskstateAdapter(config["adapters"]["taskstate"]))
    
    # Protocols (required for risk/approval)
    if config.get("adapters", {}).get("protocols", {}).get("enabled"):
        registry.register(ProtocolsAdapter(config["adapters"]["protocols"]))
    
    # Memx (required for docs/stale)
    if config.get("adapters", {}).get("memx", {}).get("enabled"):
        registry.register(MemxAdapter(config["adapters"]["memx"]))
    
    # Shipyard (required for stage/publish)
    if config.get("adapters", {}).get("shipyard", {}).get("enabled"):
        registry.register(ShipyardAdapter(config["adapters"]["shipyard"]))
    
    # Workflow (required for evidence/acceptance)
    if config.get("adapters", {}).get("workflow", {}).get("enabled"):
        registry.register(WorkflowAdapter(config["adapters"]["workflow"]))
    
    return registry
```

---

## 9. Health Check Contract

```python
def health_check_all(self) -> Dict[str, bool]:
    """Return health status for all registered adapters."""
    result = {}
    for name, adapter in self.adapters.items():
        try:
            result[name] = adapter.health_check()
        except Exception:
            result[name] = False
    return result
```

---

## 10. 実API照合表 (Adapter-to-Repo API Mapping)

agent-state-gate adapter契約と既存repo実APIの対応表。P0実装前にgolden fixture作成必須。

### 10.1 GatefieldAdapter API Mapping

| agent-state-gate Method | agent-gatefield API | Method | Args | Return | Auth |
|---|---|---|---|---|---|
| `evaluate(artifact, trace, rule_results)` | `POST /v1/evaluate` | HTTP | `artifact_id`, `run_id`, `artifact_ref`, `diff_hash` | DecisionPacket (DATA_TYPES_SPEC:779-1141) | API Key header |
| `enqueue_review(review_item)` | `POST /v1/review/items` | HTTP | `decision_id`, `run_id`, `severity`, `top_factors` | `review_id` (UUID) | API Key header |
| `export_audit(run_id)` | `GET /v1/audit/{run_id}` | HTTP | `run_id` (path) | `audit_events` (array) | API Key header |
| `get_decision_packet(decision_id)` | `GET /v1/decisions/{decision_id}` | HTTP | `decision_id` (path) | DecisionPacket | API Key header |
| `get_state_vector(run_id)` | `GET /v1/state-vectors/{run_id}` | HTTP | `run_id` (path) | StateVector (DATA_TYPES_SPEC:19-448) | API Key header |
| `health_check()` | `GET /v1/health` | HTTP | - | `{status: "ok"}` | None |

**言語境界**: Python HTTP client (requests/aiohttp)
**同期/非同期**: 同期推奨 (5s timeout)
**エラー型**: `GatefieldUnavailableError`, `DecisionNotFoundError`

### 10.2 TaskstateAdapter API Mapping

| agent-state-gate Method | agent-taskstate API | Method | Args | Return | Auth |
|---|---|---|---|---|---|
| `get_task(task_id)` | `agent-taskstate task show --task <id>` | CLI | `task_id` | Task JSON (MVP spec:79-95) | Local FS |
| `get_run(run_id)` | `agent-taskstate run show --run <id>` | CLI | `run_id` | Run JSON (MVP spec:147-158) | Local FS |
| `get_context_bundle(bundle_id)` | `agent-taskstate context show --bundle <id>` | CLI | `bundle_id` | ContextBundle (MVP spec:159-173) | Local FS |
| `record_read_receipt(task_id, doc_id, version, chunk_ids)` | `agent-taskstate state append --task <id> --event read_receipt` | CLI | `task_id`, `event` JSON | `receipt_id` (typed_ref) | Local FS |
| `append_state_event(task_id, event)` | `agent-taskstate state append --task <id> --event <json>` | CLI | `task_id`, `event` | `event_id` (typed_ref) | Local FS |
| `list_decisions(task_id)` | `agent-taskstate decision list --task <id>` | CLI | `task_id` | Decision[] (MVP spec:115-129) | Local FS |
| `health_check()` | `agent-taskstate task list --limit 1` | CLI | - | `{ok: true}` | Local FS |

**言語境界**: Python subprocess call
**同期/非同期**: 同期 (3s timeout)
**エラー型**: `TaskNotFoundError`, `RunNotFoundError`, `BundleNotFoundError`

**typed_ref format**: agent-taskstate src/typed_ref.py準拠 (4-segment canonical)
```python
# Example outputs
task_id: "agent-taskstate:task:local:01HXYZ..."
run_id: "agent-taskstate:run:local:01HABC..."
decision_id: "agent-taskstate:decision:local:01HDEF..."
receipt_id: "agent-taskstate:read_receipt:local:01HGHI..."
```

### 10.3 ProtocolsAdapter API Mapping

| agent-state-gate Method | agent-protocols Schema | Method | Args | Return | Auth |
|---|---|---|---|---|---|
| `derive_risk_level(capabilities, context)` | `schemas/risk_levels.yaml` + logic | File read | `capabilities[]` | `risk_level: "low|medium|high|critical"` | None |
| `derive_required_approvals(risk_level, capabilities)` | `schemas/approval_matrix.yaml` | File read | `risk_level`, `capabilities[]` | `approver_roles[]` | None |
| `resolve_definition_of_done(contract_type)` | `schemas/contract_types/{type}.schema.json` | File read | `contract_type` | `DefinitionOfDone` schema | None |
| `resolve_publish_requirements(target)` | `schemas/publish_gates/{target}.schema.json` | File read | `target` | `PublishGate` schema | None |
| `validate_contract(contract, contract_type)` | `src/validation/validate.py` | Python import | `contract`, `type` | `valid: bool` | None |
| `health_check()` | `ls schemas/` | File check | - | `exists: bool` | None |

**言語境界**: Python YAML/JSON file read
**同期/非同期**: 同期 (local FS)
**エラー型**: `SchemaValidationError`, `ContractNotFoundError`

**Risk Derivation Logic** (adapter_contract.md:233-243):
```python
# Logic implementation
if "production_data_access" in capabilities or "external_secret" in capabilities:
    return "critical"
elif any(c in capabilities for c in ["install_deps", "network_access", "read_secrets", "publish_release"]):
    return "high"
elif "write_repo" in capabilities:
    return "medium"
else:
    return "low"
```

### 10.4 MemxAdapter API Mapping

| agent-state-gate Method | memx-resolver API | Method | Args | Return | Auth |
|---|---|---|---|---|---|
| `resolve_docs(task_id, action, feature, touched_paths)` | `docs:resolve` CLI/API | HTTP/CLI | `task_id`, `action`, `feature?`, `paths?` | ResolveDocsResult (interfaces.md:309-322) | API Key |
| `get_chunks(doc_id, chunk_ids)` | `chunks:get` CLI/API | HTTP/CLI | `doc_id`, `chunk_ids[]` | Chunk[] | API Key |
| `ack_reads(task_id, doc_id, version, chunk_ids)` | `reads:ack` CLI/API | HTTP/CLI | `task_id`, `doc_id`, `version`, `chunk_ids[]` | `ack_ref` (typed_ref) | API Key |
| `stale_check(task_id)` | `docs:stale-check` CLI/API | HTTP/CLI | `task_id` | StaleCheckResult (interfaces.md:325-340) | API Key |
| `resolve_contract(contract_type, context)` | `contracts:resolve` CLI/API | HTTP/CLI | `contract_type`, `context` | ContractRef | API Key |
| `health_check()` | `GET /v1/health` | HTTP | - | `{status: "ok"}` | None |

**言語境界**: Python HTTP client OR Go subprocess
**同期/非同期**: 同期 (3s timeout)
**エラー型**: `DocsNotFoundError`, `StaleCheckError`, `AckFailedError`

**typed_ref format**: memx-resolver interfaces.md準拠 (4-segment canonical)
```python
# Example outputs
doc_ref: "memx:doc:local:01HDOC..."
chunk_ref: "memx:chunk:local:01HCHK..."
ack_ref: "memx:ack:local:01HACK..."
contract_ref: "memx:contract:local:01HCNT..."
```

### 10.5 ShipyardAdapter API Mapping

| agent-state-gate Method | shipyard-cp API | Method | Args | Return | Auth |
|---|---|---|---|---|---|
| `get_pipeline_stage(run_id)` | `GET /v1/tasks/{task_id}` | HTTP | `task_id` (path) | Stage (api-contract:397-408) | JWT |
| `hold_for_review(run_id, assessment_id, reason)` | `POST /v1/tasks/{task_id}/transitions` | HTTP | `task_id`, `transition` body | `hold_id` (UUID) | JWT |
| `resume_from_review(run_id, hold_id, resolution)` | `POST /v1/tasks/{task_id}/transitions` | HTTP | `task_id`, `transition` body | `success: bool` | JWT |
| `get_worker_capabilities(worker_id)` | `GET /v1/workers/{worker_id}/caps` | HTTP | `worker_id` (path) | `capabilities[]` | JWT |
| `record_transition(run_id, from_stage, to_stage, reason)` | `POST /v1/tasks/{task_id}/transitions` | HTTP | `task_id`, `transition` body | `transition_id` (UUID) | JWT |
| `health_check()` | `GET /v1/health` | HTTP | - | `{status: "ok"}` | None |

**言語境界**: TypeScript HTTP API
**同期/非同期**: 同期 (5s timeout)
**エラー型**: `StageNotFoundError`, `TransitionNotAllowedError`, `WorkerNotFoundError`

**Stage State Machine** (api-contract.md:222-278):
```
queued → planning → planned → developing → dev_completed → accepting → accepted → integrating → integrated → publishing → published
         ↓              ↓              ↓                 ↓
      blocked      rework_required  blocked           blocked
```

### 10.6 WorkflowAdapter API Mapping

| agent-state-gate Method | workflow-cookbook API | Method | Args | Return | Auth |
|---|---|---|---|---|---|
| `get_birdseye_caps(repo_path)` | `tools/codemap/update --radius 2` | CLI | `repo_path` | `birdseye/index.json` | None |
| `get_acceptance_index(task_id)` | `tools/ci/generate_acceptance_index.py --task <id>` | CLI | `task_id` | AcceptanceIndex (docs/acceptance/) | None |
| `get_governance_policy(policy_id)` | `governance/policy.yaml` read | File read | `policy_id` | GovernancePolicy schema | None |
| `get_evidence_report(task_id, stage)` | `tools/ci/generate_evidence_report.py --task <id>` | CLI | `task_id`, `stage?` | EvidenceReport (adapter_contract:547-580) | None |
| `get_codemap(scope)` | `tools/codemap/update --scope <scope>` | CLI | `scope` | Codemap JSON | None |
| `health_check()` | `ls docs/acceptance/` | File check | - | `exists: bool` | None |

**言語境界**: Python CLI subprocess + YAML/JSON file read
**同步/非同期**: 同期 (2s timeout)
**エラー型**: `EvidenceNotFoundError`, `AcceptanceNotFoundError`, `PolicyNotFoundError`

---

## 11. Adapter Error Type Mapping

| agent-state-gate Error | HTTP Code | Retryable | Source Adapter |
|---|---:|---:|---|
| `AdapterUnavailableError` | 503 | Yes | All adapters |
| `TaskNotFoundError` | 404 | No | taskstate_adapter |
| `RunNotFoundError` | 404 | No | taskstate_adapter |
| `DecisionNotFoundError` | 404 | No | gatefield_adapter |
| `DocsNotFoundError` | 404 | No | memx_adapter |
| `StageNotFoundError` | 404 | No | shipyard_adapter |
| `SchemaValidationError` | 400 | No | protocols_adapter |
| `StaleCheckError` | 500 | Conditional | memx_adapter |
| `TransitionNotAllowedError` | 409 | No | shipyard_adapter |
| `EvidenceNotFoundError` | 404 | No | workflow_adapter |
| `AssessmentError` | 500 | No | assessment_engine (internal) |

---

## 12. Version History

| Version | Date | Changes |
|---|---|---|
| 0.2.0 | 2026-04-26 | 実API照合表追加 (Section 10-11), 6 adapter API mapping, Error type mapping |
| 0.1.0 | 2026-04-26 | Initial adapter contract specification |
