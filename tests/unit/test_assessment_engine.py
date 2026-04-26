"""
Tests for assessment_engine module.

Tests Assessment assembly, storage, and causal trace generation.
Reference: AC-002_assessment_assembly.json, architecture.md
"""


from src.core import (
    ApprovalSummary,
    Assessment,
    AssessmentEngine,
    AssessmentStore,
    CausalStep,
    Counterfactual,
    EvidenceSummary,
    ObligationSummary,
    StaleSummary,
)
from src.core.verdict_transformer import Verdict


class TestAssessmentStore:
    """Tests for AssessmentStore."""

    def test_save_and_get_assessment(self):
        """Save and retrieve assessment."""
        store = AssessmentStore()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="agent-gatefield:decision:local:01HDEC0001",
            task_id="agent-taskstate:task:local:01HTSK0001",
            run_id="agent-taskstate:run:local:01HRUN0001",
            stage="dev",
            context_bundle_ref="agent-taskstate:context_bundle:local:01HBND0001",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.ALLOW,
            verdict_reason="All checks passed",
        )

        ref = store.save(assessment)
        retrieved = store.get(ref)

        assert retrieved is not None
        assert retrieved.assessment_id == "01HASM0001"

    def test_get_by_id(self):
        """Get assessment by ID directly."""
        store = AssessmentStore()

        assessment = Assessment(
            assessment_id="01HASM0002",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.ALLOW,
            verdict_reason="test",
        )

        store.save(assessment)
        retrieved = store.get_by_id("01HASM0002")

        assert retrieved is not None
        assert retrieved.assessment_id == "01HASM0002"

    def test_list_by_task(self):
        """List assessments for task."""
        store = AssessmentStore()

        # Add multiple assessments
        for i in range(3):
            assessment = Assessment(
                assessment_id=f"01HASM{i:04d}",
                decision_packet_ref="",
                task_id="task-001",
                run_id=f"run-{i}",
                stage="dev",
                context_bundle_ref="",
                stale_summary=StaleSummary(fresh=True),
                obligation_summary=ObligationSummary(fulfillment_rate=1.0),
                approval_summary=ApprovalSummary(missing_approvals=[]),
                evidence_summary=EvidenceSummary(evidence_strength=1.0),
                final_verdict=Verdict.ALLOW,
                verdict_reason="test",
            )
            store.save(assessment)

        # Add assessment for different task
        other = Assessment(
            assessment_id="01HASM9999",
            decision_packet_ref="",
            task_id="task-002",
            run_id="run-999",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.ALLOW,
            verdict_reason="test",
        )
        store.save(other)

        task_list = store.list_by_task("task-001")
        assert len(task_list) == 3


class TestAssessmentEngine:
    """Tests for AssessmentEngine."""

    def test_assemble_assessment_basic(self):
        """Assemble basic assessment."""
        engine = AssessmentEngine()

        decision_packet = {
            "decision_id": "01HDEC0001",
            "decision": "pass",
            "composite_score": 0.9,
            "threshold_version": "sha256:test",
            "factors": [],
        }
        task_data = {"task_id": "01HTSK0001"}
        run_data = {"run_id": "01HRUN0001", "stage": "dev"}
        stale_result = {"fresh": True, "stale_items": []}
        obligation_result = {"fulfillment_rate": 1.0}
        approval_result = {"missing_approvals": [], "required_approvals": []}
        evidence_result = {"evidence_strength": 1.0}
        context_bundle = {"bundle_id": "01HBND0001"}

        assessment = engine.assemble_assessment(
            decision_packet=decision_packet,
            task_data=task_data,
            run_data=run_data,
            stale_result=stale_result,
            obligation_result=obligation_result,
            approval_result=approval_result,
            evidence_result=evidence_result,
            context_bundle=context_bundle,
        )

        assert assessment is not None
        assert assessment.final_verdict == Verdict.ALLOW
        assert assessment.task_id == "agent-taskstate:task:local:01HTSK0001"

    def test_assemble_with_stale(self):
        """Asssemble assessment with stale detection."""
        engine = AssessmentEngine()

        decision_packet = {
            "decision_id": "01HDEC0001",
            "decision": "pass",
            "composite_score": 0.9,
            "factors": [],
        }
        task_data = {"task_id": "01HTSK0001"}
        run_data = {"run_id": "01HRUN0001", "stage": "dev"}
        stale_result = {
            "fresh": False,
            "stale_items": [{"doc_id": "doc-001"}],
            "stale_reasons": ["doc_version_changed"],
        }
        obligation_result = {"fulfillment_rate": 1.0}
        approval_result = {"missing_approvals": []}
        evidence_result = {"evidence_strength": 1.0}
        context_bundle = {"bundle_id": "01HBND0001"}

        assessment = engine.assemble_assessment(
            decision_packet=decision_packet,
            task_data=task_data,
            run_data=run_data,
            stale_result=stale_result,
            obligation_result=obligation_result,
            approval_result=approval_result,
            evidence_result=evidence_result,
            context_bundle=context_bundle,
        )

        assert assessment.final_verdict == Verdict.STALE_BLOCKED

    def test_assemble_creates_causal_trace(self):
        """Assemble creates causal trace."""
        engine = AssessmentEngine()

        decision_packet = {
            "decision_id": "01HDEC0001",
            "decision": "pass",
            "composite_score": 0.9,
            "factors": [{"name": "taboo_proximity", "value": 0.85}],
        }
        task_data = {"task_id": "01HTSK0001"}
        run_data = {"run_id": "01HRUN0001", "stage": "dev"}
        stale_result = {"fresh": True}
        obligation_result = {"fulfillment_rate": 1.0}
        approval_result = {"missing_approvals": []}
        evidence_result = {"evidence_strength": 0.7}  # Insufficient
        context_bundle = {"bundle_id": "01HBND0001"}

        assessment = engine.assemble_assessment(
            decision_packet=decision_packet,
            task_data=task_data,
            run_data=run_data,
            stale_result=stale_result,
            obligation_result=obligation_result,
            approval_result=approval_result,
            evidence_result=evidence_result,
            context_bundle=context_bundle,
        )

        assert len(assessment.causal_trace) > 0
        # Causal trace should have gatefield step
        assert any(s.source == "gatefield" for s in assessment.causal_trace)


class TestCausalStep:
    """Tests for CausalStep."""

    def test_causal_step_creation(self):
        """Create causal step."""
        step = CausalStep(
            step_id="STEP-001",
            source="gatefield",
            rule_id="taboo_warn",
            input_state={"decision": "warn"},
            output_state={"score": 0.85},
            contribution_weight=0.4,
            rationale="Taboo proximity threshold",
        )

        assert step.step_id == "STEP-001"
        assert step.source == "gatefield"
        assert step.contribution_weight == 0.4


class TestCounterfactual:
    """Tests for Counterfactual."""

    def test_counterfactual_creation(self):
        """Create counterfactual."""
        cf = Counterfactual(
            counterfactual_id="CF-001",
            condition="if evidence were complete",
            alternative_verdict=Verdict.ALLOW,
            required_action="Add missing evidence",
            feasibility="medium",
        )

        assert cf.counterfactual_id == "CF-001"
        assert cf.alternative_verdict == Verdict.ALLOW


class TestAssessmentEngineMethods:
    """Tests for additional AssessmentEngine methods."""

    def test_list_assessments_by_task(self):
        """List assessments by task."""
        engine = AssessmentEngine()

        # Create assessment
        decision_packet = {
            "decision_id": "01HDEC0001",
            "decision": "pass",
            "composite_score": 0.9,
            "factors": [],
        }
        task_data = {"task_id": "01HTSK0001"}
        run_data = {"run_id": "01HRUN0001", "stage": "dev"}
        stale_result = {"fresh": True}
        obligation_result = {"fulfillment_rate": 1.0}
        approval_result = {"missing_approvals": []}
        evidence_result = {"evidence_strength": 1.0}
        context_bundle = {"bundle_id": "01HBND0001"}

        engine.assemble_assessment(
            decision_packet=decision_packet,
            task_data=task_data,
            run_data=run_data,
            stale_result=stale_result,
            obligation_result=obligation_result,
            approval_result=approval_result,
            evidence_result=evidence_result,
            context_bundle=context_bundle,
        )

        # list_by_task uses typed_ref format
        from src.typed_ref import task_ref
        assessments = engine.list_assessments_by_task(task_ref("01HTSK0001"))
        assert len(assessments) >= 1

    def test_get_assessment(self):
        """Get assessment by typed_ref."""
        engine = AssessmentEngine()

        decision_packet = {
            "decision_id": "01HDEC0002",
            "decision": "pass",
            "composite_score": 0.9,
            "factors": [],
        }
        task_data = {"task_id": "01HTSK0002"}
        run_data = {"run_id": "01HRUN0002", "stage": "dev"}
        stale_result = {"fresh": True}
        obligation_result = {"fulfillment_rate": 1.0}
        approval_result = {"missing_approvals": []}
        evidence_result = {"evidence_strength": 1.0}
        context_bundle = {"bundle_id": "01HBND0002"}

        assessment = engine.assemble_assessment(
            decision_packet=decision_packet,
            task_data=task_data,
            run_data=run_data,
            stale_result=stale_result,
            obligation_result=obligation_result,
            approval_result=approval_result,
            evidence_result=evidence_result,
            context_bundle=context_bundle,
        )

        from src.typed_ref import assessment_ref
        retrieved = engine.get_assessment(assessment_ref(assessment.assessment_id))
        assert retrieved is not None
        assert retrieved.assessment_id == assessment.assessment_id

    def test_assemble_with_obligation_failure(self):
        """Assemble with obligation failure returns DENY."""
        engine = AssessmentEngine()

        decision_packet = {
            "decision_id": "01HDEC0003",
            "decision": "pass",
            "composite_score": 0.9,
            "factors": [],
        }
        task_data = {"task_id": "01HTSK0003"}
        run_data = {"run_id": "01HRUN0003", "stage": "dev"}
        stale_result = {"fresh": True}
        obligation_result = {"fulfillment_rate": 0.0}  # Failed
        approval_result = {"missing_approvals": []}
        evidence_result = {"evidence_strength": 1.0}
        context_bundle = {"bundle_id": "01HBND0003"}

        assessment = engine.assemble_assessment(
            decision_packet=decision_packet,
            task_data=task_data,
            run_data=run_data,
            stale_result=stale_result,
            obligation_result=obligation_result,
            approval_result=approval_result,
            evidence_result=evidence_result,
            context_bundle=context_bundle,
        )

        # Low obligation should trigger verdict based on decision
        assert assessment.final_verdict in [Verdict.DENY, Verdict.REQUIRE_HUMAN, Verdict.NEEDS_APPROVAL]


class TestAssessment:
    """Tests for Assessment dataclass."""

    def test_assessment_creation(self):
        """Create assessment."""
        from src.core.verdict_transformer import (
            ApprovalSummary,
            EvidenceSummary,
            ObligationSummary,
            StaleSummary,
        )

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="ref",
            task_id="task",
            run_id="run",
            stage="dev",
            context_bundle_ref="bundle",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.ALLOW,
            verdict_reason="All passed",
        )

        assert assessment.assessment_id == "01HASM0001"
        assert assessment.final_verdict == Verdict.ALLOW

    def test_assessment_has_timestamps(self):
        """Assessment has created_at and updated_at."""
        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="",
            run_id="",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.ALLOW,
            verdict_reason="test",
        )

        assert assessment.created_at is not None
        assert assessment.updated_at is not None
