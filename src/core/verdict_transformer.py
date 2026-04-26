"""
VerdictTransformer Module

Transforms gatefield decision to external verdict.
Implements Decision Table rules with fixed branching logic.

Reference: BLUEPRINT.md Section 6 (Verdict変換規則)
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Verdict(StrEnum):
    """
    External verdict values for agent-state-gate.

    These are the transformed verdicts from gatefield decisions,
    suitable for MCP surface and external consumers.
    """
    ALLOW = "allow"
    STALE_BLOCKED = "stale_blocked"
    NEEDS_APPROVAL = "needs_approval"
    REQUIRE_HUMAN = "require_human"
    REVISE = "revise"
    DENY = "deny"


class Decision(StrEnum):
    """Gatefield decision values."""
    PASS = "pass"
    WARN = "warn"
    HOLD = "hold"
    BLOCK = "block"


@dataclass
class StaleSummary:
    """Stale check result summary."""
    fresh: bool
    stale_items: list[dict[str, Any]] = field(default_factory=list)
    stale_reasons: list[str] = field(default_factory=list)


@dataclass
class ObligationSummary:
    """Obligation fulfillment summary."""
    fulfillment_rate: float = 1.0
    has_critical_unfulfilled: bool = False
    has_high_unfulfilled: bool = False
    unfulfilled_items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ApprovalSummary:
    """Approval status summary."""
    missing_approvals: list[str] = field(default_factory=list)
    required_approvals: list[str] = field(default_factory=list)
    approved_roles: list[str] = field(default_factory=list)
    approval_rate: float = 1.0


@dataclass
class EvidenceSummary:
    """Evidence collection summary."""
    evidence_strength: float = 1.0
    required_evidence: list[str] = field(default_factory=list)
    collected_evidence: list[str] = field(default_factory=list)
    unlinked_evidence: list[str] = field(default_factory=list)


@dataclass
class TransformContext:
    """
    Context for verdict transformation.

    Contains all summaries and metadata needed for resolve_verdict.
    """
    decision: Decision
    stale_summary: StaleSummary
    obligation_summary: ObligationSummary
    approval_summary: ApprovalSummary
    evidence_summary: EvidenceSummary
    final_verdict: Verdict = Verdict.ALLOW  # Computed verdict
    permission_level: str = "standard"  # standard, admin, elevated
    uncertainty_score: float = 0.0
    self_correction_count: int = 0
    sla_status: str = "pending"  # pending, timeout, completed
    verdict_reason: str = ""


def resolve_verdict(
    decision: str,
    stale_summary: StaleSummary,
    obligation_summary: ObligationSummary,
    approval_summary: ApprovalSummary,
    evidence_summary: EvidenceSummary,
    permission_level: str = "standard",
    uncertainty_score: float = 0.0,
    self_correction_count: int = 0,
    sla_status: str = "pending"
) -> Verdict:
    """
    Transform gatefield decision to external verdict.

    Implements fixed branching logic from BLUEPRINT.md Section 6.

    Args:
        decision: Gatefield decision (pass/warn/hold/block).
        stale_summary: Stale check result.
        obligation_summary: Obligation fulfillment status.
        approval_summary: Approval status.
        evidence_summary: Evidence collection status.
        permission_level: Permission level (standard/admin/elevated).
        uncertainty_score: Uncertainty score from DecisionPacket.
        self_correction_count: Self-correction attempts from DecisionPacket.
        sla_status: SLA status (pending/timeout/completed).

    Returns:
        Verdict enum value.

    Reference: BLUEPRINT.md lines 134-209
    """
    # Normalize decision string
    dec = Decision(decision.lower()) if isinstance(decision, str) else decision

    # Priority 1: Hard override (block → deny確定)
    if dec == Decision.BLOCK:
        return Verdict.DENY

    # Priority 2: Stale detection (stale → stale_blocked確定)
    if not stale_summary.fresh:
        return Verdict.STALE_BLOCKED

    # Priority 3: Pass分岐
    if dec == Decision.PASS:
        # 3a: Evidence不足 → needs_approval
        if evidence_summary.evidence_strength < 0.85:
            return Verdict.NEEDS_APPROVAL

        # 3b: Obligation不足 → severity分岐
        if obligation_summary.fulfillment_rate < 1.0:
            # critical obligation未充足 → deny (安全上重要)
            if obligation_summary.has_critical_unfulfilled:
                return Verdict.DENY
            # high obligation未充足 → require_human
            elif obligation_summary.has_high_unfulfilled:
                return Verdict.REQUIRE_HUMAN
            # medium/low → needs_approval
            else:
                return Verdict.NEEDS_APPROVAL

        # 3c: 全充足 → allow
        return Verdict.ALLOW

    # Priority 4: Warn分岐
    if dec == Decision.WARN:
        # 4a: Self-correction可能 → revise
        if self_correction_count < 2:
            return Verdict.REVISE

        # 4b: 高権限 + uncertainty → require_human
        if permission_level == "admin" and uncertainty_score >= 0.15:
            return Verdict.REQUIRE_HUMAN

        # 4c: Reviewer必須 → require_human
        if approval_summary.required_approvals:
            return Verdict.REQUIRE_HUMAN

        return Verdict.REVISE

    # Priority 5: Hold分岐
    if dec == Decision.HOLD:
        # 5a: Approval欠落 → needs_approval
        if approval_summary.missing_approvals:
            return Verdict.NEEDS_APPROVAL

        # 5b: 判断欠落 → require_human
        if uncertainty_score >= 0.25:
            return Verdict.REQUIRE_HUMAN

        # 5c: SLA timeout → deny
        if sla_status == "timeout":
            return Verdict.DENY

        # 5d: Reviewer pending → needs_approval (default)
        return Verdict.NEEDS_APPROVAL

    # Default fallback
    return Verdict.ALLOW


class VerdictTransformer:
    """
    Verdict transformer class.

    Provides verdict transformation with context assembly.
    """

    def transform(
        self,
        decision_packet: dict[str, Any],
        stale_result: dict[str, Any],
        obligation_result: dict[str, Any],
        approval_result: dict[str, Any],
        evidence_result: dict[str, Any]
    ) -> TransformContext:
        """
        Transform DecisionPacket to verdict with full context.

        Args:
            decision_packet: DecisionPacket from agent-gatefield.
            stale_result: Stale check result from memx-resolver.
            obligation_result: Obligation check result.
            approval_result: Approval check result.
            evidence_result: Evidence report from workflow-cookbook.

        Returns:
            TransformContext with verdict and reason.
        """
        # Extract decision from packet
        decision = decision_packet.get("decision", "pass")

        # Build summaries
        stale_summary = self._build_stale_summary(stale_result)
        obligation_summary = self._build_obligation_summary(obligation_result)
        approval_summary = self._build_approval_summary(approval_result)
        evidence_summary = self._build_evidence_summary(evidence_result)

        # Extract metadata from packet
        permission_level = self._derive_permission_level(decision_packet)
        uncertainty_score = decision_packet.get("composite_score", 0.0)
        self_correction_count = decision_packet.get("self_correction_count", 0)

        # Resolve verdict
        verdict = resolve_verdict(
            decision=decision,
            stale_summary=stale_summary,
            obligation_summary=obligation_summary,
            approval_summary=approval_summary,
            evidence_summary=evidence_summary,
            permission_level=permission_level,
            uncertainty_score=uncertainty_score,
            self_correction_count=self_correction_count,
            sla_status="pending"
        )

        # Build reason string
        reason = self._build_verdict_reason(
            verdict, decision, stale_summary, obligation_summary,
            approval_summary, evidence_summary
        )

        return TransformContext(
            decision=Decision(decision),
            stale_summary=stale_summary,
            obligation_summary=obligation_summary,
            approval_summary=approval_summary,
            evidence_summary=evidence_summary,
            final_verdict=verdict,
            permission_level=permission_level,
            uncertainty_score=uncertainty_score,
            self_correction_count=self_correction_count,
            verdict_reason=reason
        )

    def _build_stale_summary(self, stale_result: dict) -> StaleSummary:
        """Build StaleSummary from stale check result."""
        return StaleSummary(
            fresh=stale_result.get("fresh", True),
            stale_items=stale_result.get("stale_items", []),
            stale_reasons=stale_result.get("stale_reasons", [])
        )

    def _build_obligation_summary(self, obligation_result: dict) -> ObligationSummary:
        """Build ObligationSummary from obligation check result."""
        fulfillment_rate = obligation_result.get("fulfillment_rate", 1.0)
        unfulfilled = obligation_result.get("unfulfilled_items", [])

        # Determine severity levels
        has_critical = any(
            item.get("severity") == "critical" for item in unfulfilled
        )
        has_high = any(
            item.get("severity") == "high" for item in unfulfilled
        )

        return ObligationSummary(
            fulfillment_rate=fulfillment_rate,
            has_critical_unfulfilled=has_critical,
            has_high_unfulfilled=has_high,
            unfulfilled_items=unfulfilled
        )

    def _build_approval_summary(self, approval_result: dict) -> ApprovalSummary:
        """Build ApprovalSummary from approval check result."""
        return ApprovalSummary(
            missing_approvals=approval_result.get("missing_approvals", []),
            required_approvals=approval_result.get("required_approvals", []),
            approved_roles=approval_result.get("approved_roles", []),
            approval_rate=approval_result.get("approval_rate", 1.0)
        )

    def _build_evidence_summary(self, evidence_result: dict) -> EvidenceSummary:
        """Build EvidenceSummary from evidence report."""
        # Calculate evidence strength
        required = evidence_result.get("required_evidence", [])
        collected = evidence_result.get("collected_evidence", [])

        if not required:
            strength = 1.0
        else:
            strength = len(collected) / len(required)

        return EvidenceSummary(
            evidence_strength=strength,
            required_evidence=required,
            collected_evidence=collected,
            unlinked_evidence=evidence_result.get("unlinked_evidence", [])
        )

    def _derive_permission_level(self, decision_packet: dict) -> str:
        """Derive permission level from DecisionPacket."""
        # Check for hard override indicators
        if decision_packet.get("hard_override"):
            return "admin"

        # Check factors for high privilege
        factors = decision_packet.get("factors", [])
        for factor in factors:
            if factor.get("name") == "uncertainty_score" and factor.get("value") >= 0.15:
                return "elevated"

        return "standard"

    def _build_verdict_reason(
        self,
        verdict: Verdict,
        decision: str,
        stale_summary: StaleSummary,
        obligation_summary: ObligationSummary,
        approval_summary: ApprovalSummary,
        evidence_summary: EvidenceSummary
    ) -> str:
        """Build human-readable verdict reason."""
        reasons = []

        if verdict == Verdict.DENY:
            if decision == "block":
                reasons.append("Gate decision blocked")
            elif obligation_summary.has_critical_unfulfilled:
                reasons.append("Critical obligation unfulfilled")
            elif stale_summary.stale_reasons:
                reasons.append("Stale detection")
        elif verdict == Verdict.STALE_BLOCKED:
            reasons.append(f"Stale detected: {', '.join(stale_summary.stale_reasons)}")
        elif verdict == Verdict.NEEDS_APPROVAL:
            if evidence_summary.evidence_strength < 0.85:
                reasons.append("Evidence insufficient")
            if approval_summary.missing_approvals:
                reasons.append(f"Missing approvals: {', '.join(approval_summary.missing_approvals)}")
        elif verdict == Verdict.REQUIRE_HUMAN:
            reasons.append("Requires human review")
        elif verdict == Verdict.REVISE:
            reasons.append("Self-correction recommended")
        elif verdict == Verdict.ALLOW:
            reasons.append("All checks passed")

        return "; ".join(reasons) if reasons else "No reason specified"


def get_verdict_priority(verdict: Verdict) -> int:
    """
    Get priority level for verdict (higher = more restrictive).

    Args:
        verdict: Verdict enum value.

    Returns:
        Priority integer (1-6).
    """
    priorities = {
        Verdict.ALLOW: 1,
        Verdict.REVISE: 2,
        Verdict.NEEDS_APPROVAL: 3,
        Verdict.REQUIRE_HUMAN: 4,
        Verdict.STALE_BLOCKED: 5,
        Verdict.DENY: 6,
    }
    return priorities.get(verdict, 1)
