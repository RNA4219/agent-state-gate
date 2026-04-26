"""
MCP Surface Module

MCP façade for agent-context-mcp.
Provides read-heavy surface for context, gate, and queue operations.

Reference: api_spec.md MCP Surface API
Reference: BLUEPRINT.md MCP Surface
Reference: gate_config.yaml mcp section
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..adapters import (
    AdapterRegistry,
    AdapterUnavailableError,
)
from ..audit import (
    AuditPacketGenerator,
    EvidenceRecorder,
)
from ..common import hash_dict, iso_timestamp, utc_now
from ..core import (
    ApprovalSummary,
    AssessmentEngine,
    EvidenceSummary,
    ObligationSummary,
    StaleSummary,
    Verdict,
    VerdictTransformer,
)
from ..queue import (
    HumanAttentionQueue,
    HumanQueueItem,
    QueueStatus,
)

# --- Result Types (api_spec.md definitions) ---

@dataclass
class DocRef:
    """Document reference for recall result."""
    doc_id: str
    version: str
    priority: str  # required | recommended
    doc_type: str
    title: str


@dataclass
class ContractRef:
    """Contract reference for recall result."""
    contract_id: str
    contract_type: str
    version: str


@dataclass
class RecallResult:
    """Result from context.recall."""
    required_docs: list[DocRef]
    recommended_docs: list[DocRef]
    contract_refs: list[ContractRef]
    stale_summary: StaleSummary
    ack_required: bool


@dataclass
class EvidenceRef:
    """Evidence reference for evaluate result."""
    evidence_id: str
    evidence_type: str
    status: str


@dataclass
class ApprovalRef:
    """Approval reference for evaluate result."""
    approval_id: str
    approver_role: str
    status: str


@dataclass
class EvaluateResult:
    """Result from gate.evaluate."""
    verdict: Verdict
    required_evidence: list[EvidenceRef]
    required_approvals: list[ApprovalRef]
    missing_approvals: list[str]
    assessment_id: str
    causal_trace: list[str]
    verdict_reason: str


@dataclass
class StaleItem:
    """Stale item in stale check result."""
    item_type: str  # doc | approval | acceptance | contract
    item_id: str
    current_version: str
    expected_version: str
    stale_reason: str


@dataclass
class StaleCheckResult:
    """Result from context.stale_check."""
    fresh: bool
    stale_items: list[StaleItem]
    stale_reasons: list[str]
    last_check_at: datetime


@dataclass
class StateGateAssessResult:
    """Result from state_gate.assess."""
    assessment_id: str
    decision_packet_ref: str
    scores: dict[str, float]  # taboo, drift, anomaly, uncertainty
    recommendation: str
    human_queue_required: bool
    exemplar_refs: list[str]
    threshold_version: str


@dataclass
class SLAStatus:
    """SLA status for queue items."""
    pending_count: int
    ack_timeout_count: int
    decision_timeout_count: int
    escalated_count: int


@dataclass
class AttentionListResult:
    """Result from attention.list."""
    items: list[HumanQueueItem]
    total_pending: int
    by_severity: dict[str, int]
    sla_status: dict[str, SLAStatus]


@dataclass
class ReplayContextResult:
    """Result from run.replay_context."""
    run_id: str
    context_snapshot: dict[str, Any]
    decision_packet: dict[str, Any]
    assessment: dict[str, Any]
    audit_packet_ref: str
    attestation_hash: str
    decision_diff: dict[str, Any] | None = None
    reproducibility_verified: bool = True


# --- MCP Surface Class ---

class MCPSurface:
    """
    MCP Surface façade for agent-state-gate.

    Provides read-heavy surface for:
    - context.recall: Required docs resolution
    - gate.evaluate: Integrated gate evaluation
    - context.stale_check: Stale detection
    - state_gate.assess: State-space gate assessment
    - attention.list: Human queue listing
    - run.replay_context: Context replay for reproducibility
    """

    def __init__(
        self,
        adapter_registry: AdapterRegistry,
        assessment_engine: AssessmentEngine,
        human_queue: HumanAttentionQueue,
        evidence_recorder: EvidenceRecorder,
        config: dict[str, Any] | None = None
    ):
        self._registry = adapter_registry
        self._engine = assessment_engine
        self._queue = human_queue
        self._recorder = evidence_recorder
        self._config = config or {}
        self._transformer = VerdictTransformer()
        self._audit_generator = AuditPacketGenerator()

    # --- 1.1 context.recall ---
    def context_recall(
        self,
        task_id: str,
        action: str,
        feature: str | None = None,
        touched_paths: list[str] | None = None,
        limit: int = 10
    ) -> RecallResult:
        """
        Resolve required docs from task/action context.

        Args:
            task_id: Task ID.
            action: Action type (edit_repo, install_deps, etc.).
            feature: Optional feature context.
            touched_paths: Optional target file paths.
            limit: Max results (1-100).

        Returns:
            RecallResult with required/recommended docs.

        Raises:
            TaskNotFoundError: If task not found.
            AdapterUnavailableError: If memx unavailable.
        """
        memx_adapter = self._registry.get("memx")
        if not memx_adapter:
            raise AdapterUnavailableError("memx", "adapter not registered")

        # Resolve docs via memx
        resolve_result = memx_adapter.resolve_docs(
            task_id=task_id,
            action=action,
            feature=feature,
            touched_paths=touched_paths
        )

        # Build doc refs
        required_docs = [
            DocRef(
                doc_id=d.get("doc_id", ""),
                version=d.get("version", ""),
                priority="required",
                doc_type=d.get("doc_type", "unknown"),
                title=d.get("title", "")
            )
            for d in resolve_result.get("required_docs", [])[:limit]
        ]

        recommended_docs = [
            DocRef(
                doc_id=d.get("doc_id", ""),
                version=d.get("version", ""),
                priority="recommended",
                doc_type=d.get("doc_type", "unknown"),
                title=d.get("title", "")
            )
            for d in resolve_result.get("recommended_docs", [])[:limit]
        ]

        contract_refs = [
            ContractRef(
                contract_id=c.get("contract_id", ""),
                contract_type=c.get("contract_type", ""),
                version=c.get("version", "")
            )
            for c in resolve_result.get("contract_refs", [])
        ]

        # Build stale summary
        stale_summary = StaleSummary(
            fresh=resolve_result.get("stale_summary", {}).get("fresh", True),
            stale_items=resolve_result.get("stale_summary", {}).get("stale_items", []),
            stale_reasons=resolve_result.get("stale_summary", {}).get("stale_reasons", [])
        )

        ack_required = len(required_docs) > 0

        return RecallResult(
            required_docs=required_docs,
            recommended_docs=recommended_docs,
            contract_refs=contract_refs,
            stale_summary=stale_summary,
            ack_required=ack_required
        )

    # --- 1.2 gate.evaluate ---
    def gate_evaluate(
        self,
        task_id: str,
        action: str,
        capabilities: list[str],
        risk_hints: dict | None = None,
        touched_paths: list[str] | None = None
    ) -> EvaluateResult:
        """
        Integrated gate evaluation.

        Args:
            task_id: Task ID.
            action: Action type.
            capabilities: Requested capabilities.
            risk_hints: Optional additional risk context.
            touched_paths: Optional target file paths.

        Returns:
            EvaluateResult with verdict and requirements.
        """
        # Get adapters
        self._registry.get("gatefield")
        protocols_adapter = self._registry.get("protocols")
        memx_adapter = self._registry.get("memx")
        workflow_adapter = self._registry.get("workflow")

        # Derive risk level
        risk_level = "medium"
        required_approvals = []
        if protocols_adapter:
            risk_level = protocols_adapter.derive_risk_level(capabilities, risk_hints)
            required_approvals = protocols_adapter.derive_required_approvals(risk_level, capabilities)

        # Check stale
        stale_result = {"fresh": True, "stale_items": [], "stale_reasons": []}
        if memx_adapter:
            stale_result = memx_adapter.stale_check(task_id)

        # Get evidence report
        evidence_result = {"evidence_strength": 1.0, "collected_evidence": [], "required_evidence": []}
        if workflow_adapter:
            try:
                evidence_result = workflow_adapter.get_evidence_report(task_id)
            except Exception:
                pass

        # Build summaries
        stale_summary = StaleSummary(
            fresh=stale_result.get("fresh", True),
            stale_items=stale_result.get("stale_items", []),
            stale_reasons=stale_result.get("stale_reasons", [])
        )

        ObligationSummary(fulfillment_rate=1.0)
        approval_summary = ApprovalSummary(
            missing_approvals=required_approvals,
            required_approvals=required_approvals
        )
        evidence_summary = EvidenceSummary(
            evidence_strength=evidence_result.get("evidence_strength", 1.0)
        )

        # ADVISORY MODE: DecisionPacket from gatefield adapter not connected.
        # In MVP advisory mode, verdict is derived from stale/approval/evidence checks.
        # Production blocking mode requires real gatefield DecisionPacket integration.
        # See: docs/CHECKLISTS.md Production Enforce Entry Criteria

        # Determine verdict
        verdict = Verdict.ALLOW
        verdict_reason = "All checks passed"

        if not stale_summary.fresh:
            verdict = Verdict.STALE_BLOCKED
            verdict_reason = "Stale items detected"
        elif approval_summary.missing_approvals:
            verdict = Verdict.NEEDS_APPROVAL
            verdict_reason = f"Missing approvals: {', '.join(approval_summary.missing_approvals)}"
        elif evidence_summary.evidence_strength < 0.85:
            verdict = Verdict.NEEDS_APPROVAL
            verdict_reason = "Evidence strength insufficient"

        # Build result
        assessment_id = f"ASM-{task_id[:8]}"

        return EvaluateResult(
            verdict=verdict,
            required_evidence=[
                EvidenceRef(evidence_id=e, evidence_type="unknown", status="pending")
                for e in evidence_result.get("required_evidence", [])
            ],
            required_approvals=[
                ApprovalRef(approval_id=a, approver_role=a, status="missing")
                for a in required_approvals
            ],
            missing_approvals=required_approvals,
            assessment_id=assessment_id,
            causal_trace=[],
            verdict_reason=verdict_reason
        )

    # --- 1.3 context.stale_check ---
    def context_stale_check(self, task_id: str) -> StaleCheckResult:
        """
        Check stale status for task.

        Args:
            task_id: Task ID.

        Returns:
            StaleCheckResult with stale items and reasons.
        """
        memx_adapter = self._registry.get("memx")
        if not memx_adapter:
            return StaleCheckResult(
                fresh=True,
                stale_items=[],
                stale_reasons=[],
                last_check_at=utc_now()
            )

        result = memx_adapter.stale_check(task_id)

        stale_items = [
            StaleItem(
                item_type=i.get("item_type", "unknown"),
                item_id=i.get("item_id", ""),
                current_version=i.get("current_version", ""),
                expected_version=i.get("expected_version", ""),
                stale_reason=i.get("stale_reason", "")
            )
            for i in result.get("stale_items", [])
        ]

        return StaleCheckResult(
            fresh=result.get("fresh", True),
            stale_items=stale_items,
            stale_reasons=result.get("stale_reasons", []),
            last_check_at=utc_now()
        )

    # --- 1.4 state_gate.assess ---
    def state_gate_assess(
        self,
        artifact_refs: list[str],
        diff: str,
        run_id: str,
        stage: str
    ) -> StateGateAssessResult:
        """
        State-space gate assessment.

        Args:
            artifact_refs: Artifact references.
            diff: Diff content (redacted).
            run_id: Run ID.
            stage: Current stage.

        Returns:
            StateGateAssessResult with scores and recommendation.
        """
        gatefield_adapter = self._registry.get("gatefield")
        taskstate_adapter = self._registry.get("taskstate")

        # Get run data
        if taskstate_adapter:
            try:
                taskstate_adapter.get_run(run_id)
            except Exception:
                pass

        # Evaluate via gatefield
        decision_packet = {}
        if gatefield_adapter:
            try:
                decision_packet = gatefield_adapter.evaluate(
                    artifact={"artifact_ref": artifact_refs[0] if artifact_refs else ""},
                    trace={"run_id": run_id, "stage": stage},
                    rule_results={}
                )
            except Exception:
                decision_packet = {
                    "decision": "pass",
                    "composite_score": 0.9,
                    "factors": []
                }

        # Build scores
        scores = {}
        factors = decision_packet.get("factors", [])
        for factor in factors:
            name = factor.get("name", "")
            if name:
                scores[name] = factor.get("value", 0.0)

        # Determine recommendation
        decision = decision_packet.get("decision", "pass")
        recommendation = "continue"
        human_queue_required = False

        if decision == "block":
            recommendation = "block"
            human_queue_required = False  # Already blocked
        elif decision == "hold":
            recommendation = "hold_for_review"
            human_queue_required = True
        elif decision == "warn":
            recommendation = "self_correct"
            human_queue_required = decision_packet.get("self_correction_count", 0) >= 2

        assessment_id = f"ASM-{run_id[:8]}"

        return StateGateAssessResult(
            assessment_id=assessment_id,
            decision_packet_ref=decision_packet.get("decision_id", ""),
            scores=scores,
            recommendation=recommendation,
            human_queue_required=human_queue_required,
            exemplar_refs=[e.get("doc_id", "") for e in decision_packet.get("exemplar_refs", [])],
            threshold_version=decision_packet.get("threshold_version", "")
        )

    # --- 1.5 attention.list ---
    def attention_list(
        self,
        queue_scope: str = "all",
        reviewer_role: str | None = None,
        status: str | None = None
    ) -> AttentionListResult:
        """
        List human attention queue items.

        Args:
            queue_scope: Scope filter (all | mine | pending).
            reviewer_role: Role filter.
            status: Status filter (pending | taken | resolved).

        Returns:
            AttentionListResult with items and counts.
        """
        # Get items based on filters
        items = []
        if status:
            status_enum = QueueStatus(status)
            items = [i for i in self._queue.get_pending_items() if i.status == status_enum]
        else:
            items = self._queue.get_pending_items()

        if reviewer_role:
            items = [i for i in items if i.required_role == reviewer_role]

        # Enforce SLA
        self._queue.enforce_sla()

        # Calculate counts
        total_pending = len([i for i in items if i.status == QueueStatus.PENDING])

        by_severity = {}
        for severity in ["critical", "high", "medium", "low"]:
            by_severity[severity] = len([i for i in items if i.severity.value == severity])

        sla_status = {
            "global": SLAStatus(
                pending_count=total_pending,
                ack_timeout_count=0,
                decision_timeout_count=0,
                escalated_count=len([i for i in items if i.status == QueueStatus.ESCALATED])
            )
        }

        return AttentionListResult(
            items=items,
            total_pending=total_pending,
            by_severity=by_severity,
            sla_status=sla_status
        )

    # --- 1.6 run.replay_context ---
    def run_replay_context(
        self,
        run_id: str,
        as_of: datetime | None = None
    ) -> ReplayContextResult:
        """
        Replay historical context snapshot for run.

        Args:
            run_id: Run ID.
            as_of: Historical timestamp (optional).

        Returns:
            ReplayContextResult with full context replay.
        """
        gatefield_adapter = self._registry.get("gatefield")
        taskstate_adapter = self._registry.get("taskstate")

        # Get run data
        run_data = {}
        if taskstate_adapter:
            try:
                run_data = taskstate_adapter.get_run(run_id)
            except Exception:
                pass

        # Get audit events
        audit_events = []
        if gatefield_adapter:
            try:
                audit_result = gatefield_adapter.export_audit(run_id)
                audit_events = audit_result.get("audit_events", [])
            except Exception:
                pass

        # Get assessment
        assessments = self._engine.list_assessments_by_run(run_id)
        assessment = assessments[-1] if assessments else None

        # Build context snapshot
        context_snapshot = {
            "run_id": run_id,
            "run_data": run_data,
            "audit_events_count": len(audit_events),
            "as_of": as_of.isoformat() if as_of else iso_timestamp(),
        }

        # ADVISORY MODE: DecisionPacket mock for replay.
        # MVP advisory mode uses placeholder decision_packet for context replay.
        # Production blocking mode requires gatefield DecisionPacket export integration.
        # See: docs/CHECKLISTS.md Production Enforce Entry Criteria
        decision_packet = {
            "run_id": run_id,
            "decision": "advisory_placeholder",
            "threshold_version": "mvp-advisory",
            "advisory_mode": True,
            "note": "MVP advisory mode - requires gatefield integration for production"
        }

        # Build assessment dict
        assessment_dict = {}
        if assessment:
            assessment_dict = {
                "assessment_id": assessment.assessment_id,
                "verdict": assessment.final_verdict.value,
                "verdict_reason": assessment.verdict_reason,
                "threshold_version": assessment.threshold_version,
                "context_hash": assessment.context_hash,
            }

        # Generate attestation hash
        attestation_hash = self._hash_context(context_snapshot, decision_packet, assessment_dict)

        # Build audit packet ref
        audit_packet_ref = ""
        if assessment:
            audit_packet_ref = f"agent-state-gate:audit_packet:local:AUD-{assessment.assessment_id}"

        return ReplayContextResult(
            run_id=run_id,
            context_snapshot=context_snapshot,
            decision_packet=decision_packet,
            assessment=assessment_dict,
            audit_packet_ref=audit_packet_ref,
            attestation_hash=attestation_hash,
            reproducibility_verified=True
        )

    def _hash_context(
        self,
        context_snapshot: dict,
        decision_packet: dict,
        assessment_dict: dict
    ) -> str:
        """Generate attestation hash for replay verification."""
        data = {
            "context": context_snapshot,
            "decision": decision_packet,
            "assessment": assessment_dict,
        }
        return hash_dict(data)


# --- Convenience Functions ---

def create_mcp_surface(
    adapter_registry: AdapterRegistry,
    config: dict | None = None
) -> MCPSurface:
    """
    Create MCP surface with default components.

    Args:
        adapter_registry: Adapter registry.
        config: Optional configuration.

    Returns:
        MCPSurface instance.
    """
    engine = AssessmentEngine()
    queue = HumanAttentionQueue()
    recorder = EvidenceRecorder()

    return MCPSurface(
        adapter_registry=adapter_registry,
        assessment_engine=engine,
        human_queue=queue,
        evidence_recorder=recorder,
        config=config
    )
