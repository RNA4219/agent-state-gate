"""
Tests for adapters base module.

Tests BaseAdapter types, error classes, and metadata.
"""

import pytest

from src.adapters.base import (
    AckFailedError,
    AdapterError,
    AdapterMetadata,
    AdapterUnavailableError,
    AssessmentError,
    BaseAdapter,
    BundleNotFoundError,
    DecisionNotFoundError,
    DocsNotFoundError,
    EntityNotFoundError,
    EvidenceNotFoundError,
    FailurePolicy,
    OperationMode,
    RunNotFoundError,
    SchemaValidationError,
    StageNotFoundError,
    StaleCheckError,
    TaskNotFoundError,
    TransitionNotAllowedError,
    ValidationError,
)


class TestAdapterMetadata:
    """Tests for AdapterMetadata."""

    def test_metadata_creation(self):
        """Create adapter metadata."""
        metadata = AdapterMetadata(
            name="test_adapter",
            capability="test",
            operation_mode=OperationMode.READ_ONLY,
            timeout_ms=5000,
            failure_policy=FailurePolicy.FAIL_CLOSED,
            audit_required=True,
        )

        assert metadata.name == "test_adapter"
        assert metadata.operation_mode == OperationMode.READ_ONLY
        assert metadata.failure_policy == FailurePolicy.FAIL_CLOSED


class TestOperationModeEnum:
    """Tests for OperationMode enum."""

    def test_operation_mode_values(self):
        """OperationMode has correct values."""
        assert OperationMode.READ_ONLY.value == "read-only"
        assert OperationMode.APPEND_ONLY.value == "append-only"
        assert OperationMode.CONTROLLED_MUTATION.value == "controlled-mutation"


class TestFailurePolicyEnum:
    """Tests for FailurePolicy enum."""

    def test_failure_policy_values(self):
        """FailurePolicy has correct values."""
        assert FailurePolicy.FAIL_CLOSED.value == "fail-closed"
        assert FailurePolicy.FAIL_OPEN.value == "fail-open"
        assert FailurePolicy.NEEDS_APPROVAL.value == "needs-approval"


class TestErrorTypes:
    """Tests for error type hierarchy."""

    def test_adapter_error_base(self):
        """AdapterError is base class."""
        error = AdapterError("test error", "test_adapter")
        assert error.adapter_name == "test_adapter"
        assert str(error) == "test error"

    def test_adapter_unavailable_error_retryable(self):
        """AdapterUnavailableError is retryable."""
        error = AdapterUnavailableError("gatefield", "connection failed")
        assert error.retryable
        assert error.adapter_name == "gatefield"

    def test_task_not_found_error(self):
        """TaskNotFoundError has correct message."""
        error = TaskNotFoundError("01HTSK0001")
        assert "task" in str(error).lower()
        assert "01HTSK0001" in str(error)
        assert not error.retryable

    def test_run_not_found_error(self):
        """RunNotFoundError has correct message."""
        error = RunNotFoundError("01HRUN0001")
        assert "run" in str(error).lower()
        assert error.adapter_name == "taskstate"

    def test_decision_not_found_error(self):
        """DecisionNotFoundError has correct message."""
        error = DecisionNotFoundError("01HDEC0001")
        assert error.adapter_name == "gatefield"

    def test_docs_not_found_error(self):
        """DocsNotFoundError has correct message."""
        error = DocsNotFoundError("doc-001")
        assert error.adapter_name == "memx"

    def test_stage_not_found_error(self):
        """StageNotFoundError has correct message."""
        error = StageNotFoundError("run-001")
        assert error.adapter_name == "shipyard"

    def test_evidence_not_found_error(self):
        """EvidenceNotFoundError has correct message."""
        error = EvidenceNotFoundError("task-001")
        assert error.adapter_name == "workflow"

    def test_bundle_not_found_error(self):
        """BundleNotFoundError has correct message."""
        error = BundleNotFoundError("bundle-001")
        assert error.adapter_name == "taskstate"

    def test_schema_validation_error(self):
        """SchemaValidationError is not retryable."""
        error = SchemaValidationError("Invalid schema")
        assert not error.retryable
        assert error.adapter_name == "protocols"

    def test_stale_check_error_retryable(self):
        """StaleCheckError is retryable."""
        error = StaleCheckError("task-001", "check failed")
        assert error.retryable

    def test_transition_not_allowed_error(self):
        """TransitionNotAllowedError has details."""
        error = TransitionNotAllowedError(
            "run-001", "dev", "publish", "Not authorized"
        )
        assert "dev" in str(error)
        assert "publish" in str(error)
        assert not error.retryable

    def test_ack_failed_error(self):
        """AckFailedError has correct details."""
        error = AckFailedError("task-001", "doc-001")
        assert error.adapter_name == "memx"
        assert not error.retryable

    def test_assessment_error(self):
        """AssessmentError is internal."""
        error = AssessmentError("Internal error", "01HASM0001")
        assert error.assessment_id == "01HASM0001"


class TestErrorCatchability:
    """Tests for error catchability patterns."""

    def test_entity_not_found_catches_task(self):
        """TaskNotFoundError caught as EntityNotFoundError."""
        with pytest.raises(EntityNotFoundError):
            raise TaskNotFoundError("01HTSK0001")

    def test_entity_not_found_catches_run(self):
        """RunNotFoundError caught as EntityNotFoundError."""
        with pytest.raises(EntityNotFoundError):
            raise RunNotFoundError("01HRUN0001")

    def test_adapter_error_catches_unavailable(self):
        """AdapterUnavailableError caught as AdapterError."""
        with pytest.raises(AdapterError):
            raise AdapterUnavailableError("test", "error")

    def test_validation_error_catches_schema(self):
        """SchemaValidationError caught as ValidationError."""
        with pytest.raises(ValidationError):
            raise SchemaValidationError("error")


class TestMockAdapter:
    """Tests for mock adapter implementation."""

    def test_mock_adapter_implementation(self):
        """Mock adapter implements BaseAdapter."""

        class MockAdapter(BaseAdapter):
            @property
            def name(self) -> str:
                return "mock"

            @property
            def capability(self) -> str:
                return "mock"

            def health_check(self) -> bool:
                return True

            def get_metadata(self) -> AdapterMetadata:
                return AdapterMetadata(
                    name=self.name,
                    capability=self.capability,
                    operation_mode=OperationMode.READ_ONLY,
                )

        adapter = MockAdapter()
        assert adapter.name == "mock"
        assert adapter.capability == "mock"
        assert adapter.health_check()
        assert adapter.get_metadata().name == "mock"
