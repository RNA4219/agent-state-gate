"""Strict MCP facade contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from agent_state_gate.core import StaleSummary
from agent_state_gate.models import (
    ContractModel,
    EvaluateResult,
    ReplayResult,
    StateGateAssessResult,
)


class DocRef(ContractModel):
    doc_id: str
    version: str
    priority: str
    doc_type: str
    title: str


class ContractRef(ContractModel):
    contract_id: str
    contract_type: str
    version: str


class RecallResult(ContractModel):
    required_docs: list[DocRef]
    recommended_docs: list[DocRef]
    contract_refs: list[ContractRef]
    stale_summary: StaleSummary
    ack_required: bool


class EvidenceRef(ContractModel):
    evidence_id: str
    evidence_type: str
    status: str


class ApprovalRef(ContractModel):
    approval_id: str
    approver_role: str
    status: str


class StaleItem(ContractModel):
    item_type: str
    item_id: str
    current_version: str
    expected_version: str
    stale_reason: str


class StaleCheckResult(ContractModel):
    fresh: bool
    stale_items: list[StaleItem]
    stale_reasons: list[str]
    last_check_at: datetime


class SLAStatus(ContractModel):
    pending_count: int
    ack_timeout_count: int
    decision_timeout_count: int
    escalated_count: int


class AttentionListResult(ContractModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    total_pending: int
    by_severity: dict[str, int]
    sla_status: dict[str, SLAStatus]


ReplayContextResult = ReplayResult


__all__ = [
    "ApprovalRef",
    "AttentionListResult",
    "ContractRef",
    "DocRef",
    "EvaluateResult",
    "EvidenceRef",
    "RecallResult",
    "ReplayContextResult",
    "SLAStatus",
    "StaleCheckResult",
    "StaleItem",
    "StateGateAssessResult",
]
