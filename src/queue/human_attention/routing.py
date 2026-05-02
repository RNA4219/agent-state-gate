"""
Human Attention Queue Routing

Functions for routing assessments to human attention queue.

Reference: architecture.md HumanQueueItem (lines 395-442)
"""

from src.core import Assessment, Verdict

from .types import (
    HumanQueueItem,
    ReasonCode,
    Severity,
)
from .queue import HumanAttentionQueue


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


__all__ = ["route_assessment_to_queue"]