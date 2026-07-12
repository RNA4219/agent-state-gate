"""Strict public contracts for the agent-state-gate service."""

from __future__ import annotations

import math
import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from .common import generate_trace_id, utc_now
from .config import RuntimeProfile

_HEX_32 = re.compile(r"^[0-9a-f]{32}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReplayStatus(StrEnum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"


class RequestContext(ContractModel):
    tenant_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    roles: frozenset[str] = Field(default_factory=frozenset)
    trace_id: str = Field(default_factory=generate_trace_id)
    authenticated: bool = True

    @field_validator("roles", mode="before")
    @classmethod
    def normalize_roles(cls, value: Any) -> frozenset[str]:
        if isinstance(value, (set, frozenset, list, tuple)):
            return frozenset(value)
        return value

    @field_validator("tenant_id", "subject")
    @classmethod
    def no_blank_identifiers(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifier must be non-blank")
        return value

    @field_validator("trace_id")
    @classmethod
    def valid_trace_id(cls, value: str) -> str:
        normalized = value.lower()
        if not _HEX_32.fullmatch(normalized):
            raise ValueError("trace_id must be 32 lowercase hex characters")
        return normalized


class GateEvaluationRequest(ContractModel):
    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    risk_hints: dict[str, Any] = Field(default_factory=dict)
    touched_paths: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    diff_hash: str | None = None
    semantic_evidence: dict[str, Any] | None = None

    @field_validator("diff_hash")
    @classmethod
    def valid_optional_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower()
        if not _HEX_64.fullmatch(normalized):
            raise ValueError("diff_hash must be 64 lowercase hex characters")
        return normalized


class StateGateAssessRequest(ContractModel):
    artifact_refs: list[str] = Field(min_length=1)
    diff_hash: str
    redacted_diff: str | None = None
    semantic_evidence: dict[str, Any] | None = None
    run_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)

    @field_validator("diff_hash")
    @classmethod
    def valid_hash(cls, value: str) -> str:
        normalized = value.lower()
        if not _HEX_64.fullmatch(normalized):
            raise ValueError("diff_hash must be 64 lowercase hex characters")
        return normalized

    @model_validator(mode="after")
    def exactly_one_safe_artifact(self) -> StateGateAssessRequest:
        if (self.redacted_diff is None) == (self.semantic_evidence is None):
            raise ValueError("exactly one of redacted_diff or semantic_evidence is required")
        return self


class DecisionFactor(ContractModel):
    name: str = Field(min_length=1)
    value: float
    contribution: float = 0.0


class DecisionPacket(ContractModel):
    schema_version: str = "2.0.0"
    decision_id: str = Field(min_length=1)
    run_id: str = ""
    artifact_id: str = ""
    decision: str
    composite_score: float = Field(ge=0.0, le=1.0)
    factors: list[DecisionFactor] = Field(default_factory=list)
    exemplar_refs: list[dict[str, Any]] = Field(default_factory=list)
    action: dict[str, Any] = Field(default_factory=dict)
    threshold_version: str = ""
    policy_version: str = ""
    static_gate_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    evidence_status: str = "unknown"
    degraded_components: list[str] = Field(default_factory=list)
    request_id: str = ""
    state_vector_ref: str = ""
    self_correction_count: int = Field(default=0, ge=0)
    uncertainty_score: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("decision")
    @classmethod
    def valid_decision(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"pass", "warn", "hold", "block"}:
            raise ValueError("unsupported gatefield decision")
        return normalized


class EvidenceReport(ContractModel):
    required_evidence: list[str] = Field(default_factory=list)
    collected_evidence: list[str] = Field(default_factory=list)
    unlinked_evidence: list[str] = Field(default_factory=list)
    evidence_strength: float | None = Field(default=None, ge=0.0, le=1.0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def computed_strength(self) -> float:
        required = set(self.required_evidence)
        if not required:
            return 1.0
        return len(required & set(self.collected_evidence)) / len(required)

    @model_validator(mode="after")
    def supplied_strength_matches(self) -> EvidenceReport:
        if self.evidence_strength is not None and not math.isclose(
            self.evidence_strength,
            self.computed_strength,
            abs_tol=1e-9,
        ):
            raise ValueError("evidence_strength does not match collected/required evidence")
        return self

    @classmethod
    def from_adapter(cls, value: dict[str, Any]) -> EvidenceReport:
        if "required_evidence" in value or "collected_evidence" in value:
            return cls.model_validate(value)
        acceptances = value.get("acceptances", [])
        evidences = value.get("evidences", [])
        required = [str(item.get("id")) for item in acceptances if item.get("id")]
        collected = [
            str(item.get("acceptance_id", item.get("id")))
            for item in evidences
            if item.get("acceptance_id") or item.get("id")
        ]
        return cls(
            required_evidence=required,
            collected_evidence=collected,
            unlinked_evidence=[str(item) for item in value.get("unlinked_evidences", [])],
        )


class ApprovalBinding(ContractModel):
    approval_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    diff_hash: str
    context_hash: str
    policy_version: str = Field(min_length=1)
    approved_roles: frozenset[str] = Field(default_factory=frozenset)
    expires_at: datetime | None = None
    @field_validator("approved_roles", mode="before")
    @classmethod
    def normalize_approved_roles(cls, value: Any) -> frozenset[str]:
        if isinstance(value, (set, frozenset, list, tuple)):
            return frozenset(value)
        return value


    @field_validator("diff_hash", "context_hash")
    @classmethod
    def valid_binding_hash(cls, value: str) -> str:
        normalized = value.lower()
        if not _HEX_64.fullmatch(normalized):
            raise ValueError("approval binding hashes must be 64 lowercase hex characters")
        return normalized

    def is_current(
        self,
        *,
        tenant_id: str,
        diff_hash: str,
        context_hash: str,
        policy_version: str,
        now: datetime | None = None,
    ) -> bool:
        current_time = now or utc_now()
        expires_at = self.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=current_time.tzinfo)
        return (
            self.tenant_id == tenant_id
            and self.diff_hash == diff_hash
            and self.context_hash == context_hash
            and self.policy_version == policy_version
            and (expires_at is None or expires_at > current_time)
        )


class AdapterHealth(ContractModel):
    name: str
    healthy: bool
    latency_ms: float | None = None
    failure_policy: str
    details: dict[str, Any] = Field(default_factory=dict)


class AssessmentModel(ContractModel):
    assessment_id: str
    tenant_id: str
    task_id: str
    run_id: str
    stage: str
    decision_packet_ref: str
    final_verdict: str
    verdict_reason: str
    context_hash: str
    diff_hash: str
    policy_version: str
    threshold_version: str
    degraded: bool = False
    unavailable_axes: list[str] = Field(default_factory=list)
    failure_policy_applied: dict[str, str] = Field(default_factory=dict)
    causal_trace: list[dict[str, Any]] = Field(default_factory=list)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    approval_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class EvaluateResult(ContractModel):
    verdict: str
    assessment_id: str
    verdict_reason: str
    runtime_profile: RuntimeProfile
    degraded: bool = False
    unavailable_axes: list[str] = Field(default_factory=list)
    failure_policy_applied: dict[str, str] = Field(default_factory=dict)
    policy_version: str = ""
    audit_packet_ref: str = ""
    required_evidence: list[str] = Field(default_factory=list)
    required_approvals: list[str] = Field(default_factory=list)
    causal_trace: list[dict[str, Any]] = Field(default_factory=list)


class StateGateAssessResult(ContractModel):
    assessment_id: str
    decision_packet_ref: str = ""
    scores: dict[str, float] = Field(default_factory=dict)
    recommendation: str
    human_queue_required: bool
    exemplar_refs: list[str] = Field(default_factory=list)
    threshold_version: str = ""
    degraded: bool = False
    unavailable_axes: list[str] = Field(default_factory=list)


class ReplayResult(ContractModel):
    run_id: str
    status: ReplayStatus
    expected_verdict: str | None = None
    actual_verdict: str | None = None
    attestation_hash: str | None = None
    audit_packet_ref: str = ""
    details: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reproducibility_verified(self) -> bool:
        return self.status == ReplayStatus.VERIFIED


class HealthReport(ContractModel):
    ready: bool
    runtime_profile: RuntimeProfile
    adapters: dict[str, AdapterHealth]
    database_healthy: bool
    production_ready: bool
    checked_at: datetime = Field(default_factory=utc_now)


__all__ = [
    "AdapterHealth",
    "ApprovalBinding",
    "AssessmentModel",
    "ContractModel",
    "DecisionFactor",
    "DecisionPacket",
    "EvaluateResult",
    "EvidenceReport",
    "GateEvaluationRequest",
    "HealthReport",
    "ReplayResult",
    "ReplayStatus",
    "RequestContext",
    "RiskLevel",
    "StateGateAssessRequest",
    "StateGateAssessResult",
]
