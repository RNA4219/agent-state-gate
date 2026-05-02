"""
Human Attention Queue

Routes items requiring human review with SLA management and escalation.
Implements ownership context checks and reviewer routing.

Reference: architecture.md HumanQueueItem (lines 395-442)
Reference: architecture.md SLA Enforcement Logic
Reference: gate_config.yaml human_queue.sla
"""

from datetime import datetime, timedelta

from src.common import (
    generate_queue_item_id,
    utc_now,
)
from src.core import Assessment

from .types import (
    DEFAULT_ESCALATION_CHAIN,
    DEFAULT_REVIEWER_ROLES,
    DEFAULT_SLA_DEFINITIONS,
    HumanQueueItem,
    OwnershipContext,
    QueueStatus,
    ReasonCode,
    Resolution,
    SLAAction,
    SLADefinition,
    Severity,
)


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

    def list_items(self) -> list[HumanQueueItem]:
        """List all items in queue."""
        return list(self._queue.values())


__all__ = ["HumanAttentionQueue"]