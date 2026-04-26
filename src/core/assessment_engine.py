"""
AssessmentEngine Module

Core engine for assembling Assessment from DecisionPacket + obligation + stale + approval + evidence.
Manages Assessment lifecycle and storage.

Reference: architecture.md Section 4 (Assessment構造)
Reference: BLUEPRINT.md Section 5.1 (Assessment assembly)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..common import (
    generate_assessment_id,
    hash_dict,
    utc_now,
)
from ..typed_ref import (
    assessment_ref,
    decision_ref,
    format_ref,
    parse_ref,
    run_ref,
    task_ref,
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


class AssessmentStore:
    """
    In-memory assessment store for MVP.

    Stores Assessment canonical copies in agent-state-gate.
    Future: Replace with persistent DB backend.
    """

    def __init__(self):
        self._assessments: dict[str, Assessment] = {}

    def save(self, assessment: Assessment) -> str:
        """
        Save assessment to store.

        Args:
            assessment: Assessment instance.

        Returns:
            assessment_ref (typed_ref format).
        """
        self._assessments[assessment.assessment_id] = assessment
        return assessment_ref(assessment.assessment_id)

    def get(self, assessment_ref_str: str) -> Assessment | None:
        """
        Get assessment by typed_ref.

        Args:
            assessment_ref_str: Assessment typed_ref string.

        Returns:
            Assessment instance or None if not found.
        """
        try:
            parsed = parse_ref(assessment_ref_str)
            return self._assessments.get(parsed.entity_id)
        except ValueError:
            return None

    def get_by_id(self, assessment_id: str) -> Assessment | None:
        """
        Get assessment by ID.

        Args:
            assessment_id: Assessment ID string.

        Returns:
            Assessment instance or None.
        """
        return self._assessments.get(assessment_id)

    def list_by_task(self, task_id: str) -> list[Assessment]:
        """
        List assessments for a task.

        Args:
            task_id: Task ID.

        Returns:
            List of assessments for task.
        """
        return [
            a for a in self._assessments.values()
            if a.task_id == task_id
        ]

    def list_by_run(self, run_id: str) -> list[Assessment]:
        """
        List assessments for a run.

        Args:
            run_id: Run ID.

        Returns:
            List of assessments for run.
        """
        return [
            a for a in self._assessments.values()
            if a.run_id == run_id
        ]


class AssessmentEngine:
    """
    Engine for assembling Assessment from multiple sources.

    Capabilities:
    - Assemble assessment from DecisionPacket + summaries
    - Generate causal trace with contribution weights
    - Generate counterfactuals for decision explanation
    - Store and retrieve assessments
    """

    def __init__(self):
        self._store = AssessmentStore()
        self._transformer = VerdictTransformer()

    @property
    def store(self) -> AssessmentStore:
        """Get assessment store."""
        return self._store

    def assemble_assessment(
        self,
        decision_packet: dict[str, Any],
        task_data: dict[str, Any],
        run_data: dict[str, Any],
        stale_result: dict[str, Any],
        obligation_result: dict[str, Any],
        approval_result: dict[str, Any],
        evidence_result: dict[str, Any],
        context_bundle: dict[str, Any],
        threshold_version: str = ""
    ) -> Assessment:
        """
        Assemble assessment from all components.

        Args:
            decision_packet: DecisionPacket from agent-gatefield.
            task_data: Task data from agent-taskstate.
            run_data: Run data from agent-taskstate.
            stale_result: Stale check result from memx-resolver.
            obligation_result: Obligation check result.
            approval_result: Approval check result.
            evidence_result: Evidence report from workflow-cookbook.
            context_bundle: ContextBundle from agent-taskstate.
            threshold_version: Threshold config version hash.

        Returns:
            Assessment instance.

        Raises:
            AssessmentError: If assembly fails.
        """
        # Generate assessment ID
        assessment_id = self._generate_assessment_id()

        # Transform decision to verdict
        transform_context = self._transformer.transform(
            decision_packet=decision_packet,
            stale_result=stale_result,
            obligation_result=obligation_result,
            approval_result=approval_result,
            evidence_result=evidence_result
        )

        # Build causal trace
        causal_trace = self._build_causal_trace(
            decision_packet=decision_packet,
            stale_result=stale_result,
            obligation_result=obligation_result,
            approval_result=approval_result,
            evidence_result=evidence_result,
            final_verdict=transform_context.final_verdict
        )

        # Build counterfactuals
        counterfactuals = self._build_counterfactuals(
            transform_context=transform_context,
            stale_result=stale_result,
            obligation_result=obligation_result,
            approval_result=approval_result,
            evidence_result=evidence_result
        )

        # Build context hash
        context_hash = self._build_context_hash(
            decision_packet=decision_packet,
            stale_result=stale_result,
            obligation_result=obligation_result,
            approval_result=approval_result,
            evidence_result=evidence_result
        )

        # Create assessment
        assessment = Assessment(
            assessment_id=assessment_id,
            decision_packet_ref=decision_ref(
                decision_packet.get("decision_id", "")
            ),
            task_id=task_ref(task_data.get("task_id", "")),
            run_id=run_ref(run_data.get("run_id", "")),
            stage=run_data.get("stage", "unknown"),
            context_bundle_ref=format_ref(
                "agent-taskstate",
                "context_bundle",
                "local",
                context_bundle.get("bundle_id", "")
            ),
            stale_summary=transform_context.stale_summary,
            obligation_summary=transform_context.obligation_summary,
            approval_summary=transform_context.approval_summary,
            evidence_summary=transform_context.evidence_summary,
            final_verdict=transform_context.final_verdict,
            verdict_reason=transform_context.verdict_reason,
            causal_trace=causal_trace,
            counterfactuals=counterfactuals,
            threshold_version=threshold_version or decision_packet.get("threshold_version", ""),
            context_hash=context_hash,
            diff_hash=self._extract_diff_hash(decision_packet),
        )

        # Save to store
        self._store.save(assessment)

        return assessment

    def get_assessment(self, assessment_ref: str) -> Assessment | None:
        """
        Get assessment by typed_ref.

        Args:
            assessment_ref: Assessment typed_ref string.

        Returns:
            Assessment instance or None.
        """
        return self._store.get(assessment_ref)

    def list_assessments_by_task(self, task_id: str) -> list[Assessment]:
        """
        List assessments for task.

        Args:
            task_id: Task ID.

        Returns:
            List of assessments.
        """
        return self._store.list_by_task(task_id)

    def list_assessments_by_run(self, run_id: str) -> list[Assessment]:
        """
        List assessments for run.

        Args:
            run_id: Run ID.

        Returns:
            List of assessments.
        """
        return self._store.list_by_run(run_id)

    def _generate_assessment_id(self) -> str:
        """Generate unique assessment ID."""
        return generate_assessment_id()

    def _build_causal_trace(
        self,
        decision_packet: dict,
        stale_result: dict,
        obligation_result: dict,
        approval_result: dict,
        evidence_result: dict,
        final_verdict: Verdict
    ) -> list[CausalStep]:
        """
        Build causal trace from decision sources.

        Reference: architecture.md lines 203-274
        """
        steps = []
        step_counter = 0

        # Step from gatefield decision
        step_counter += 1
        gatefield_step = CausalStep(
            step_id=f"STEP-{step_counter:03d}",
            source="gatefield",
            rule_id=self._extract_rule_id(decision_packet),
            input_state={"decision": decision_packet.get("decision")},
            output_state={"composite_score": decision_packet.get("composite_score")},
            contribution_weight=self._calculate_gatefield_weight(final_verdict),
            rationale=self._build_gatefield_rationale(decision_packet)
        )
        steps.append(gatefield_step)

        # Step from stale check
        if not stale_result.get("fresh"):
            step_counter += 1
            stale_step = CausalStep(
                step_id=f"STEP-{step_counter:03d}",
                source="stale_check",
                rule_id="stale_detected",
                input_state={"expected_versions": []},
                output_state={"stale_items": stale_result.get("stale_items", [])},
                contribution_weight=self._calculate_stale_weight(final_verdict),
                rationale=f"Stale detected: {', '.join(stale_result.get('stale_reasons', []))}"
            )
            steps.append(stale_step)

        # Step from obligation check
        if obligation_result.get("fulfillment_rate", 1.0) < 1.0:
            step_counter += 1
            obligation_step = CausalStep(
                step_id=f"STEP-{step_counter:03d}",
                source="obligation_check",
                rule_id="obligation_gap",
                input_state={"expected_rate": 1.0},
                output_state={"fulfillment_rate": obligation_result.get("fulfillment_rate")},
                contribution_weight=self._calculate_obligation_weight(final_verdict, obligation_result),
                rationale=f"Obligation gap: {obligation_result.get('fulfillment_rate'):.2%}"
            )
            steps.append(obligation_step)

        # Step from approval check
        if approval_result.get("missing_approvals"):
            step_counter += 1
            approval_step = CausalStep(
                step_id=f"STEP-{step_counter:03d}",
                source="approval_check",
                rule_id="approval_missing",
                input_state={"required": approval_result.get("required_approvals", [])},
                output_state={"missing": approval_result.get("missing_approvals", [])},
                contribution_weight=self._calculate_approval_weight(final_verdict),
                rationale=f"Missing approvals: {', '.join(approval_result.get('missing_approvals', []))}"
            )
            steps.append(approval_step)

        # Step from evidence check
        if evidence_result.get("evidence_strength", 1.0) < 0.85:
            step_counter += 1
            evidence_step = CausalStep(
                step_id=f"STEP-{step_counter:03d}",
                source="evidence_check",
                rule_id="evidence_gap",
                input_state={"target_strength": 0.85},
                output_state={"evidence_strength": evidence_result.get("evidence_strength")},
                contribution_weight=self._calculate_evidence_weight(final_verdict),
                rationale=f"Evidence strength: {evidence_result.get('evidence_strength'):.2%}"
            )
            steps.append(evidence_step)

        # Normalize weights
        total_weight = sum(s.contribution_weight for s in steps)
        if total_weight > 0:
            for step in steps:
                step.contribution_weight = step.contribution_weight / total_weight

        return steps

    def _build_counterfactuals(
        self,
        transform_context: TransformContext,
        stale_result: dict,
        obligation_result: dict,
        approval_result: dict,
        evidence_result: dict
    ) -> list[Counterfactual]:
        """Build counterfactual conditions for decision explanation."""
        counterfactuals = []
        counterfactual_counter = 0

        # Counterfactual: if stale were fresh
        if not stale_result.get("fresh", True):
            counterfactual_counter += 1
            counterfactuals.append(Counterfactual(
                counterfactual_id=f"CF-{counterfactual_counter:03d}",
                condition="if stale items were refreshed",
                alternative_verdict=Verdict.ALLOW if transform_context.decision == Decision.PASS else Verdict.NEEDS_APPROVAL,
                required_action="Update docs/approvals to current versions",
                feasibility="easy"
            ))

        # Counterfactual: if evidence were complete
        if evidence_result.get("evidence_strength", 1.0) < 0.85:
            counterfactual_counter += 1
            counterfactuals.append(Counterfactual(
                counterfactual_id=f"CF-{counterfactual_counter:03d}",
                condition="if evidence were complete",
                alternative_verdict=Verdict.ALLOW,
                required_action="Add missing evidence items",
                feasibility="medium"
            ))

        # Counterfactual: if approvals were present
        if approval_result.get("missing_approvals"):
            counterfactual_counter += 1
            counterfactuals.append(Counterfactual(
                counterfactual_id=f"CF-{counterfactual_counter:03d}",
                condition="if missing approvals were granted",
                alternative_verdict=Verdict.ALLOW,
                required_action="Obtain approvals from: " + ", ".join(approval_result.get("missing_approvals", [])),
                feasibility="medium"
            ))

        return counterfactuals

    def _build_context_hash(
        self,
        decision_packet: dict,
        stale_result: dict,
        obligation_result: dict,
        approval_result: dict,
        evidence_result: dict
    ) -> str:
        """Build context hash for replay reproducibility."""
        context_data = {
            "decision_id": decision_packet.get("decision_id"),
            "threshold_version": decision_packet.get("threshold_version"),
            "stale_fresh": stale_result.get("fresh"),
            "obligation_rate": obligation_result.get("fulfillment_rate"),
            "approval_missing": approval_result.get("missing_approvals"),
            "evidence_strength": evidence_result.get("evidence_strength"),
        }
        return hash_dict(context_data)

    def _extract_diff_hash(self, decision_packet: dict) -> str:
        """Extract diff hash from current or legacy DecisionPacket shapes."""
        artifact_ref = decision_packet.get("artifact_ref")
        if isinstance(artifact_ref, dict) and artifact_ref.get("diff_hash"):
            return artifact_ref["diff_hash"]
        return decision_packet.get("diff_hash", "")

    def _extract_rule_id(self, decision_packet: dict) -> str:
        """Extract primary rule ID from DecisionPacket."""
        factors = decision_packet.get("factors", [])
        if factors:
            # Get highest contributing factor
            sorted_factors = sorted(
                factors,
                key=lambda f: f.get("contribution", 0),
                reverse=True
            )
            return sorted_factors[0].get("name", "unknown")
        return "unknown"

    def _build_gatefield_rationale(self, decision_packet: dict) -> str:
        """Build rationale from DecisionPacket."""
        decision = decision_packet.get("decision", "pass")
        score = decision_packet.get("composite_score", 0)

        factors = decision_packet.get("factors", [])
        top_factors = sorted(
            factors,
            key=lambda f: f.get("contribution", 0),
            reverse=True
        )[:3]

        factor_names = [f.get("name") for f in top_factors]
        return f"Decision {decision}, score {score:.2f}, factors: {', '.join(factor_names)}"

    def _calculate_gatefield_weight(self, verdict: Verdict) -> float:
        """Calculate gatefield step base weight."""
        base = 0.40
        if verdict in [Verdict.DENY, Verdict.STALE_BLOCKED]:
            return base * 1.5
        return base

    def _calculate_stale_weight(self, verdict: Verdict) -> float:
        """Calculate stale step weight."""
        base = 0.20
        if verdict == Verdict.STALE_BLOCKED:
            return base * 1.5
        return base

    def _calculate_obligation_weight(self, verdict: Verdict, obligation_result: dict) -> float:
        """Calculate obligation step weight."""
        base = 0.15
        unfulfilled = obligation_result.get("unfulfilled_items", [])
        has_critical = any(i.get("severity") == "critical" for i in unfulfilled)
        if has_critical:
            return base * 1.5
        return base

    def _calculate_approval_weight(self, verdict: Verdict) -> float:
        """Calculate approval step weight."""
        base = 0.15
        return base

    def _calculate_evidence_weight(self, verdict: Verdict) -> float:
        """Calculate evidence step weight."""
        base = 0.10
        return base
