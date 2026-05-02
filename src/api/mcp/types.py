"""
MCP Surface Types

Result dataclasses for MCP Surface API.
Reference: api_spec.md MCP Surface API
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.core import StaleSummary, Verdict


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
    items: list  # HumanQueueItem type
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


__all__ = [
    "DocRef",
    "ContractRef",
    "RecallResult",
    "EvidenceRef",
    "ApprovalRef",
    "EvaluateResult",
    "StaleItem",
    "StaleCheckResult",
    "StateGateAssessResult",
    "SLAStatus",
    "AttentionListResult",
    "ReplayContextResult",
]