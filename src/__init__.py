"""
agent-state-gate Package

Engineering Governance Integration Layer.
Integrates 6 existing assets for unified control surface:
- agent-gatefield: State-space gate evaluation
- agent-taskstate: Task/run/context management
- agent-protocols: Contract/risk/approval definitions
- memx-resolver: Docs/chunks/stale/ack operations
- shipyard-cp: Pipeline stage/transition management
- workflow-cookbook: Evidence/acceptance/governance
"""

from .adapters import (
    AdapterMetadata,
    AdapterRegistry,
    BaseAdapter,
    initialize_adapters,
)
from .api import (
    EvaluateResult,
    MCPSurface,
    RecallResult,
    StaleCheckResult,
    create_mcp_surface,
)
from .audit import (
    AuditPacket,
    AuditPacketGenerator,
    EvidenceRecorder,
    create_audit_packet,
)
from .common import (
    SCHEMA_VERSION,
    generate_assessment_id,
    generate_audit_packet_id,
    generate_evidence_id,
    generate_id,
    generate_queue_item_id,
    hash_dict,
    iso_timestamp,
    utc_now,
)
from .core import (
    Assessment,
    AssessmentEngine,
    ConflictResolver,
    Verdict,
    VerdictTransformer,
)
from .queue import (
    HumanAttentionQueue,
    HumanQueueItem,
    QueueStatus,
    ReasonCode,
    Severity,
    route_assessment_to_queue,
)
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

__version__ = "0.4.2"

__all__ = [
    # common
    "utc_now",
    "generate_id",
    "generate_assessment_id",
    "generate_audit_packet_id",
    "generate_queue_item_id",
    "generate_evidence_id",
    "hash_dict",
    "iso_timestamp",
    "SCHEMA_VERSION",
    # typed_ref
    "TypedRef",
    "parse_ref",
    "canonicalize_ref",
    "format_ref",
    "is_valid_ref",
    "KNOWN_DOMAINS",
    "KNOWN_ENTITY_TYPES",
    "KNOWN_PROVIDERS",
    # adapters
    "BaseAdapter",
    "AdapterMetadata",
    "AdapterRegistry",
    "initialize_adapters",
    # core
    "Verdict",
    "Assessment",
    "AssessmentEngine",
    "VerdictTransformer",
    "ConflictResolver",
    # queue
    "HumanQueueItem",
    "HumanAttentionQueue",
    "QueueStatus",
    "ReasonCode",
    "Severity",
    "route_assessment_to_queue",
    # audit
    "AuditPacket",
    "AuditPacketGenerator",
    "EvidenceRecorder",
    "create_audit_packet",
    # api
    "MCPSurface",
    "create_mcp_surface",
    "RecallResult",
    "EvaluateResult",
    "StaleCheckResult",
]
