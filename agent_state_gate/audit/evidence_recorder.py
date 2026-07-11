"""
Evidence Recorder Module

Records evidence for append-only evidence store with task binding.
Links evidence to acceptance criteria and tracks collection.

Reference: BLUEPRINT.md evidence.record
Reference: workflow-cookbook generate_evidence_report.py
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from ..common import (
    generate_evidence_id,
    hash_dict,
    iso_timestamp,
    utc_now,
)


class EvidenceType(StrEnum):
    """Evidence type classification."""
    TEST_RESULT = "test_result"
    REVIEW_COMMENT = "review_comment"
    CI_LOG = "ci_log"
    ARTIFACT = "artifact"
    SCREENSHOT = "screenshot"
    METRIC = "metric"
    DOCUMENT = "document"
    APPROVAL = "approval"
    RUN_TRACE = "run_trace"
    ASSESSMENT_OUTPUT = "assessment_output"


class EvidenceStatus(StrEnum):
    """Evidence collection status."""
    COLLECTED = "collected"
    PENDING = "pending"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class EvidenceItem:
    """
    Evidence item in append-only store.

    Records evidence with task binding and acceptance linking.
    """
    evidence_id: str
    evidence_type: EvidenceType
    task_id: str

    # Content (required)
    content_ref: str          # Reference to evidence content (file, URL, etc.)
    content_hash: str         # Hash of evidence content
    content_summary: str      # Brief summary of evidence

    # Collection metadata (required)
    collected_by: str         # Collector identifier (agent, human, system)
    collection_method: str    # How evidence was collected (auto, manual, ci)

    # Optional fields (with defaults)
    run_id: str | None = None

    # Acceptance linking
    acceptance_id: str | None = None
    acceptance_criteria_ref: str | None = None

    collected_at: datetime = field(default_factory=utc_now)

    # Status
    status: EvidenceStatus = EvidenceStatus.COLLECTED

    # Retention
    retention_days: int = 90
    expires_at: datetime | None = None

    # Trace correlation
    trace_id: str | None = None
    assessment_id: str | None = None

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)


class EvidenceRecorder:
    """
    Recorder for append-only evidence store.

    Capabilities:
    - Record evidence items
    - Link to acceptance criteria
    - Track collection status
    - Query by task/acceptance
    """

    def __init__(self, default_retention_days: int = 90):
        self._default_retention_days = default_retention_days
        self._evidence_store: dict[str, EvidenceItem] = {}

    def record(
        self,
        evidence_type: EvidenceType,
        task_id: str,
        content_ref: str,
        content_hash: str,
        content_summary: str,
        collected_by: str,
        run_id: str | None = None,
        acceptance_id: str | None = None,
        collection_method: str = "auto",
        trace_id: str | None = None,
        assessment_id: str | None = None,
        metadata: dict[str, Any] | None = None
    ) -> EvidenceItem:
        """
        Record evidence item.

        Args:
            evidence_type: Type of evidence.
            task_id: Task binding.
            content_ref: Reference to evidence content.
            content_hash: Hash of content.
            content_summary: Brief summary.
            collected_by: Collector identifier.
            run_id: Optional run binding.
            acceptance_id: Optional acceptance linking.
            collection_method: Collection method.
            trace_id: Optional trace correlation.
            assessment_id: Optional assessment correlation.
            metadata: Optional additional metadata.

        Returns:
            EvidenceItem instance.
        """
        evidence_id = self._generate_evidence_id()

        expires_at = utc_now() + timedelta(days=self._default_retention_days)

        item = EvidenceItem(
            evidence_id=evidence_id,
            evidence_type=evidence_type,
            task_id=task_id,
            run_id=run_id,
            content_ref=content_ref,
            content_hash=content_hash,
            content_summary=content_summary,
            acceptance_id=acceptance_id,
            collected_by=collected_by,
            collection_method=collection_method,
            trace_id=trace_id,
            assessment_id=assessment_id,
            retention_days=self._default_retention_days,
            expires_at=expires_at,
            metadata=metadata or {},
        )

        self._evidence_store[evidence_id] = item
        return item

    def record_test_result(
        self,
        task_id: str,
        test_name: str,
        test_result: str,  # passed | failed | skipped
        run_id: str | None = None,
        trace_id: str | None = None
    ) -> EvidenceItem:
        """
        Convenience method to record test result evidence.

        Args:
            task_id: Task binding.
            test_name: Test name.
            test_result: Test result (passed/failed/skipped).
            run_id: Optional run binding.
            trace_id: Optional trace correlation.

        Returns:
            EvidenceItem instance.
        """
        content = {
            "test_name": test_name,
            "result": test_result,
            "timestamp": iso_timestamp(),
        }
        content_hash = hash_dict(content)

        return self.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id=task_id,
            content_ref=f"test://{test_name}",
            content_hash=content_hash,
            content_summary=f"Test {test_name}: {test_result}",
            collected_by="ci",
            run_id=run_id,
            collection_method="auto",
            trace_id=trace_id,
            metadata=content
        )

    def record_approval(
        self,
        task_id: str,
        approver: str,
        approval_type: str,
        run_id: str | None = None,
        comment: str = ""
    ) -> EvidenceItem:
        """
        Convenience method to record approval evidence.

        Args:
            task_id: Task binding.
            approver: Approver identifier.
            approval_type: Approval type.
            run_id: Optional run binding.
            comment: Optional approval comment.

        Returns:
            EvidenceItem instance.
        """
        content = {
            "approver": approver,
            "approval_type": approval_type,
            "comment": comment,
            "timestamp": iso_timestamp(),
        }
        content_hash = hash_dict(content)

        return self.record(
            evidence_type=EvidenceType.APPROVAL,
            task_id=task_id,
            content_ref=f"approval://{approver}/{approval_type}",
            content_hash=content_hash,
            content_summary=f"Approval by {approver}: {approval_type}",
            collected_by=approver,
            run_id=run_id,
            collection_method="manual",
            metadata=content
        )

    def link_to_acceptance(
        self,
        evidence_id: str,
        acceptance_id: str,
        acceptance_criteria_ref: str
    ) -> EvidenceItem | None:
        """
        Link evidence to acceptance criteria.

        Args:
            evidence_id: Evidence ID.
            acceptance_id: Acceptance ID.
            acceptance_criteria_ref: Acceptance criteria reference.

        Returns:
            Updated EvidenceItem or None.
        """
        item = self._evidence_store.get(evidence_id)
        if not item:
            return None

        item.acceptance_id = acceptance_id
        item.acceptance_criteria_ref = acceptance_criteria_ref
        return item

    def get_evidence(self, evidence_id: str) -> EvidenceItem | None:
        """Get evidence by ID."""
        return self._evidence_store.get(evidence_id)

    def list_by_task(self, task_id: str) -> list[EvidenceItem]:
        """List evidence for task."""
        return [e for e in self._evidence_store.values() if e.task_id == task_id]

    def list_by_run(self, run_id: str) -> list[EvidenceItem]:
        """List evidence for run."""
        return [e for e in self._evidence_store.values() if e.run_id == run_id]

    def list_by_acceptance(self, acceptance_id: str) -> list[EvidenceItem]:
        """List evidence for acceptance."""
        return [e for e in self._evidence_store.values() if e.acceptance_id == acceptance_id]

    def list_by_type(self, evidence_type: EvidenceType) -> list[EvidenceItem]:
        """List evidence by type."""
        return [e for e in self._evidence_store.values() if e.evidence_type == evidence_type]

    def get_collected_count(self, task_id: str) -> int:
        """Get count of collected evidence for task."""
        items = self.list_by_task(task_id)
        return len([e for e in items if e.status == EvidenceStatus.COLLECTED])

    def get_evidence_strength(self, task_id: str, required_count: int = 1) -> float:
        """
        Calculate evidence strength for task.

        Args:
            task_id: Task ID.
            required_count: Minimum required evidence count.

        Returns:
            Evidence strength 0.0-1.0.
        """
        collected = self.get_collected_count(task_id)
        if required_count <= 0:
            return 1.0
        return min(collected / required_count, 1.0)

    def _generate_evidence_id(self) -> str:
        """Generate unique evidence ID."""
        return generate_evidence_id()


def record_evidence(
    evidence_type: str,
    task_id: str,
    content_ref: str,
    content_hash: str,
    content_summary: str,
    collected_by: str,
    recorder: EvidenceRecorder | None = None
) -> EvidenceItem:
    """
    Convenience function to record evidence.

    Args:
        evidence_type: Evidence type string.
        task_id: Task binding.
        content_ref: Content reference.
        content_hash: Content hash.
        content_summary: Content summary.
        collected_by: Collector.
        recorder: Optional recorder instance.

    Returns:
        EvidenceItem instance.
    """
    recorder = recorder or EvidenceRecorder()
    et = EvidenceType(evidence_type.lower())
    return recorder.record(
        evidence_type=et,
        task_id=task_id,
        content_ref=content_ref,
        content_hash=content_hash,
        content_summary=content_summary,
        collected_by=collected_by
    )
