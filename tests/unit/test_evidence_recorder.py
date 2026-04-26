"""
Unit tests for EvidenceRecorder.

Tests evidence recording, linking, and retrieval.
"""


from src.audit.evidence_recorder import (
    EvidenceItem,
    EvidenceRecorder,
    EvidenceStatus,
    EvidenceType,
    record_evidence,
)


class TestEvidenceType:
    def test_evidence_type_values(self):
        assert EvidenceType.TEST_RESULT.value == "test_result"
        assert EvidenceType.REVIEW_COMMENT.value == "review_comment"
        assert EvidenceType.CI_LOG.value == "ci_log"
        assert EvidenceType.ARTIFACT.value == "artifact"
        assert EvidenceType.APPROVAL.value == "approval"
        assert EvidenceType.RUN_TRACE.value == "run_trace"


class TestEvidenceStatus:
    def test_evidence_status_values(self):
        assert EvidenceStatus.COLLECTED.value == "collected"
        assert EvidenceStatus.PENDING.value == "pending"
        assert EvidenceStatus.FAILED.value == "failed"
        assert EvidenceStatus.EXPIRED.value == "expired"


class TestEvidenceItem:
    def test_evidence_item_creation(self):
        item = EvidenceItem(
            evidence_id="EV-001",
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-001",
            content_ref="test://test1",
            content_hash="hash123",
            content_summary="Test passed",
            collected_by="ci",
            collection_method="auto"
        )
        assert item.evidence_id == "EV-001"
        assert item.evidence_type == EvidenceType.TEST_RESULT
        assert item.status == EvidenceStatus.COLLECTED

    def test_evidence_item_with_run_id(self):
        item = EvidenceItem(
            evidence_id="EV-001",
            evidence_type=EvidenceType.RUN_TRACE,
            task_id="TASK-001",
            content_ref="run://trace",
            content_hash="hash123",
            content_summary="Run trace",
            collected_by="agent",
            collection_method="auto",
            run_id="RUN-001"
        )
        assert item.run_id == "RUN-001"


class TestEvidenceRecorderCreation:
    def test_recorder_creation(self):
        recorder = EvidenceRecorder()
        assert recorder is not None

    def test_recorder_with_custom_retention(self):
        recorder = EvidenceRecorder(default_retention_days=180)
        assert recorder._default_retention_days == 180


class TestEvidenceRecorderRecord:
    def test_record_basic(self):
        recorder = EvidenceRecorder()
        item = recorder.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-001",
            content_ref="test://test1",
            content_hash="hash123",
            content_summary="Test passed",
            collected_by="ci"
        )
        assert item.evidence_id is not None
        assert item.task_id == "TASK-001"
        assert item.evidence_type == EvidenceType.TEST_RESULT

    def test_record_with_run_id(self):
        recorder = EvidenceRecorder()
        item = recorder.record(
            evidence_type=EvidenceType.RUN_TRACE,
            task_id="TASK-001",
            content_ref="run://trace",
            content_hash="hash123",
            content_summary="Run trace",
            collected_by="agent",
            run_id="RUN-001"
        )
        assert item.run_id == "RUN-001"

    def test_record_with_acceptance(self):
        recorder = EvidenceRecorder()
        item = recorder.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-001",
            content_ref="test://test1",
            content_hash="hash123",
            content_summary="Test passed",
            collected_by="ci",
            acceptance_id="ACC-001"
        )
        assert item.acceptance_id == "ACC-001"

    def test_record_with_metadata(self):
        recorder = EvidenceRecorder()
        item = recorder.record(
            evidence_type=EvidenceType.METRIC,
            task_id="TASK-001",
            content_ref="metric://latency",
            content_hash="hash123",
            content_summary="Latency metric",
            collected_by="system",
            metadata={"value": 150, "unit": "ms"}
        )
        assert item.metadata["value"] == 150


class TestEvidenceRecorderConvenience:
    def test_record_test_result(self):
        recorder = EvidenceRecorder()
        item = recorder.record_test_result(
            task_id="TASK-001",
            test_name="test_login",
            test_result="passed"
        )
        assert item.evidence_type == EvidenceType.TEST_RESULT
        assert "test_login" in item.content_summary

    def test_record_test_result_failed(self):
        recorder = EvidenceRecorder()
        item = recorder.record_test_result(
            task_id="TASK-001",
            test_name="test_auth",
            test_result="failed",
            run_id="RUN-001"
        )
        assert "failed" in item.content_summary
        assert item.run_id == "RUN-001"

    def test_record_approval(self):
        recorder = EvidenceRecorder()
        item = recorder.record_approval(
            task_id="TASK-001",
            approver="reviewer@example.com",
            approval_type="code_review"
        )
        assert item.evidence_type == EvidenceType.APPROVAL
        assert item.collected_by == "reviewer@example.com"

    def test_record_approval_with_comment(self):
        recorder = EvidenceRecorder()
        item = recorder.record_approval(
            task_id="TASK-001",
            approver="security@example.com",
            approval_type="security_review",
            comment="Approved after security check"
        )
        assert item.metadata["comment"] == "Approved after security check"


class TestEvidenceRecorderLink:
    def test_link_to_acceptance(self):
        recorder = EvidenceRecorder()
        item = recorder.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-001",
            content_ref="test://test1",
            content_hash="hash123",
            content_summary="Test passed",
            collected_by="ci"
        )
        linked = recorder.link_to_acceptance(
            item.evidence_id,
            "ACC-001",
            "criteria://AC-001"
        )
        assert linked is not None
        assert linked.acceptance_id == "ACC-001"

    def test_link_to_acceptance_nonexistent(self):
        recorder = EvidenceRecorder()
        result = recorder.link_to_acceptance("EV-UNKNOWN", "ACC-001", "criteria://AC-001")
        assert result is None


class TestEvidenceRecorderQuery:
    def test_get_evidence(self):
        recorder = EvidenceRecorder()
        item = recorder.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-001",
            content_ref="test://test1",
            content_hash="hash123",
            content_summary="Test passed",
            collected_by="ci"
        )
        retrieved = recorder.get_evidence(item.evidence_id)
        assert retrieved is not None
        assert retrieved.evidence_id == item.evidence_id

    def test_get_evidence_nonexistent(self):
        recorder = EvidenceRecorder()
        result = recorder.get_evidence("EV-UNKNOWN")
        assert result is None

    def test_list_by_task(self):
        recorder = EvidenceRecorder()
        recorder.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-001",
            content_ref="test://test1",
            content_hash="hash123",
            content_summary="Test 1",
            collected_by="ci"
        )
        recorder.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-001",
            content_ref="test://test2",
            content_hash="hash456",
            content_summary="Test 2",
            collected_by="ci"
        )
        recorder.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-002",
            content_ref="test://test3",
            content_hash="hash789",
            content_summary="Test 3",
            collected_by="ci"
        )
        items = recorder.list_by_task("TASK-001")
        assert len(items) == 2

    def test_list_by_run(self):
        recorder = EvidenceRecorder()
        recorder.record(
            evidence_type=EvidenceType.RUN_TRACE,
            task_id="TASK-001",
            content_ref="run://trace1",
            content_hash="hash123",
            content_summary="Trace",
            collected_by="agent",
            run_id="RUN-001"
        )
        recorder.record(
            evidence_type=EvidenceType.RUN_TRACE,
            task_id="TASK-001",
            content_ref="run://trace2",
            content_hash="hash456",
            content_summary="Trace2",
            collected_by="agent",
            run_id="RUN-002"
        )
        items = recorder.list_by_run("RUN-001")
        assert len(items) == 1

    def test_list_by_acceptance(self):
        recorder = EvidenceRecorder()
        recorder.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-001",
            content_ref="test://test1",
            content_hash="hash123",
            content_summary="Test",
            collected_by="ci",
            acceptance_id="ACC-001"
        )
        items = recorder.list_by_acceptance("ACC-001")
        assert len(items) == 1

    def test_list_by_type(self):
        recorder = EvidenceRecorder()
        recorder.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-001",
            content_ref="test://test1",
            content_hash="hash123",
            content_summary="Test",
            collected_by="ci"
        )
        recorder.record(
            evidence_type=EvidenceType.APPROVAL,
            task_id="TASK-001",
            content_ref="approval://review",
            content_hash="hash456",
            content_summary="Approval",
            collected_by="reviewer"
        )
        items = recorder.list_by_type(EvidenceType.TEST_RESULT)
        assert len(items) == 1


class TestEvidenceRecorderMetrics:
    def test_get_collected_count(self):
        recorder = EvidenceRecorder()
        recorder.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-001",
            content_ref="test://test1",
            content_hash="hash123",
            content_summary="Test",
            collected_by="ci"
        )
        recorder.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-001",
            content_ref="test://test2",
            content_hash="hash456",
            content_summary="Test",
            collected_by="ci"
        )
        count = recorder.get_collected_count("TASK-001")
        assert count == 2

    def test_get_evidence_strength(self):
        recorder = EvidenceRecorder()
        recorder.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-001",
            content_ref="test://test1",
            content_hash="hash123",
            content_summary="Test",
            collected_by="ci"
        )
        strength = recorder.get_evidence_strength("TASK-001", required_count=2)
        assert strength == 0.5

    def test_get_evidence_strength_full(self):
        recorder = EvidenceRecorder()
        recorder.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-001",
            content_ref="test://test1",
            content_hash="hash123",
            content_summary="Test",
            collected_by="ci"
        )
        recorder.record(
            evidence_type=EvidenceType.TEST_RESULT,
            task_id="TASK-001",
            content_ref="test://test2",
            content_hash="hash456",
            content_summary="Test",
            collected_by="ci"
        )
        strength = recorder.get_evidence_strength("TASK-001", required_count=1)
        assert strength == 1.0

    def test_get_evidence_strength_zero_required(self):
        recorder = EvidenceRecorder()
        strength = recorder.get_evidence_strength("TASK-001", required_count=0)
        assert strength == 1.0


class TestRecordEvidenceFunction:
    def test_record_evidence_function(self):
        item = record_evidence(
            evidence_type="test_result",
            task_id="TASK-001",
            content_ref="test://test1",
            content_hash="hash123",
            content_summary="Test passed",
            collected_by="ci"
        )
        assert item.evidence_type == EvidenceType.TEST_RESULT
        assert item.task_id == "TASK-001"

    def test_record_evidence_with_recorder(self):
        recorder = EvidenceRecorder()
        item = record_evidence(
            evidence_type="approval",
            task_id="TASK-001",
            content_ref="approval://review",
            content_hash="hash123",
            content_summary="Approved",
            collected_by="reviewer",
            recorder=recorder
        )
        assert item.evidence_type == EvidenceType.APPROVAL
