"""
agent-state-gate Adapter Base Types

BaseAdapter interface, AdapterMetadata, and common error types.
All adapters inherit from BaseAdapter and follow this contract.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


class OperationMode(StrEnum):
    """Adapter operation mode classification."""
    READ_ONLY = "read-only"
    APPEND_ONLY = "append-only"
    CONTROLLED_MUTATION = "controlled-mutation"


class FailurePolicy(StrEnum):
    """Adapter failure policy for unavailable/error conditions."""
    FAIL_CLOSED = "fail-closed"  # Block on failure (high-risk context)
    FAIL_OPEN = "fail-open"      # Allow on failure (low-risk context)
    NEEDS_APPROVAL = "needs-approval"  # Require human review on failure


@dataclass
class AdapterMetadata:
    """Adapter metadata describing capabilities and constraints."""
    name: str
    capability: str
    operation_mode: OperationMode
    idempotency_key: str | None = None
    timeout_ms: int = 5000  # Default 5s timeout
    failure_policy: FailurePolicy = FailurePolicy.FAIL_CLOSED
    audit_required: bool = True


class BaseAdapter(ABC):
    """
    Abstract base class for all agent-state-gate adapters.

    Each adapter connects to an external system (agent-gatefield, agent-taskstate,
    memx-resolver, shipyard-cp, workflow-cookbook, agent-protocols) and provides
    specific capabilities as defined in adapter_contract.md.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique adapter name (e.g., 'gatefield', 'taskstate')."""
        pass

    @property
    @abstractmethod
    def capability(self) -> str:
        """Capability descriptor (e.g., 'state-space-gate', 'task-state')."""
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """
        Check if the adapter and its target system are healthy.

        Returns:
            True if healthy and ready to process requests.
        """
        pass

    @abstractmethod
    def get_metadata(self) -> AdapterMetadata:
        """
        Get adapter metadata including operation mode and failure policy.

        Returns:
            AdapterMetadata instance describing this adapter.
        """
        pass


# --- Error Types (Section 11: Adapter Error Type Mapping) ---

class AdapterError(Exception):
    """Base class for all adapter-related errors."""
    def __init__(self, message: str, adapter_name: str, retryable: bool = False):
        self.adapter_name = adapter_name
        self.retryable = retryable
        super().__init__(message)


class AdapterUnavailableError(AdapterError):
    """Adapter or target system is unavailable (HTTP 503)."""
    def __init__(self, adapter_name: str, details: str | None = None):
        super().__init__(
            f"Adapter '{adapter_name}' unavailable: {details or 'connection failed'}",
            adapter_name,
            retryable=True
        )


class EntityNotFoundError(AdapterError):
    """Requested entity not found (HTTP 404)."""
    def __init__(self, adapter_name: str, entity_type: str, entity_id: str):
        super().__init__(
            f"{entity_type} '{entity_id}' not found in {adapter_name}",
            adapter_name,
            retryable=False
        )


class TaskNotFoundError(EntityNotFoundError):
    """Task not found in agent-taskstate."""
    def __init__(self, task_id: str):
        super().__init__("taskstate", "task", task_id)


class RunNotFoundError(EntityNotFoundError):
    """Run not found in agent-taskstate."""
    def __init__(self, run_id: str):
        super().__init__("taskstate", "run", run_id)


class DecisionNotFoundError(EntityNotFoundError):
    """Decision not found in agent-gatefield."""
    def __init__(self, decision_id: str):
        super().__init__("gatefield", "decision", decision_id)


class DocsNotFoundError(EntityNotFoundError):
    """Docs not found in memx-resolver."""
    def __init__(self, doc_id: str):
        super().__init__("memx", "doc", doc_id)


class StageNotFoundError(EntityNotFoundError):
    """Stage not found in shipyard-cp."""
    def __init__(self, run_id: str):
        super().__init__("shipyard", "stage", run_id)


class EvidenceNotFoundError(EntityNotFoundError):
    """Evidence not found in workflow-cookbook."""
    def __init__(self, task_id: str):
        super().__init__("workflow", "evidence", task_id)


class BundleNotFoundError(EntityNotFoundError):
    """ContextBundle not found in agent-taskstate."""
    def __init__(self, bundle_id: str):
        super().__init__("taskstate", "context_bundle", bundle_id)


class ValidationError(AdapterError):
    """Schema or contract validation failed (HTTP 400)."""
    def __init__(self, adapter_name: str, details: str):
        super().__init__(
            f"Validation failed in {adapter_name}: {details}",
            adapter_name,
            retryable=False
        )


class SchemaValidationError(ValidationError):
    """Schema validation failed in agent-protocols."""
    def __init__(self, details: str):
        super().__init__("protocols", details)


class StaleCheckError(AdapterError):
    """Stale check operation failed (HTTP 500, conditional retry)."""
    def __init__(self, task_id: str, details: str | None = None):
        super().__init__(
            f"Stale check failed for task '{task_id}': {details or 'unknown error'}",
            "memx",
            retryable=True  # Conditional retry based on error type
        )


class TransitionNotAllowedError(AdapterError):
    """State transition not allowed (HTTP 409)."""
    def __init__(self, run_id: str, from_stage: str, to_stage: str, reason: str):
        super().__init__(
            f"Transition {from_stage} -> {to_stage} not allowed for run '{run_id}': {reason}",
            "shipyard",
            retryable=False
        )


class AckFailedError(AdapterError):
    """Read acknowledgment failed in memx-resolver."""
    def __init__(self, task_id: str, doc_id: str):
        super().__init__(
            f"Ack failed for doc '{doc_id}' in task '{task_id}'",
            "memx",
            retryable=False
        )


class AssessmentError(Exception):
    """Internal assessment engine error (not adapter-related)."""
    def __init__(self, message: str, assessment_id: str | None = None):
        self.assessment_id = assessment_id
        super().__init__(message)
