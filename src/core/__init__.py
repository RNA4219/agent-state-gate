"""
agent-state-gate Core Engine Package

Core modules:
- AssessmentEngine: Assessment assembly and storage
- VerdictTransformer: Decision to verdict transformation
- ConflictResolver: Assessment conflict resolution
"""

from .assessment_engine import (
    Assessment,
    AssessmentEngine,
    AssessmentStore,
    CausalStep,
    Counterfactual,
)
from .conflict_resolver import (
    ConflictRecord,
    ConflictResolver,
    ConflictType,
    ResolutionResult,
    ResolutionStrategy,
    resolve_assessments,
)
from .verdict_transformer import (
    ApprovalSummary,
    Decision,
    EvidenceSummary,
    ObligationSummary,
    StaleSummary,
    TransformContext,
    Verdict,
    VerdictTransformer,
    get_verdict_priority,
    resolve_verdict,
)

__all__ = [
    # Verdict types
    "Verdict",
    "Decision",
    "StaleSummary",
    "ObligationSummary",
    "ApprovalSummary",
    "EvidenceSummary",
    "TransformContext",
    "VerdictTransformer",
    "resolve_verdict",
    "get_verdict_priority",
    # Assessment types
    "Assessment",
    "CausalStep",
    "Counterfactual",
    "AssessmentStore",
    "AssessmentEngine",
    # Conflict types
    "ConflictType",
    "ResolutionStrategy",
    "ConflictRecord",
    "ResolutionResult",
    "ConflictResolver",
    "resolve_assessments",
]
