"""
agent-state-gate Adapters Package

Provides adapter interfaces for connecting to external systems:
- agent-gatefield: State-space gate evaluation
- agent-taskstate: Task/run/context management
- agent-protocols: Contract/risk/approval definitions
- memx-resolver: Docs/chunks/stale/ack operations
- shipyard-cp: Pipeline stage/transition management
- workflow-cookbook: Evidence/acceptance/governance
"""

from .base import (
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
from .registry import AdapterRegistry, initialize_adapters

__all__ = [
    # Base types
    "BaseAdapter",
    "AdapterMetadata",
    "OperationMode",
    "FailurePolicy",
    # Registry
    "AdapterRegistry",
    "initialize_adapters",
    # Errors
    "AdapterError",
    "AdapterUnavailableError",
    "EntityNotFoundError",
    "TaskNotFoundError",
    "RunNotFoundError",
    "DecisionNotFoundError",
    "DocsNotFoundError",
    "StageNotFoundError",
    "EvidenceNotFoundError",
    "BundleNotFoundError",
    "ValidationError",
    "SchemaValidationError",
    "StaleCheckError",
    "TransitionNotAllowedError",
    "AckFailedError",
    "AssessmentError",
]
