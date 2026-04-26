"""
Human Attention Queue Module

Routes items requiring human review with SLA management and escalation.
Implements ownership context checks and reviewer routing.

Reference: architecture.md HumanQueueItem (lines 395-442)
Reference: architecture.md SLA Enforcement Logic
Reference: gate_config.yaml human_queue.sla
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from ..common import (
    generate_queue_item_id,
    utc_now,
)
from ..core import Assessment, Verdict


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

    created_at: datetime = field(default_factory=utc_now)

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


class HumanAttentionQueue:
    """
    Human attention queue for review routing.

    Capabilities:
    - Add items to queue
    - Route to appropriate reviewers
    - Track SLA deadlines
    - Enforce escalation
    - Track resolution
    """

    def __init__(
        self,
        sla_definitions: dict[str, SLADefinition] | None = None,
        escalation_chain: dict[str, list[str]] | None = None,
        reviewer_roles: dict[str, str] | None = None
    ):
        self._sla_definitions = sla_definitions or DEFAULT_SLA_DEFINITIONS
        self._escalation_chain = escalation_chain or DEFAULT_ESCALATION_CHAIN
        self._reviewer_roles = reviewer_roles or DEFAULT_REVIEWER_ROLES
        self._queue: dict[str, HumanQueueItem] = {}

    def add_item(
        self,
        assessment: Assessment,
        reason_code: ReasonCode,
        severity: Severity,
        required_role: str,
        task_owner: str,
        task_owner_type: str = "human",
        ownership_context: OwnershipContext | None = None
    ) -> HumanQueueItem:
        """
        Add item to human attention queue.

        Args:
            assessment: Assessment triggering review.
            reason_code: Reason for attention.
            severity: Severity level.
            required_role: Required reviewer role.
            task_owner: Task owner identifier.
            task_owner_type: Owner type (human/agent/system).
            ownership_context: Owner permission context.

        Returns:
            HumanQueueItem added to queue.
        """
        item_id = self._generate_item_id()
        sla = self._sla_definitions.get(severity.value, DEFAULT_SLA_DEFINITIONS["medium"])

        created_at = utc_now()
        due_at = sla.get_decision_deadline(created_at) or created_at + timedelta(hours=24)

        suggested_actions = self._generate_suggested_actions(reason_code, assessment)
        exemplar_refs = self._extract_exemplar_refs(assessment)

        item = HumanQueueItem(
            item_id=item_id,
            assessment_id=assessment.assessment_id,
            task_id=assessment.task_id,
            run_id=assessment.run_id,
            reason_code=reason_code,
            severity=severity,
            required_role=required_role,
            task_owner=task_owner,
            task_owner_type=task_owner_type,
            ownership_context=ownership_context or OwnershipContext(
                owner_id=task_owner,
                owner_role="unknown",
                permission_scope=["read"],
                approval_authority_level=1
            ),
            due_at=due_at,
            sla=sla,
            suggested_actions=suggested_actions,
            exemplar_refs=exemplar_refs,
        )

        self._queue[item_id] = item
        return item

    def take_item(
        self,
        item_id: str,
        reviewer: str
    ) -> HumanQueueItem | None:
        """
        Mark item as taken by reviewer.

        Args:
            item_id: Item identifier.
            reviewer: Reviewer identifier.

        Returns:
            Updated HumanQueueItem or None if not found.
        """
        item = self._queue.get(item_id)
        if not item:
            return None

        if item.status != QueueStatus.PENDING and item.status != QueueStatus.ESCALATED:
            return None

        item.status = QueueStatus.TAKEN
        item.assigned_to = reviewer
        item.taken_at = utc_now()

        return item

    def resolve_item(
        self,
        item_id: str,
        resolution: Resolution,
        comment: str = ""
    ) -> HumanQueueItem | None:
        """
        Resolve queue item.

        Args:
            item_id: Item identifier.
            resolution: Resolution decision.
            comment: Resolution comment.

        Returns:
            Updated HumanQueueItem or None.
        """
        item = self._queue.get(item_id)
        if not item:
            return None

        if item.status != QueueStatus.TAKEN:
            return None

        item.status = QueueStatus.RESOLVED
        item.resolution = resolution
        item.resolution_comment = comment
        item.resolved_at = utc_now()

        return item

    def escalate_item(
        self,
        item_id: str,
        reason: str = ""
    ) -> HumanQueueItem | None:
        """
        Escalate item to next level.

        Args:
            item_id: Item identifier.
            reason: Escalation reason.

        Returns:
            Updated HumanQueueItem or None.
        """
        item = self._queue.get(item_id)
        if not item:
            return None

        escalation_chain = self._escalation_chain.get(item.severity.value, [])
        next_level = item.escalation_level + 1

        if next_level >= len(escalation_chain):
            # Max escalation reached
            item.status = QueueStatus.ESCALATED
            item.escalation_level = next_level
            item.escalated_to = "governance_board"
            item.escalation_reason = reason or "max_escalation_reached"
            return item

        item.status = QueueStatus.ESCALATED
        item.escalation_level = next_level
        item.escalated_to = escalation_chain[next_level]
        item.escalation_reason = reason

        return item

    def enforce_sla(self, now: datetime | None = None) -> list[HumanQueueItem]:
        """
        Enforce SLA deadlines on all pending items.

        Args:
            now: Current timestamp (default: now).

        Returns:
            List of items with SLA action applied.

        Reference: architecture.md SLA Enforcement Logic
        """
        now = now or utc_now()
        updated_items = []

        for item in self._queue.values():
            if item.status == QueueStatus.RESOLVED:
                continue

            action = self._check_sla_action(item, now)
            if action != SLAAction.NONE:
                updated_item = self._apply_sla_action(item, action, now)
                updated_items.append(updated_item)

        return updated_items

    def _check_sla_action(self, item: HumanQueueItem, now: datetime) -> SLAAction:
        """
        Check SLA action for item.

        Reference: architecture.md lines 396-440 (SLA Enforcement Logic)
        """
        created_at = item.created_at

        # Check ack deadline (pending items)
        if item.status == QueueStatus.PENDING:
            ack_deadline = item.sla.get_ack_deadline(created_at)
            if ack_deadline and now > ack_deadline:
                if item.severity == Severity.CRITICAL:
                    return SLAAction.ESCALATE_ACK_TIMEOUT
                return SLAAction.ESCALATE_ACK_TIMEOUT

        # Check decision deadline (taken items)
        if item.status == QueueStatus.TAKEN:
            decision_deadline = item.sla.get_decision_deadline(created_at)
            if decision_deadline and now > decision_deadline:
                if item.severity == Severity.CRITICAL:
                    return SLAAction.AUTO_BLOCK
                if item.severity == Severity.HIGH:
                    return SLAAction.ESCALATE_DECISION_TIMEOUT
                return SLAAction.ESCALATE_DECISION_TIMEOUT

        # Check escalation chain exceeded
        if item.status == QueueStatus.ESCALATED:
            escalation_chain = self._escalation_chain.get(item.severity.value, [])
            if item.escalation_level >= len(escalation_chain):
                return SLAAction.GOVERNANCE_BOARD_NOTIFY

        return SLAAction.NONE

    def _apply_sla_action(
        self,
        item: HumanQueueItem,
        action: SLAAction,
        now: datetime
    ) -> HumanQueueItem:
        """Apply SLA enforcement action."""
        if action == SLAAction.ESCALATE_ACK_TIMEOUT:
            return self.escalate_item(item.item_id, "ack_timeout")
        if action == SLAAction.ESCALATE_DECISION_TIMEOUT:
            return self.escalate_item(item.item_id, "decision_timeout")
        if action == SLAAction.AUTO_BLOCK:
            # Critical timeout → auto block
            item.status = QueueStatus.RESOLVED
            item.resolution = Resolution.REJECTED
            item.resolution_comment = "SLA auto-block: critical timeout"
            item.resolved_at = now
            return item
        if action == SLAAction.GOVERNANCE_BOARD_NOTIFY:
            item.escalated_to = "governance_board"
            item.escalation_reason = "escalation_chain_exceeded"
            return item
        return item

    def get_pending_items(self) -> list[HumanQueueItem]:
        """Get all pending items."""
        return [i for i in self._queue.values() if i.status == QueueStatus.PENDING]

    def get_items_by_reviewer(self, reviewer_role: str) -> list[HumanQueueItem]:
        """Get items assigned to specific reviewer role."""
        return [
            i for i in self._queue.values()
            if i.required_role == reviewer_role and i.status in [QueueStatus.PENDING, QueueStatus.ESCALATED]
        ]

    def get_items_by_task(self, task_id: str) -> list[HumanQueueItem]:
        """Get items for specific task."""
        return [i for i in self._queue.values() if i.task_id == task_id]

    def get_item(self, item_id: str) -> HumanQueueItem | None:
        """Get item by ID."""
        return self._queue.get(item_id)

    def route_to_reviewer(self, item: HumanQueueItem) -> str:
        """
        Determine appropriate reviewer for item.

        Uses ownership context checks and severity routing.
        """
        # Severity-based routing (priority for critical/high)
        if item.severity == Severity.CRITICAL:
            return "governance_board"
        if item.severity == Severity.HIGH:
            if item.reason_code == ReasonCode.TABOO:
                return self._reviewer_roles.get("security", "security_reviewer")
            return self._reviewer_roles.get("architecture", "project_lead")

        # Check ownership context for cross-owner routing
        if self._requires_cross_owner_review(item):
            return self._get_cross_owner_reviewer(item)

        return item.required_role

    def _requires_cross_owner_review(self, item: HumanQueueItem) -> bool:
        """Check if cross-owner review required."""
        ctx = item.ownership_context

        # Required role different from owner role
        if item.required_role != ctx.owner_role:
            return True

        # Admin permission requires higher authority
        if "admin" in ctx.permission_scope:
            return True

        return False

    def _get_cross_owner_reviewer(self, item: HumanQueueItem) -> str:
        """Get cross-owner reviewer."""
        # Escalate to project_lead for cross-owner
        return self._reviewer_roles.get("architecture", "project_lead")

    def _generate_item_id(self) -> str:
        """Generate unique item ID."""
        return generate_queue_item_id()

    def _generate_suggested_actions(
        self,
        reason_code: ReasonCode,
        assessment: Assessment
    ) -> list[str]:
        """Generate suggested actions for reviewer."""
        actions = []

        if reason_code == ReasonCode.TABOO:
            actions.append("Review taboo proximity factors")
            actions.append("Consider code modification to reduce proximity")
        elif reason_code == ReasonCode.STALE:
            actions.append("Update stale docs to current versions")
            actions.append("Re-run assessment after refresh")
        elif reason_code == ReasonCode.APPROVAL_MISSING:
            actions.append("Obtain missing approvals")
            actions.append(f"Approvers needed: {', '.join(assessment.approval_summary.missing_approvals)}")
        elif reason_code == ReasonCode.EVIDENCE_GAP:
            actions.append("Add evidence items")
            actions.append(f"Target strength: 0.85, current: {assessment.evidence_summary.evidence_strength:.2%}")
        elif reason_code == ReasonCode.OBLIGATION_UNFULFILLED:
            actions.append("Fulfill unmet obligations")
            if assessment.obligation_summary.has_critical_unfulfilled:
                actions.append("WARNING: Critical obligation unfulfilled")

        return actions

    def _extract_exemplar_refs(self, assessment: Assessment) -> list[str]:
        """Extract exemplar references from assessment."""
        # Placeholder: would come from DecisionPacket
        return []


def route_assessment_to_queue(
    assessment: Assessment,
    queue: HumanAttentionQueue,
    task_owner: str,
    task_owner_type: str = "human"
) -> HumanQueueItem | None:
    """
    Route assessment to human attention queue if needed.

    Args:
        assessment: Assessment to route.
        queue: Human attention queue.
        task_owner: Task owner.
        task_owner_type: Owner type.

    Returns:
        HumanQueueItem if routed, None if not needed.
    """
    if assessment.final_verdict == Verdict.ALLOW:
        return None  # No review needed

    # Determine reason code and severity
    reason_code, severity, required_role = _derive_queue_params(assessment)

    # Add to queue
    return queue.add_item(
        assessment=assessment,
        reason_code=reason_code,
        severity=severity,
        required_role=required_role,
        task_owner=task_owner,
        task_owner_type=task_owner_type
    )


def _derive_queue_params(assessment: Assessment) -> tuple:
    """Derive queue parameters from assessment."""
    verdict = assessment.final_verdict

    # Critical verdicts
    if verdict == Verdict.DENY:
        return ReasonCode.HIGH_RISK, Severity.CRITICAL, "governance_board"

    if verdict == Verdict.STALE_BLOCKED:
        return ReasonCode.STALE, Severity.HIGH, "project_lead"

    if verdict == Verdict.REQUIRE_HUMAN:
        # Check reason from verdict_reason
        reason_str = assessment.verdict_reason.lower()
        if "taboo" in reason_str:
            return ReasonCode.TABOO, Severity.HIGH, "security_reviewer"
        if "uncertainty" in reason_str:
            return ReasonCode.UNCERTAINTY_HIGH, Severity.MEDIUM, "project_lead"
        if "obligation" in reason_str:
            return ReasonCode.OBLIGATION_UNFULFILLED, Severity.HIGH, "project_lead"
        return ReasonCode.HIGH_RISK, Severity.HIGH, "project_lead"

    if verdict == Verdict.NEEDS_APPROVAL:
        if assessment.approval_summary.missing_approvals:
            return ReasonCode.APPROVAL_MISSING, Severity.MEDIUM, "project_lead"
        if assessment.evidence_summary.evidence_strength < 0.85:
            return ReasonCode.EVIDENCE_GAP, Severity.MEDIUM, "qa_owner"
        return ReasonCode.APPROVAL_MISSING, Severity.MEDIUM, "project_lead"

    if verdict == Verdict.REVISE:
        return ReasonCode.HIGH_RISK, Severity.LOW, "owner"

    # Default
    return ReasonCode.HIGH_RISK, Severity.MEDIUM, "project_lead"
