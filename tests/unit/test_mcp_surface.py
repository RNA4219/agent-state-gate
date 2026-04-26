"""
Unit tests for MCP Surface.

Tests context.recall, gate.evaluate, stale_check, state_gate.assess,
and attention.list APIs.
"""

from unittest.mock import MagicMock

import pytest

from src.adapters import AdapterRegistry
from src.api.mcp_surface import (
    AttentionListResult,
    ContractRef,
    DocRef,
    EvaluateResult,
    MCPSurface,
    RecallResult,
    ReplayContextResult,
    SLAStatus,
    StaleCheckResult,
    StateGateAssessResult,
    create_mcp_surface,
)
from src.core.verdict_transformer import Verdict


class TestDocRef:
    def test_doc_ref_creation(self):
        ref = DocRef(
            doc_id="DOC-001",
            version="v1",
            priority="required",
            doc_type="spec",
            title="Test Document"
        )
        assert ref.doc_id == "DOC-001"
        assert ref.priority == "required"


class TestContractRef:
    def test_contract_ref_creation(self):
        ref = ContractRef(
            contract_id="CTR-001",
            contract_type="Intent",
            version="v1"
        )
        assert ref.contract_id == "CTR-001"
        assert ref.contract_type == "Intent"


class TestRecallResult:
    def test_recall_result_creation(self):
        from src.core.assessment_engine import StaleSummary
        stale = StaleSummary(fresh=True, stale_items=[], stale_reasons=[])
        result = RecallResult(
            required_docs=[],
            recommended_docs=[],
            contract_refs=[],
            stale_summary=stale,
            ack_required=False
        )
        assert result.required_docs == []
        assert result.ack_required is False


class TestEvaluateResult:
    def test_evaluate_result_creation(self):
        result = EvaluateResult(
            verdict=Verdict.ALLOW,
            required_evidence=[],
            required_approvals=[],
            missing_approvals=[],
            assessment_id="ASM-001",
            causal_trace=["trace1"],
            verdict_reason="All checks passed"
        )
        assert result.verdict == Verdict.ALLOW
        assert result.assessment_id == "ASM-001"


class TestStaleCheckResult:
    def test_stale_check_result_creation(self):
        from src.common import utc_now
        result = StaleCheckResult(
            fresh=True,
            stale_items=[],
            stale_reasons=[],
            last_check_at=utc_now()
        )
        assert result.fresh is True


class TestStateGateAssessResult:
    def test_state_gate_assess_result_creation(self):
        result = StateGateAssessResult(
            assessment_id="ASM-001",
            decision_packet_ref="DEC-001",
            scores={"taboo": 0.1, "drift": 0.2},
            recommendation="allow",
            human_queue_required=False,
            exemplar_refs=["EX-001"],
            threshold_version="v1"
        )
        assert result.assessment_id == "ASM-001"
        assert result.human_queue_required is False


class TestSLAStatus:
    def test_sla_status_creation(self):
        status = SLAStatus(
            pending_count=5,
            ack_timeout_count=0,
            decision_timeout_count=0,
            escalated_count=0
        )
        assert status.pending_count == 5


class TestAttentionListResult:
    def test_attention_list_result_creation(self):
        result = AttentionListResult(
            items=[],
            total_pending=0,
            by_severity={"critical": 0, "high": 0},
            sla_status={"critical": SLAStatus(0, 0, 0, 0)}
        )
        assert result.items == []
        assert result.total_pending == 0


class TestReplayContextResult:
    def test_replay_context_result_creation(self):
        result = ReplayContextResult(
            run_id="RUN-001",
            context_snapshot={},
            decision_packet={},
            assessment={},
            audit_packet_ref="AUD-001",
            attestation_hash="hash123"
        )
        assert result.run_id == "RUN-001"
        assert result.reproducibility_verified is True


class TestMCPSurfaceCreation:
    def test_mcp_surface_creation(self):
        registry = AdapterRegistry()
        engine = MagicMock()
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        assert surface is not None


class TestMCPSurfaceContextRecall:
    def test_context_recall_no_memx_adapter(self):
        registry = AdapterRegistry()
        engine = MagicMock()
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)

        from src.adapters.base import AdapterUnavailableError
        with pytest.raises(AdapterUnavailableError):
            surface.context_recall("TASK-001", "edit_repo")

    def test_context_recall_with_mock_adapter(self):
        registry = AdapterRegistry()
        mock_memx = MagicMock()
        mock_memx.name = "memx"
        mock_memx.resolve_docs = MagicMock(return_value={
            "required_docs": [{"doc_id": "DOC-001", "version": "v1"}],
            "recommended_docs": [],
            "contract_refs": []
        })
        registry.register(mock_memx)

        engine = MagicMock()
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.context_recall("TASK-001", "edit_repo")

        assert len(result.required_docs) == 1
        assert result.required_docs[0].doc_id == "DOC-001"


class TestMCPSurfaceGateEvaluate:
    def test_gate_evaluate_returns_result_without_adapter(self):
        registry = AdapterRegistry()
        engine = MagicMock()
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.gate_evaluate("TASK-001", "edit_repo", ["read_repo"])

        # Without gatefield adapter, returns ALLOW verdict in advisory mode
        assert result.verdict == Verdict.ALLOW

    def test_gate_evaluate_with_stale_items(self):
        registry = AdapterRegistry()
        mock_memx = MagicMock()
        mock_memx.name = "memx"
        mock_memx.stale_check = MagicMock(return_value={
            "fresh": False,
            "stale_items": [{"doc_id": "DOC-001"}],
            "stale_reasons": ["version mismatch"]
        })
        registry.register(mock_memx)

        engine = MagicMock()
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.gate_evaluate("TASK-001", "edit_repo", ["read_repo"])

        assert result.verdict == Verdict.STALE_BLOCKED

    def test_gate_evaluate_with_missing_approvals(self):
        registry = AdapterRegistry()
        mock_protocols = MagicMock()
        mock_protocols.name = "protocols"
        mock_protocols.derive_risk_level = MagicMock(return_value="high")
        mock_protocols.derive_required_approvals = MagicMock(return_value=["security_reviewer"])
        registry.register(mock_protocols)

        engine = MagicMock()
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.gate_evaluate("TASK-001", "edit_repo", ["write_repo"])

        assert result.verdict == Verdict.NEEDS_APPROVAL


class TestMCPSurfaceStaleCheck:
    def test_stale_check_returns_fresh_when_no_adapter(self):
        registry = AdapterRegistry()
        engine = MagicMock()
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.context_stale_check("TASK-001")

        assert result.fresh is True

    def test_stale_check_with_memx_adapter(self):
        registry = AdapterRegistry()
        mock_memx = MagicMock()
        mock_memx.name = "memx"
        mock_memx.stale_check = MagicMock(return_value={
            "fresh": False,
            "stale_items": [{"doc_id": "DOC-001"}],
            "stale_reasons": ["version mismatch"]
        })
        registry.register(mock_memx)

        engine = MagicMock()
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.context_stale_check("TASK-001")

        assert result.fresh is False
        assert len(result.stale_items) == 1


class TestMCPSurfaceStateGateAssess:
    def test_state_gate_assess_returns_result_without_adapter(self):
        registry = AdapterRegistry()
        engine = MagicMock()
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.state_gate_assess(["art://test"], "diff", "RUN-001", "dev")

        # Returns assessment_id without real adapter
        assert result.assessment_id is not None


class TestMCPSurfaceAttentionList:
    def test_attention_list_empty(self):
        registry = AdapterRegistry()
        engine = MagicMock()
        queue = MagicMock()
        queue.list_items = MagicMock(return_value=[])
        queue.get_pending_items = MagicMock(return_value=[])
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.attention_list()

        assert result.items == []
        assert result.total_pending == 0

    def test_attention_list_with_status_filter(self):
        registry = AdapterRegistry()
        engine = MagicMock()
        queue = MagicMock()
        queue.list_items = MagicMock(return_value=[])
        queue.get_pending_items = MagicMock(return_value=[])
        queue.get_items_by_reviewer = MagicMock(return_value=[])
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.attention_list(status="pending")

        assert result.items == []

    def test_attention_list_with_role_filter(self):
        registry = AdapterRegistry()
        engine = MagicMock()
        queue = MagicMock()
        queue.list_items = MagicMock(return_value=[])
        queue.get_pending_items = MagicMock(return_value=[])
        queue.get_items_by_reviewer = MagicMock(return_value=[])
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.attention_list(reviewer_role="security_reviewer")

        assert result.items == []


class TestMCPSurfaceStateGateAssessWithAdapters:
    def test_state_gate_assess_with_gatefield_adapter(self):
        registry = AdapterRegistry()
        mock_gatefield = MagicMock()
        mock_gatefield.name = "gatefield"
        mock_gatefield.evaluate = MagicMock(return_value={
            "decision_id": "DEC-001",
            "decision": "pass",
            "composite_score": 0.9
        })
        mock_gatefield.get_state_vector = MagicMock(return_value={
            "taboo_proximity": 0.1,
            "scope_drift": 0.2,
            "anomaly_score": 0.05
        })
        registry.register(mock_gatefield)

        engine = MagicMock()
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.state_gate_assess(["art://test"], "diff content", "RUN-001", "dev")

        assert result.decision_packet_ref is not None
        assert result.human_queue_required is False


class TestMCPSurfaceRunReplayContext:
    def test_run_replay_context_without_adapters(self):
        """Run replay context without adapters returns minimal result."""
        registry = AdapterRegistry()
        engine = MagicMock()
        engine.list_assessments_by_run = MagicMock(return_value=[])
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.run_replay_context("RUN-001")

        assert result.run_id == "RUN-001"
        assert result.reproducibility_verified is True

    def test_run_replay_context_with_taskstate_adapter(self):
        """Run replay context with taskstate adapter returns run data."""
        registry = AdapterRegistry()
        mock_taskstate = MagicMock()
        mock_taskstate.name = "taskstate"
        mock_taskstate.get_run = MagicMock(return_value={"run_id": "RUN-001", "stage": "dev"})
        registry.register(mock_taskstate)

        engine = MagicMock()
        engine.list_assessments_by_run = MagicMock(return_value=[])
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.run_replay_context("RUN-001")

        assert result.run_id == "RUN-001"
        assert "run_data" in result.context_snapshot

    def test_run_replay_context_with_gatefield_adapter(self):
        """Run replay context with gatefield adapter returns audit events."""
        registry = AdapterRegistry()
        mock_gatefield = MagicMock()
        mock_gatefield.name = "gatefield"
        mock_gatefield.export_audit = MagicMock(return_value={"audit_events": [{"event": "test"}]})
        registry.register(mock_gatefield)

        engine = MagicMock()
        engine.list_assessments_by_run = MagicMock(return_value=[])
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.run_replay_context("RUN-001")

        assert result.run_id == "RUN-001"
        assert result.context_snapshot["audit_events_count"] == 1

    def test_run_replay_context_with_assessment(self):
        """Run replay context with assessment returns assessment data."""
        registry = AdapterRegistry()
        mock_assessment = MagicMock()
        mock_assessment.assessment_id = "ASM-001"
        mock_assessment.final_verdict = MagicMock(value="allow")
        mock_assessment.verdict_reason = "All passed"
        mock_assessment.threshold_version = "v1"
        mock_assessment.context_hash = "hash123"

        engine = MagicMock()
        engine.list_assessments_by_run = MagicMock(return_value=[mock_assessment])
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.run_replay_context("RUN-001")

        assert result.assessment["assessment_id"] == "ASM-001"
        assert result.audit_packet_ref != ""

    def test_run_replay_context_adapter_error_handling(self):
        """Run replay context handles adapter errors gracefully."""
        registry = AdapterRegistry()
        mock_taskstate = MagicMock()
        mock_taskstate.name = "taskstate"
        mock_taskstate.get_run = MagicMock(side_effect=Exception("error"))
        registry.register(mock_taskstate)

        engine = MagicMock()
        engine.list_assessments_by_run = MagicMock(return_value=[])
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        result = surface.run_replay_context("RUN-001")

        # Should not raise, returns empty result
        assert result.run_id == "RUN-001"


class TestMCPSurfaceHashContext:
    def test_hash_context_generates_hash(self):
        """Hash context generates attestation hash."""
        registry = AdapterRegistry()
        engine = MagicMock()
        queue = MagicMock()
        recorder = MagicMock()

        surface = MCPSurface(registry, engine, queue, recorder)
        hash_result = surface._hash_context(
            {"run_id": "RUN-001"},
            {"decision": "pass"},
            {"assessment_id": "ASM-001"}
        )

        assert hash_result is not None
        assert len(hash_result) > 0


class TestCreateMCPSurface:
    def test_create_mcp_surface_default(self):
        """Create MCP surface with default components."""
        registry = AdapterRegistry()
        result = create_mcp_surface(registry)
        assert result is not None

    def test_create_mcp_surface_with_config(self):
        """Create MCP surface with config."""
        registry = AdapterRegistry()
        result = create_mcp_surface(registry, {"some": "config"})
        assert result is not None
