"""
agent-state-gate API Package

MCP Surface for agent-context-mcp integration.
"""

from .mcp_surface import (
    ApprovalRef,
    AttentionListResult,
    ContractRef,
    DocRef,
    EvaluateResult,
    EvidenceRef,
    MCPSurface,
    RecallResult,
    ReplayContextResult,
    SLAStatus,
    StaleCheckResult,
    StaleItem,
    StateGateAssessResult,
    create_mcp_surface,
)

__all__ = [
    # Result types
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
    # MCP Surface
    "MCPSurface",
    "create_mcp_surface",
]
