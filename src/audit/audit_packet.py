"""
Audit Packet Module

Generates audit packets for SIEM/export and replay reproducibility.
Contains complete trace of assessment decision with refs.

Reference: AC-008_audit_packet.json golden fixture
Reference: architecture.md AuditPacket structure
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from ..common import (
    SCHEMA_VERSION,
    generate_audit_packet_id,
    generate_span_id,
    generate_trace_id,
    hash_dict,
    utc_now,
)
from ..core import Assessment, Verdict
from ..typed_ref import audit_packet_ref


class RetentionClass(StrEnum):
    """Audit packet retention classification."""
    AUDIT = "audit"        # Long-term retention (365 days)
    OPS = "ops"            # Operational retention (90 days)
    PII_SENSITIVE = "pii-sensitive"  # Short-term retention (30 days)


@dataclass
class AuditPacket:
    """
    Audit packet for SIEM/export.

    Contains complete trace of assessment with refs to all components.

    Reference: AC-008_audit_packet.json
    """
    packet_id: str
    trace_id: str              # OTel trace ID (32 hex chars)
    span_id: str               # OTel span ID (16 hex chars)

    assessment_id: str
    run_id: str

    # Decision packet reference
    decision_packet_ref: str
    decision_packet_hash: str

    # Verdict (required fields)
    final_verdict: str
    verdict_reason: str

    # Hashes for reproducibility (required fields)
    context_hash: str
    diff_hash: str
    threshold_version: str

    # Check results (optional with defaults)
    stale_check_result: dict[str, Any] = field(default_factory=dict)
    obligation_check_result: dict[str, Any] = field(default_factory=dict)
    approval_check_result: dict[str, Any] = field(default_factory=dict)
    evidence_check_result: dict[str, Any] = field(default_factory=dict)

    causal_trace: list[dict[str, Any]] = field(default_factory=list)

    # Timestamps
    created_at: datetime = field(default_factory=utc_now)

    # Retention
    retention_class: RetentionClass = RetentionClass.AUDIT

    # Additional metadata
    environment: str = "local"
    schema_version: str = SCHEMA_VERSION


class AuditPacketGenerator:
    """
    Generator for audit packets.

    Creates audit packets from assessments with full trace.
    """

    def __init__(self, retention_days: dict[str, int] = None):
        self._retention_days = retention_days or {
            "audit": 365,
            "ops": 90,
            "pii-sensitive": 30,
        }

    def generate(
        self,
        assessment: Assessment,
        trace_id: str | None = None,
        span_id: str | None = None,
        decision_packet: dict | None = None,
        environment: str = "local"
    ) -> AuditPacket:
        """
        Generate audit packet from assessment.

        Args:
            assessment: Assessment to audit.
            trace_id: Optional OTel trace ID (auto-generated if None).
            span_id: Optional OTel span ID (auto-generated if None).
            decision_packet: Optional DecisionPacket for hash.
            environment: Environment name.

        Returns:
            AuditPacket instance.
        """
        packet_id = self._generate_packet_id()
        trace_id = trace_id or self._generate_trace_id()
        span_id = span_id or self._generate_span_id()

        # Build causal trace
        causal_trace = [
            {
                "step_id": step.step_id,
                "contribution_weight": step.contribution_weight,
            }
            for step in assessment.causal_trace
        ]

        # Build check results
        stale_check_result = {
            "fresh": assessment.stale_summary.fresh,
            "stale_items": assessment.stale_summary.stale_items,
        }
        obligation_check_result = {
            "fulfillment_rate": assessment.obligation_summary.fulfillment_rate,
        }
        approval_check_result = {
            "missing_approvals": assessment.approval_summary.missing_approvals,
        }
        evidence_check_result = {
            "evidence_strength": assessment.evidence_summary.evidence_strength,
        }

        # Decision packet hash
        decision_packet_hash = ""
        if decision_packet:
            decision_packet_hash = self._hash_decision_packet(decision_packet)

        # Determine retention class
        retention_class = self._determine_retention_class(assessment)

        packet = AuditPacket(
            packet_id=packet_id,
            trace_id=trace_id,
            span_id=span_id,
            assessment_id=assessment.assessment_id,
            run_id=assessment.run_id,
            decision_packet_ref=assessment.decision_packet_ref,
            decision_packet_hash=decision_packet_hash,
            stale_check_result=stale_check_result,
            obligation_check_result=obligation_check_result,
            approval_check_result=approval_check_result,
            evidence_check_result=evidence_check_result,
            final_verdict=assessment.final_verdict.value,
            verdict_reason=assessment.verdict_reason,
            causal_trace=causal_trace,
            context_hash=assessment.context_hash,
            diff_hash=assessment.diff_hash,
            threshold_version=assessment.threshold_version,
            retention_class=retention_class,
            environment=environment,
        )

        return packet

    def export_jsonl(self, packet: AuditPacket) -> str:
        """
        Export audit packet as JSONL line.

        Args:
            packet: AuditPacket to export.

        Returns:
            JSONL string.
        """
        data = {
            "packet_id": packet.packet_id,
            "trace_id": packet.trace_id,
            "span_id": packet.span_id,
            "assessment_id": packet.assessment_id,
            "run_id": packet.run_id,
            "decision_packet_ref": packet.decision_packet_ref,
            "decision_packet_hash": packet.decision_packet_hash,
            "stale_check_result": packet.stale_check_result,
            "obligation_check_result": packet.obligation_check_result,
            "approval_check_result": packet.approval_check_result,
            "evidence_check_result": packet.evidence_check_result,
            "final_verdict": packet.final_verdict,
            "verdict_reason": packet.verdict_reason,
            "causal_trace": packet.causal_trace,
            "context_hash": packet.context_hash,
            "diff_hash": packet.diff_hash,
            "threshold_version": packet.threshold_version,
            "created_at": packet.created_at.isoformat(),
            "retention_class": packet.retention_class.value,
            "environment": packet.environment,
            "schema_version": packet.schema_version,
        }
        return json.dumps(data, sort_keys=True)

    def _generate_packet_id(self) -> str:
        """Generate unique packet ID."""
        return generate_audit_packet_id()

    def _generate_trace_id(self) -> str:
        """Generate OTel trace ID (32 hex chars)."""
        return generate_trace_id()

    def _generate_span_id(self) -> str:
        """Generate OTel span ID (16 hex chars)."""
        return generate_span_id()

    def _hash_decision_packet(self, decision_packet: dict) -> str:
        """Hash decision packet for reference."""
        return hash_dict(decision_packet)

    def _determine_retention_class(self, assessment: Assessment) -> RetentionClass:
        """Determine retention class based on assessment."""
        # Check for sensitive data indicators
        verdict = assessment.final_verdict

        if verdict == Verdict.DENY:
            # Block decisions have audit retention
            return RetentionClass.AUDIT

        # Check for sensitive tags in causal trace
        for step in assessment.causal_trace:
            if "secret" in step.rationale.lower() or "pii" in step.rationale.lower():
                return RetentionClass.PII_SENSITIVE

        # Default to audit for significant decisions
        if verdict in [Verdict.REQUIRE_HUMAN, Verdict.NEEDS_APPROVAL]:
            return RetentionClass.AUDIT

        return RetentionClass.OPS


class AuditPacketStore:
    """
    In-memory store for audit packets.

    MVP: Simple dict-based storage.
    Future: Persistent backend.
    """

    def __init__(self):
        self._packets: dict[str, AuditPacket] = {}

    def save(self, packet: AuditPacket) -> str:
        """Save audit packet."""
        self._packets[packet.packet_id] = packet
        return audit_packet_ref(packet.packet_id)

    def get(self, packet_id: str) -> AuditPacket | None:
        """Get audit packet by ID."""
        return self._packets.get(packet_id)

    def list_by_run(self, run_id: str) -> list[AuditPacket]:
        """List audit packets for run."""
        return [p for p in self._packets.values() if p.run_id == run_id]

    def list_by_assessment(self, assessment_id: str) -> list[AuditPacket]:
        """List audit packets for assessment."""
        return [p for p in self._packets.values() if p.assessment_id == assessment_id]


def create_audit_packet(
    assessment: Assessment,
    decision_packet: dict | None = None,
    trace_id: str | None = None,
    environment: str = "local"
) -> AuditPacket:
    """
    Convenience function to create audit packet.

    Args:
        assessment: Assessment instance.
        decision_packet: Optional DecisionPacket.
        trace_id: Optional trace ID.
        environment: Environment name.

    Returns:
        AuditPacket instance.
    """
    generator = AuditPacketGenerator()
    return generator.generate(
        assessment=assessment,
        trace_id=trace_id,
        decision_packet=decision_packet,
        environment=environment
    )
