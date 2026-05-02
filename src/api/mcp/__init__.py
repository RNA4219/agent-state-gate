"""
MCP Surface Module

MCP façade for agent-context-mcp.
Provides read-heavy surface for context, gate, and queue operations.

Reference: api_spec.md MCP Surface API
Reference: BLUEPRINT.md MCP Surface
"""

from .types import (
    DocRef,
    ContractRef,
    RecallResult,
    EvidenceRef,
    ApprovalRef,
    EvaluateResult,
    StaleItem,
    StaleCheckResult,
    StateGateAssessResult,
    SLAStatus,
    AttentionListResult,
    ReplayContextResult,
)
from .surface import MCPSurface, create_mcp_surface

__all__ = [
    # Types
    "DocRef",
    "ContractRef",
    "RecallResult",
    "EvidenceRef",
    "ApprovalRef",
    "EvaluateResult",
    "StaleItem",
    "StaleCheckResult",
    "StateGateAssessResult",
    "SLAStatus",
    "AttentionListResult",
    "ReplayContextResult",
    # Main class
    "MCPSurface",
    "create_mcp_surface",
]