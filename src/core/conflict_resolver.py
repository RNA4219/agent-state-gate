"""
ConflictResolver Module

Handles decision conflicts when multiple assessments or decisions conflict.
Provides priority-based resolution and escalation rules.

Reference: architecture.md (衝突解決 logic)
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..common import generate_id, iso_timestamp
from .assessment import Assessment
from .verdict_transformer import get_verdict_priority


class ConflictType(StrEnum):
    """Types of decision conflicts."""
    VERDICT_MISMATCH = "verdict_mismatch"  # Different verdicts for same task
    SCORE_DRIFT = "score_drift"  # Score changed significantly
    STALE_VS_FRESH = "stale_vs_fresh"  # Stale vs fresh assessment conflict
    APPROVAL_EXPIRED = "approval_expired"  # Approval expired between assessments
    DIFF_HASH_CHANGED = "diff_hash_changed"  # Diff changed between assessments


class ResolutionStrategy(StrEnum):
    """Conflict resolution strategies."""
    MOST_RESTRICTIVE = "most_restrictive"  # Take higher priority (more restrictive) verdict
    LATEST_TIMESTAMP = "latest_timestamp"  # Use latest assessment
    STALE_INVALIDATION = "stale_invalidation"  # Invalidate stale assessment
    ESCALATE_HUMAN = "escalate_human"  # Require human review
    MERGE_TRACE = "merge_trace"  # Merge causal traces


@dataclass
class ConflictRecord:
    """Record of detected conflict."""
    conflict_id: str
    conflict_type: ConflictType
    assessment_a: str  # Assessment ref A
    assessment_b: str  # Assessment ref B
    details: dict[str, Any]
    detected_at: str


@dataclass
class ResolutionResult:
    """Result of conflict resolution."""
    conflict_id: str
    strategy: ResolutionStrategy
    winning_assessment: str
    losing_assessment: str
    rationale: str
    requires_escalation: bool
    escalation_reason: str = ""


class ConflictResolver:
    """
    Resolver for assessment conflicts.

    Handles conflicts between multiple assessments for the same task/run
    using priority-based resolution rules.
    """

    def __init__(self):
        self._conflict_records: dict[str, ConflictRecord] = {}
        self._resolution_results: dict[str, ResolutionResult] = []

    def detect_conflict(
        self,
        assessment_a: Assessment,
        assessment_b: Assessment
    ) -> ConflictRecord | None:
        """
        Detect conflict between two assessments.

        Args:
            assessment_a: First assessment.
            assessment_b: Second assessment.

        Returns:
            ConflictRecord if conflict detected, None otherwise.
        """
        # Check if same task/run
        if assessment_a.task_id != assessment_b.task_id:
            return None
        if assessment_a.run_id != assessment_b.run_id:
            return None

        # Check verdict mismatch
        if assessment_a.final_verdict != assessment_b.final_verdict:
            return self._create_conflict(
                ConflictType.VERDICT_MISMATCH,
                assessment_a,
                assessment_b,
                {
                    "verdict_a": assessment_a.final_verdict.value,
                    "verdict_b": assessment_b.final_verdict.value,
                }
            )

        # Check score drift
        score_diff = abs(
            self._get_score(assessment_a) - self._get_score(assessment_b)
        )
        if score_diff > 0.15:  # Threshold for significant drift
            return self._create_conflict(
                ConflictType.SCORE_DRIFT,
                assessment_a,
                assessment_b,
                {
                    "score_a": self._get_score(assessment_a),
                    "score_b": self._get_score(assessment_b),
                    "drift": score_diff,
                }
            )

        # Check stale vs fresh
        if assessment_a.stale_summary.fresh != assessment_b.stale_summary.fresh:
            return self._create_conflict(
                ConflictType.STALE_VS_FRESH,
                assessment_a,
                assessment_b,
                {
                    "fresh_a": assessment_a.stale_summary.fresh,
                    "fresh_b": assessment_b.stale_summary.fresh,
                }
            )

        # Check diff hash changed
        if assessment_a.diff_hash != assessment_b.diff_hash:
            return self._create_conflict(
                ConflictType.DIFF_HASH_CHANGED,
                assessment_a,
                assessment_b,
                {
                    "diff_a": assessment_a.diff_hash,
                    "diff_b": assessment_b.diff_hash,
                }
            )

        return None

    def resolve(
        self,
        conflict: ConflictRecord,
        assessment_a: Assessment,
        assessment_b: Assessment
    ) -> ResolutionResult:
        """
        Resolve conflict between assessments.

        Args:
            conflict: Conflict record.
            assessment_a: First assessment.
            assessment_b: Second assessment.

        Returns:
            ResolutionResult with winning assessment.
        """
        strategy = self._select_strategy(conflict)

        if strategy == ResolutionStrategy.MOST_RESTRICTIVE:
            return self._resolve_by_priority(conflict, assessment_a, assessment_b)

        if strategy == ResolutionStrategy.LATEST_TIMESTAMP:
            return self._resolve_by_timestamp(conflict, assessment_a, assessment_b)

        if strategy == ResolutionStrategy.STALE_INVALIDATION:
            return self._resolve_by_freshness(conflict, assessment_a, assessment_b)

        if strategy == ResolutionStrategy.ESCALATE_HUMAN:
            return self._resolve_by_escalation(conflict, assessment_a, assessment_b)

        # Default to most restrictive
        return self._resolve_by_priority(conflict, assessment_a, assessment_b)

    def _select_strategy(self, conflict: ConflictRecord) -> ResolutionStrategy:
        """Select resolution strategy based on conflict type."""
        strategies = {
            ConflictType.VERDICT_MISMATCH: ResolutionStrategy.MOST_RESTRICTIVE,
            ConflictType.SCORE_DRIFT: ResolutionStrategy.LATEST_TIMESTAMP,
            ConflictType.STALE_VS_FRESH: ResolutionStrategy.STALE_INVALIDATION,
            ConflictType.APPROVAL_EXPIRED: ResolutionStrategy.STALE_INVALIDATION,
            ConflictType.DIFF_HASH_CHANGED: ResolutionStrategy.ESCALATE_HUMAN,
        }
        return strategies.get(conflict.conflict_type, ResolutionStrategy.MOST_RESTRICTIVE)

    def _resolve_by_priority(
        self,
        conflict: ConflictRecord,
        assessment_a: Assessment,
        assessment_b: Assessment
    ) -> ResolutionResult:
        """Resolve by verdict priority (most restrictive wins)."""
        priority_a = get_verdict_priority(assessment_a.final_verdict)
        priority_b = get_verdict_priority(assessment_b.final_verdict)

        if priority_a >= priority_b:
            winner = assessment_a.assessment_id
            loser = assessment_b.assessment_id
        else:
            winner = assessment_b.assessment_id
            loser = assessment_a.assessment_id

        result = ResolutionResult(
            conflict_id=conflict.conflict_id,
            strategy=ResolutionStrategy.MOST_RESTRICTIVE,
            winning_assessment=winner,
            losing_assessment=loser,
            rationale=f"Priority {priority_a} vs {priority_b}: most restrictive wins",
            requires_escalation=False
        )
        self._resolution_results.append(result)
        return result

    def _resolve_by_timestamp(
        self,
        conflict: ConflictRecord,
        assessment_a: Assessment,
        assessment_b: Assessment
    ) -> ResolutionResult:
        """Resolve by latest timestamp."""
        if assessment_a.created_at >= assessment_b.created_at:
            winner = assessment_a.assessment_id
            loser = assessment_b.assessment_id
        else:
            winner = assessment_b.assessment_id
            loser = assessment_a.assessment_id

        result = ResolutionResult(
            conflict_id=conflict.conflict_id,
            strategy=ResolutionStrategy.LATEST_TIMESTAMP,
            winning_assessment=winner,
            losing_assessment=loser,
            rationale=f"Timestamp {assessment_a.created_at} vs {assessment_b.created_at}: latest wins",
            requires_escalation=False
        )
        self._resolution_results.append(result)
        return result

    def _resolve_by_freshness(
        self,
        conflict: ConflictRecord,
        assessment_a: Assessment,
        assessment_b: Assessment
    ) -> ResolutionResult:
        """Resolve by freshness (fresh wins over stale)."""
        if assessment_a.stale_summary.fresh and not assessment_b.stale_summary.fresh:
            winner = assessment_a.assessment_id
            loser = assessment_b.assessment_id
        elif assessment_b.stale_summary.fresh and not assessment_a.stale_summary.fresh:
            winner = assessment_b.assessment_id
            loser = assessment_a.assessment_id
        else:
            # Both fresh or both stale: escalate
            return self._resolve_by_escalation(conflict, assessment_a, assessment_b)

        result = ResolutionResult(
            conflict_id=conflict.conflict_id,
            strategy=ResolutionStrategy.STALE_INVALIDATION,
            winning_assessment=winner,
            losing_assessment=loser,
            rationale="Fresh assessment wins over stale",
            requires_escalation=False
        )
        self._resolution_results.append(result)
        return result

    def _resolve_by_escalation(
        self,
        conflict: ConflictRecord,
        assessment_a: Assessment,
        assessment_b: Assessment
    ) -> ResolutionResult:
        """Resolve by escalation to human review."""
        # Mark both as needing review
        result = ResolutionResult(
            conflict_id=conflict.conflict_id,
            strategy=ResolutionStrategy.ESCALATE_HUMAN,
            winning_assessment="",  # No winner, needs human decision
            losing_assessment="",
            rationale=f"Conflict type {conflict.conflict_type.value} requires human review",
            requires_escalation=True,
            escalation_reason=conflict.conflict_type.value
        )
        self._resolution_results.append(result)
        return result

    def _create_conflict(
        self,
        conflict_type: ConflictType,
        assessment_a: Assessment,
        assessment_b: Assessment,
        details: dict[str, Any]
    ) -> ConflictRecord:
        """Create conflict record."""
        conflict_id = generate_id("CF-")
        conflict = ConflictRecord(
            conflict_id=conflict_id,
            conflict_type=conflict_type,
            assessment_a=assessment_a.assessment_id,
            assessment_b=assessment_b.assessment_id,
            details=details,
            detected_at=self._get_timestamp()
        )
        self._conflict_records[conflict_id] = conflict
        return conflict

    def _get_score(self, assessment: Assessment) -> float:
        """Extract composite score from assessment."""
        # Estimate from verdict priority inverse
        priority = get_verdict_priority(assessment.final_verdict)
        return 1.0 - (priority / 6.0)  # Normalize to 0.0-1.0

    def _get_timestamp(self) -> str:
        """Get current ISO timestamp."""
        return iso_timestamp()

    def list_conflicts(self) -> list[ConflictRecord]:
        """List all detected conflicts."""
        return list(self._conflict_records.values())

    def list_resolutions(self) -> list[ResolutionResult]:
        """List all resolution results."""
        return list(self._resolution_results)

    def get_pending_escalations(self) -> list[ResolutionResult]:
        """List resolutions pending human review."""
        return [r for r in self._resolution_results if r.requires_escalation]


def resolve_assessments(
    assessments: list[Assessment],
    resolver: ConflictResolver | None = None
) -> Assessment | None:
    """
    Resolve multiple assessments for same task/run to single winner.

    Args:
        assessments: List of assessments for same task/run.
        resolver: Optional ConflictResolver instance.

    Returns:
        Winning assessment or None if needs escalation.
    """
    if not assessments:
        return None
    if len(assessments) == 1:
        return assessments[0]

    resolver = resolver or ConflictResolver()

    # Pairwise conflict detection and resolution
    current_winner = assessments[0]

    for i in range(1, len(assessments)):
        next_assessment = assessments[i]

        conflict = resolver.detect_conflict(current_winner, next_assessment)
        if conflict:
            result = resolver.resolve(conflict, current_winner, next_assessment)

            if result.requires_escalation:
                return None  # Needs human review

            # Get winning assessment
            winner_id = result.winning_assessment
            if winner_id == current_winner.assessment_id:
                continue
            elif winner_id == next_assessment.assessment_id:
                current_winner = next_assessment
            else:
                # No winner, escalation needed
                return None

    return current_winner
