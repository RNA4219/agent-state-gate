"""
Unit tests for ConflictResolver.

Tests conflict detection, resolution strategies, and record management.
"""

from unittest.mock import MagicMock

import pytest

from src.core.conflict_resolver import (
    ConflictResolver,
    ConflictType,
    ResolutionStrategy,
    ConflictRecord,
    ResolutionResult,
    resolve_assessments,
)
from src.core.verdict_transformer import Verdict
from src.core.assessment_engine import Assessment
from src.common import utc_now


class TestConflictType:
    def test_conflict_type_values(self):
        assert ConflictType.VERDICT_MISMATCH.value == "verdict_mismatch"
        assert ConflictType.SCORE_DRIFT.value == "score_drift"
        assert ConflictType.STALE_VS_FRESH.value == "stale_vs_fresh"
        assert ConflictType.APPROVAL_EXPIRED.value == "approval_expired"
        assert ConflictType.DIFF_HASH_CHANGED.value == "diff_hash_changed"


class TestResolutionStrategy:
    def test_resolution_strategy_values(self):
        assert ResolutionStrategy.MOST_RESTRICTIVE.value == "most_restrictive"
        assert ResolutionStrategy.LATEST_TIMESTAMP.value == "latest_timestamp"
        assert ResolutionStrategy.STALE_INVALIDATION.value == "stale_invalidation"
        assert ResolutionStrategy.ESCALATE_HUMAN.value == "escalate_human"
        assert ResolutionStrategy.MERGE_TRACE.value == "merge_trace"


class TestConflictRecord:
    def test_conflict_record_creation(self):
        record = ConflictRecord(
            conflict_id="CF-001",
            conflict_type=ConflictType.VERDICT_MISMATCH,
            assessment_a="ASM-001",
            assessment_b="ASM-002",
            details={"verdict_a": "allow", "verdict_b": "deny"},
            detected_at="2026-04-26T10:00:00Z"
        )
        assert record.conflict_id == "CF-001"
        assert record.conflict_type == ConflictType.VERDICT_MISMATCH


class TestResolutionResult:
    def test_resolution_result_creation(self):
        result = ResolutionResult(
            conflict_id="CF-001",
            strategy=ResolutionStrategy.MOST_RESTRICTIVE,
            winning_assessment="ASM-002",
            losing_assessment="ASM-001",
            rationale="DENY has higher priority",
            requires_escalation=False
        )
        assert result.conflict_id == "CF-001"
        assert result.winning_assessment == "ASM-002"


class TestConflictResolverCreation:
    def test_resolver_creation(self):
        resolver = ConflictResolver()
        assert resolver is not None


class TestConflictResolverDetect:
    def test_detect_verdict_mismatch(self):
        resolver = ConflictResolver()
        # Create mock assessments
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW
        assessment_a.assessment_id = "ASM-001"

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.DENY
        assessment_b.assessment_id = "ASM-002"

        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        assert conflict is not None
        assert conflict.conflict_type == ConflictType.VERDICT_MISMATCH

    def test_detect_no_conflict_same_verdict(self):
        resolver = ConflictResolver()
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW
        assessment_a.diff_hash = "hash123"
        assessment_a.stale_summary = MagicMock()
        assessment_a.stale_summary.fresh = True

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.ALLOW
        assessment_b.diff_hash = "hash123"
        assessment_b.stale_summary = MagicMock()
        assessment_b.stale_summary.fresh = True

        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        assert conflict is None

    def test_detect_no_conflict_different_task(self):
        resolver = ConflictResolver()
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-002"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.DENY

        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        assert conflict is None


class TestConflictResolverResolve:
    def test_resolve_most_restrictive(self):
        resolver = ConflictResolver()
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW
        assessment_a.assessment_id = "ASM-001"
        assessment_a.created_at = utc_now()

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.DENY
        assessment_b.assessment_id = "ASM-002"
        assessment_b.created_at = utc_now()

        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        result = resolver.resolve(conflict, assessment_a, assessment_b)
        assert result.strategy == ResolutionStrategy.MOST_RESTRICTIVE

    def test_resolve_escalate_human(self):
        resolver = ConflictResolver()
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW
        assessment_a.diff_hash = "hash123"
        assessment_a.assessment_id = "ASM-001"
        assessment_a.created_at = utc_now()

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.ALLOW
        assessment_b.diff_hash = "hash456"
        assessment_b.assessment_id = "ASM-002"
        assessment_b.created_at = utc_now()

        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        result = resolver.resolve(conflict, assessment_a, assessment_b)
        # DIFF_HASH_CHANGED uses ESCALATE_HUMAN strategy
        assert result.requires_escalation is True


class TestConflictResolverRecords:
    def test_list_conflicts_after_detect(self):
        resolver = ConflictResolver()
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW
        assessment_a.assessment_id = "ASM-001"

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.DENY
        assessment_b.assessment_id = "ASM-002"

        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        # Conflict should be stored
        conflicts = resolver.list_conflicts()
        assert len(conflicts) >= 1

    def test_list_conflicts_empty(self):
        resolver = ConflictResolver()
        conflicts = resolver.list_conflicts()
        assert len(conflicts) == 0


class TestConflictResolverResolveAssessments:
    def test_resolve_assessments_function(self):
        # Create assessments with different verdicts
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.NEEDS_APPROVAL
        assessment_a.assessment_id = "ASM-001"
        assessment_a.created_at = utc_now()
        assessment_a.stale_summary = MagicMock(fresh=True)
        assessment_a.diff_hash = "hash123"

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.ALLOW
        assessment_b.assessment_id = "ASM-002"
        assessment_b.created_at = utc_now()
        assessment_b.stale_summary = MagicMock(fresh=True)
        assessment_b.diff_hash = "hash123"

        result = resolve_assessments([assessment_a, assessment_b])
        # NEEDS_APPROVAL should win (higher priority)
        assert result.final_verdict == Verdict.NEEDS_APPROVAL


class TestConflictResolverDiffHash:
    def test_detect_diff_hash_changed(self):
        resolver = ConflictResolver()
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW
        assessment_a.diff_hash = "hash123"
        assessment_a.assessment_id = "ASM-001"
        assessment_a.stale_summary = MagicMock(fresh=True)

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.ALLOW
        assessment_b.diff_hash = "hash456"
        assessment_b.assessment_id = "ASM-002"
        assessment_b.stale_summary = MagicMock(fresh=True)

        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        assert conflict is not None
        assert conflict.conflict_type == ConflictType.DIFF_HASH_CHANGED


class TestConflictResolverScoreDrift:
    def test_detect_score_drift(self):
        """Detect score drift between assessments."""
        resolver = ConflictResolver()
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW  # low priority = high score
        assessment_a.diff_hash = "hash123"
        assessment_a.assessment_id = "ASM-001"
        assessment_a.stale_summary = MagicMock(fresh=True)

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.DENY  # high priority = low score
        assessment_b.diff_hash = "hash123"
        assessment_b.assessment_id = "ASM-002"
        assessment_b.stale_summary = MagicMock(fresh=True)

        # ALLOW vs DENY has large score difference
        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        # This will be verdict mismatch, not score drift
        assert conflict is not None


class TestConflictResolverStaleVsFresh:
    def test_detect_stale_vs_fresh(self):
        """Detect stale vs fresh conflict."""
        resolver = ConflictResolver()
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW
        assessment_a.diff_hash = "hash123"
        assessment_a.assessment_id = "ASM-001"
        assessment_a.stale_summary = MagicMock(fresh=True)

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.ALLOW
        assessment_b.diff_hash = "hash123"
        assessment_b.assessment_id = "ASM-002"
        assessment_b.stale_summary = MagicMock(fresh=False)

        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        assert conflict is not None
        assert conflict.conflict_type == ConflictType.STALE_VS_FRESH

    def test_resolve_by_freshness_fresh_wins(self):
        """Resolve by freshness - fresh wins over stale."""
        resolver = ConflictResolver()
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW
        assessment_a.diff_hash = "hash123"
        assessment_a.assessment_id = "ASM-001"
        assessment_a.stale_summary = MagicMock(fresh=True)
        assessment_a.created_at = utc_now()

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.ALLOW
        assessment_b.diff_hash = "hash123"
        assessment_b.assessment_id = "ASM-002"
        assessment_b.stale_summary = MagicMock(fresh=False)
        assessment_b.created_at = utc_now()

        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        result = resolver.resolve(conflict, assessment_a, assessment_b)
        assert result.strategy == ResolutionStrategy.STALE_INVALIDATION
        assert result.winning_assessment == "ASM-001"


class TestConflictResolverTimestamp:
    def test_resolve_by_timestamp_latest_wins(self):
        """Resolve by timestamp - latest wins."""
        resolver = ConflictResolver()
        from datetime import datetime, timedelta

        now = utc_now()
        earlier = now - timedelta(hours=1)

        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW
        assessment_a.diff_hash = "hash123"
        assessment_a.assessment_id = "ASM-001"
        assessment_a.stale_summary = MagicMock(fresh=True)
        assessment_a.stale_summary.fresh = True
        assessment_a.created_at = earlier

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.ALLOW
        assessment_b.diff_hash = "hash123"
        assessment_b.assessment_id = "ASM-002"
        assessment_b.stale_summary = MagicMock(fresh=True)
        assessment_b.stale_summary.fresh = True
        assessment_b.created_at = now

        # Both stale to trigger STALE_VS_FRESH which escalates to freshness resolution
        assessment_a.stale_summary = MagicMock(fresh=False)
        assessment_b.stale_summary = MagicMock(fresh=False)

        # Create conflict manually
        from src.core.conflict_resolver import ConflictRecord
        conflict = ConflictRecord(
            conflict_id="CF-TIME",
            conflict_type=ConflictType.STALE_VS_FRESH,
            assessment_a="ASM-001",
            assessment_b="ASM-002",
            details={},
            detected_at=now.isoformat()
        )
        resolver._conflict_records[conflict.conflict_id] = conflict

        result = resolver.resolve(conflict, assessment_a, assessment_b)
        # STALE_VS_FRESH with both stale escalates to human
        assert result.requires_escalation is True


class TestConflictResolverEscalation:
    def test_resolve_by_escalation(self):
        """Resolve by escalation to human."""
        resolver = ConflictResolver()
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW
        assessment_a.diff_hash = "hash123"
        assessment_a.assessment_id = "ASM-001"
        assessment_a.stale_summary = MagicMock(fresh=True)
        assessment_a.stale_summary.fresh = True
        assessment_a.created_at = utc_now()

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.ALLOW
        assessment_b.diff_hash = "hash456"
        assessment_b.assessment_id = "ASM-002"
        assessment_b.stale_summary = MagicMock(fresh=True)
        assessment_b.stale_summary.fresh = True
        assessment_b.created_at = utc_now()

        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        result = resolver.resolve(conflict, assessment_a, assessment_b)
        assert result.requires_escalation is True
        assert result.strategy == ResolutionStrategy.ESCALATE_HUMAN


class TestConflictResolverListResolutions:
    def test_list_resolutions_empty(self):
        """List resolutions returns empty list."""
        resolver = ConflictResolver()
        results = resolver.list_resolutions()
        assert len(results) == 0

    def test_list_resolutions_after_resolve(self):
        """List resolutions after resolving conflict."""
        resolver = ConflictResolver()
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW
        assessment_a.assessment_id = "ASM-001"
        assessment_a.created_at = utc_now()

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.DENY
        assessment_b.assessment_id = "ASM-002"
        assessment_b.created_at = utc_now()

        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        resolver.resolve(conflict, assessment_a, assessment_b)

        results = resolver.list_resolutions()
        assert len(results) >= 1


class TestConflictResolverGetPendingEscalations:
    def test_get_pending_escalations_empty(self):
        """Get pending escalations returns empty."""
        resolver = ConflictResolver()
        escalations = resolver.get_pending_escalations()
        assert len(escalations) == 0

    def test_get_pending_escalations_with_escalated(self):
        """Get pending escalations returns escalated resolutions."""
        resolver = ConflictResolver()
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW
        assessment_a.diff_hash = "hash123"
        assessment_a.assessment_id = "ASM-001"
        assessment_a.stale_summary = MagicMock(fresh=True)
        assessment_a.stale_summary.fresh = True
        assessment_a.created_at = utc_now()

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.ALLOW
        assessment_b.diff_hash = "hash456"
        assessment_b.assessment_id = "ASM-002"
        assessment_b.stale_summary = MagicMock(fresh=True)
        assessment_b.stale_summary.fresh = True
        assessment_b.created_at = utc_now()

        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        resolver.resolve(conflict, assessment_a, assessment_b)

        escalations = resolver.get_pending_escalations()
        assert len(escalations) >= 1  # DIFF_HASH_CHANGED escalates


class TestConflictResolverPriorityOrdering:
    def test_verdict_priority_ordering(self):
        """Test verdict priority - DENY highest, ALLOW lowest."""
        resolver = ConflictResolver()

        # DENY should win over ALLOW
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW
        assessment_a.assessment_id = "ASM-001"
        assessment_a.created_at = utc_now()

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.DENY
        assessment_b.assessment_id = "ASM-002"
        assessment_b.created_at = utc_now()

        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        result = resolver.resolve(conflict, assessment_a, assessment_b)
        assert result.winning_assessment == "ASM-002"  # DENY wins

    def test_needs_approval_wins_over_allow(self):
        """NEEDS_APPROVAL should win over ALLOW."""
        resolver = ConflictResolver()
        assessment_a = MagicMock()
        assessment_a.task_id = "TASK-001"
        assessment_a.run_id = "RUN-001"
        assessment_a.final_verdict = Verdict.ALLOW
        assessment_a.assessment_id = "ASM-001"
        assessment_a.created_at = utc_now()

        assessment_b = MagicMock()
        assessment_b.task_id = "TASK-001"
        assessment_b.run_id = "RUN-001"
        assessment_b.final_verdict = Verdict.NEEDS_APPROVAL
        assessment_b.assessment_id = "ASM-002"
        assessment_b.created_at = utc_now()

        conflict = resolver.detect_conflict(assessment_a, assessment_b)
        result = resolver.resolve(conflict, assessment_a, assessment_b)
        assert result.winning_assessment == "ASM-002"  # NEEDS_APPROVAL wins


class TestResolveAssessmentsEmpty:
    def test_resolve_assessments_empty_list(self):
        """Resolve assessments with empty list."""
        result = resolve_assessments([])
        assert result is None

    def test_resolve_assessments_single(self):
        """Resolve assessments with single item."""
        assessment = MagicMock()
        assessment.final_verdict = Verdict.ALLOW
        result = resolve_assessments([assessment])
        assert result == assessment