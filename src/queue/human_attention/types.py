"""
Human Attention Queue Types

Enums, dataclasses, and default configurations for human attention queue.

Reference: architecture.md HumanQueueItem (lines 395-442)
Reference: architecture.md SLA Enforcement Logic
Reference: gate_config.yaml human_queue.sla
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum


class QueueStatus(StrEnum):
    """Human queue item status."""
    PENDING = "pending"
    TAKEN = "taken"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class ReasonCode(StrEnum):
    """Reason for human attention."""
    TABOO = "taboo"                      # Taboo proximity threshold exceeded
    REJECTED_CASE = "rejected_case"      # Similar to rejected exemplar
    HIGH_RISK = "high_risk"              # Risk level critical/high
    STALE = "stale"                      # Stale docs/approvals detected
    APPROVAL_MISSING = "approval_missing"  # Required approvals missing
    EVIDENCE_GAP = "evidence_gap"        # Evidence strength insufficient
    OBLIGATION_UNFULFILLED = "obligation_unfulfilled"  # Obligations not met
    UNCERTAINTY_HIGH = "uncertainty_high"  # Decision uncertainty high
    WAIVER_REQUIRED = "waiver_required"  # Waiver needed for policy bypass


class Severity(StrEnum):
    """Item severity level."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Resolution(StrEnum):
    """Resolution decision for queue item."""
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    REVOKED = "revoked"
    INFO_REQUESTED = "info_requested"


class SLAAction(StrEnum):
    """SLA enforcement action."""
    NONE = "none"
    ESCALATE_ACK_TIMEOUT = "escalate_ack_timeout"
    ESCALATE_DECISION_TIMEOUT = "escalate_decision_timeout"
    AUTO_BLOCK = "auto_block"
    GOVERNANCE_BOARD_NOTIFY = "governance_board_notify"


@dataclass
class SLADefinition:
    """SLA time limits for severity level."""
    ack_minutes: int | None = None     # Acknowledgement deadline
    decision_minutes: int | None = None  # Decision deadline
    ack_hours: int | None = None        # Alternative hour format
    decision_hours: int | None = None   # Alternative hour format
    backlog: bool = False                  # No deadline, backlog queue

    def get_ack_deadline(self, created_at: datetime) -> datetime | None:
        """Calculate acknowledgement deadline."""
        if self.ack_minutes:
            return created_at + timedelta(minutes=self.ack_minutes)
        if self.ack_hours:
            return created_at + timedelta(hours=self.ack_hours)
        return None

    def get_decision_deadline(self, created_at: datetime) -> datetime | None:
        """Calculate decision deadline."""
        if self.decision_minutes:
            return created_at + timedelta(minutes=self.decision_minutes)
        if self.decision_hours:
            return created_at + timedelta(hours=self.decision_hours)
        return None


@dataclass
class OwnershipContext:
    """
    Owner permission context for cross-owner approval checks.

    Reference: architecture.md lines 425-442
    """
    owner_id: str
    owner_role: str
    permission_scope: list[str] = field(default_factory=list)
    data_classification_access: list[str] = field(default_factory=list)
    service_scope: list[str] = field(default_factory=list)
    approval_authority_level: int = 1  # 1-4 hierarchy level


@dataclass
class HumanQueueItem:
    """
    Item in human attention queue requiring review.

    Reference: architecture.md lines 395-422
    """
    item_id: str
    assessment_id: str
    task_id: str
    run_id: str

    reason_code: ReasonCode
    severity: Severity
    required_role: str  # security_reviewer | project_lead | release_manager | governance_board

    # Ownership Context
    task_owner: str
    task_owner_type: str  # human | agent | system
    ownership_context: OwnershipContext

    due_at: datetime
    sla: SLADefinition

    suggested_actions: list[str] = field(default_factory=list)
    exemplar_refs: list[str] = field(default_factory=list)

    status: QueueStatus = QueueStatus.PENDING
    assigned_to: str | None = None
    taken_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution: Resolution | None = None
    resolution_comment: str = ""

    created_at: datetime = field(default_factory=lambda: datetime.utcnow())

    # Escalation tracking
    escalation_level: int = 0
    escalated_to: str | None = None
    escalation_reason: str = ""

    # Waiver tracking
    waiver_id: str | None = None
    waiver_status: str = ""


# Default SLA definitions (from gate_config.yaml)
DEFAULT_SLA_DEFINITIONS: dict[str, SLADefinition] = {
    "critical": SLADefinition(ack_minutes=15, decision_minutes=60),
    "high": SLADefinition(ack_minutes=60, decision_minutes=240),
    "medium": SLADefinition(ack_hours=8, decision_hours=24),
    "low": SLADefinition(backlog=True),
}

# Escalation chain (from gate_config.yaml)
DEFAULT_ESCALATION_CHAIN: dict[str, list[str]] = {
    "critical": ["project_lead", "governance_board"],
    "high": ["project_lead"],
    "medium": ["owner"],
}

# Reviewer role mapping (from gate_config.yaml)
DEFAULT_REVIEWER_ROLES: dict[str, str] = {
    "security": "security_reviewer",
    "release": "release_manager",
    "architecture": "project_lead",
    "acceptance": "qa_owner",
}


__all__ = [
    "QueueStatus",
    "ReasonCode",
    "Severity",
    "Resolution",
    "SLAAction",
    "SLADefinition",
    "OwnershipContext",
    "HumanQueueItem",
    "DEFAULT_SLA_DEFINITIONS",
    "DEFAULT_ESCALATION_CHAIN",
    "DEFAULT_REVIEWER_ROLES",
]