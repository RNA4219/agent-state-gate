"""
Assessment Types

Dataclasses for Assessment structure.
Reference: architecture.md Section 4 (Assessment構造)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.common import utc_now
from src.core.verdict_transformer import (
    ApprovalSummary,
    EvidenceSummary,
    ObligationSummary,
    StaleSummary,
    Verdict,
)


@dataclass
class CausalStep:
    """
    Causal step in assessment decision trace.

    Each step represents a decision point with contribution to final verdict.
    """
    step_id: str
    source: str  # gatefield | stale_check | obligation_check | approval_check | evidence_check
    rule_id: str = ""
    input_state: dict[str, Any] = field(default_factory=dict)
    output_state: dict[str, Any] = field(default_factory=dict)
    contribution_weight: float = 0.0
    rationale: str = ""


@dataclass
class Counterfactual:
    """
    Counterfactual condition showing alternative verdict path.

    "What if X were Y" scenarios for decision explanation.
    """
    counterfactual_id: str
    condition: str
    alternative_verdict: Verdict
    required_action: str
    feasibility: str  # easy | medium | hard | impossible


@dataclass
class Assessment:
    """
    Integrated assessment unit.

    Combines DecisionPacket + stale + obligation + approval + evidence
    into single assessment with verdict and causal trace.

    Reference: architecture.md lines 179-201
    """
    assessment_id: str
    decision_packet_ref: str
    task_id: str
    run_id: str
    stage: str
    context_bundle_ref: str

    stale_summary: StaleSummary
    obligation_summary: ObligationSummary
    approval_summary: ApprovalSummary
    evidence_summary: EvidenceSummary

    final_verdict: Verdict
    verdict_reason: str
    causal_trace: list[CausalStep] = field(default_factory=list)
    counterfactuals: list[Counterfactual] = field(default_factory=list)

    audit_packet_ref: str = ""
    threshold_version: str = ""
    context_hash: str = ""
    diff_hash: str = ""

    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


__all__ = [
    "CausalStep",
    "Counterfactual",
    "Assessment",
]