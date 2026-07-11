"""agent-state-gate 0.5 public package."""

from .adapters import AdapterMetadata, AdapterRegistry, BaseAdapter, initialize_adapters
from .api import MCPSurface, RecallResult, StaleCheckResult, create_mcp_surface
from .auth import AuthenticationError, AuthorizationError, OIDCAuthenticator, local_request_context
from .common import (
    SCHEMA_VERSION,
    __version__,
    generate_assessment_id,
    generate_audit_packet_id,
    generate_evidence_id,
    generate_id,
    generate_queue_item_id,
    hash_dict,
    iso_timestamp,
    utc_now,
)
from .config import AppConfig, RuntimeProfile, load_config
from .core import Assessment as LegacyAssessment
from .core import AssessmentEngine, ConflictResolver, Verdict, VerdictTransformer
from .models import (
    AdapterHealth,
    ApprovalBinding,
    AssessmentModel,
    DecisionPacket,
    EvaluateResult,
    EvidenceReport,
    GateEvaluationRequest,
    HealthReport,
    ReplayResult,
    ReplayStatus,
    RequestContext,
    RiskLevel,
    StateGateAssessRequest,
    StateGateAssessResult,
)
from .persistence import Database
from .queue import (
    HumanAttentionQueue,
    HumanQueueItem,
    QueueStatus,
    ReasonCode,
    Severity,
    route_assessment_to_queue,
)
from .service import GateService, create_gate_service
from .typed_ref import (
    KNOWN_DOMAINS,
    KNOWN_ENTITY_TYPES,
    KNOWN_PROVIDERS,
    TypedRef,
    canonicalize_ref,
    format_ref,
    is_valid_ref,
    parse_ref,
)

# Public Assessment is the strict v0.5 contract. LegacyAssessment remains available
# only to support the 0.4 in-process engine during the compatibility release.
Assessment = AssessmentModel

__all__ = [
    "AdapterHealth",
    "AdapterMetadata",
    "AdapterRegistry",
    "AppConfig",
    "ApprovalBinding",
    "Assessment",
    "AssessmentEngine",
    "AuthenticationError",
    "AuthorizationError",
    "BaseAdapter",
    "ConflictResolver",
    "Database",
    "DecisionPacket",
    "EvaluateResult",
    "EvidenceReport",
    "GateEvaluationRequest",
    "GateService",
    "HealthReport",
    "HumanAttentionQueue",
    "HumanQueueItem",
    "KNOWN_DOMAINS",
    "KNOWN_ENTITY_TYPES",
    "KNOWN_PROVIDERS",
    "LegacyAssessment",
    "MCPSurface",
    "OIDCAuthenticator",
    "QueueStatus",
    "RecallResult",
    "ReasonCode",
    "ReplayResult",
    "ReplayStatus",
    "RequestContext",
    "RiskLevel",
    "RuntimeProfile",
    "SCHEMA_VERSION",
    "Severity",
    "StaleCheckResult",
    "StateGateAssessRequest",
    "StateGateAssessResult",
    "TypedRef",
    "Verdict",
    "VerdictTransformer",
    "__version__",
    "canonicalize_ref",
    "create_gate_service",
    "create_mcp_surface",
    "format_ref",
    "generate_assessment_id",
    "generate_audit_packet_id",
    "generate_evidence_id",
    "generate_id",
    "generate_queue_item_id",
    "hash_dict",
    "initialize_adapters",
    "is_valid_ref",
    "iso_timestamp",
    "load_config",
    "local_request_context",
    "parse_ref",
    "route_assessment_to_queue",
    "utc_now",
]
