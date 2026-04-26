"""
Unit tests for adapters.

Tests GatefieldAdapter, TaskstateAdapter, ProtocolsAdapter,
MemxAdapter, ShipyardAdapter, WorkflowAdapter, and AdapterRegistry.
"""

from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest

from src.adapters.base import (
    EvidenceNotFoundError,
    FailurePolicy,
    OperationMode,
)
from src.adapters.gatefield_adapter import GatefieldAdapter, GatefieldConfig
from src.adapters.memx_adapter import MemxAdapter, MemxConfig
from src.adapters.protocols_adapter import ProtocolsAdapter, ProtocolsConfig
from src.adapters.registry import AdapterRegistry
from src.adapters.shipyard_adapter import ShipyardAdapter, ShipyardConfig
from src.adapters.taskstate_adapter import TaskstateAdapter, TaskstateConfig
from src.adapters.workflow_adapter import WorkflowAdapter, WorkflowConfig

# === GatefieldAdapter Tests ===

class TestGatefieldAdapterConfig:
    def test_default_config(self):
        config = GatefieldConfig()
        assert config.base_url == "http://localhost:8080"
        assert config.timeout_seconds == 5

    def test_custom_config(self):
        config = GatefieldConfig(base_url="http://custom:9000", timeout_seconds=3)
        assert config.base_url == "http://custom:9000"
        assert config.timeout_seconds == 3


class TestGatefieldAdapterMetadata:
    def test_adapter_name(self):
        adapter = GatefieldAdapter()
        assert adapter.name == "gatefield"

    def test_adapter_capability(self):
        adapter = GatefieldAdapter()
        assert adapter.capability == "state-space-gate"

    def test_adapter_metadata(self):
        adapter = GatefieldAdapter()
        metadata = adapter.get_metadata()
        assert metadata.name == "gatefield"
        assert metadata.operation_mode == OperationMode.APPEND_ONLY
        assert metadata.failure_policy == FailurePolicy.FAIL_CLOSED


class TestGatefieldAdapterHealthCheck:
    def test_health_check_success(self):
        adapter = GatefieldAdapter()
        # Mock the session's get method
        mock_response = MagicMock()
        mock_response.status_code = 200
        adapter._session.get = MagicMock(return_value=mock_response)
        assert adapter.health_check() is True

    def test_health_check_failure(self):
        adapter = GatefieldAdapter()
        adapter._session.get = MagicMock(side_effect=Exception("Connection failed"))
        assert adapter.health_check() is False


class TestGatefieldAdapterEvaluate:
    def test_evaluate_returns_decision_packet(self):
        adapter = GatefieldAdapter()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "decision_id": "DEC-001",
            "decision": "pass",
            "composite_score": 0.85,
            "factors": []
        }
        mock_response.status_code = 200
        adapter._session.post = MagicMock(return_value=mock_response)

        result = adapter.evaluate(
            artifact={"artifact_id": "ART-001", "artifact_ref": "", "diff_hash": ""},
            trace={"run_id": "RUN-001", "trace_id": "TRACE-001", "context": {}}
        )

        assert result["decision_id"] == "DEC-001"
        assert result["decision"] == "pass"


# === TaskstateAdapter Tests ===

class TestTaskstateAdapterConfig:
    def test_default_config(self):
        config = TaskstateConfig()
        assert config.cli_path == "agent-taskstate"
        assert config.timeout_seconds == 3

    def test_custom_config(self):
        config = TaskstateConfig(cli_path="/custom/path", timeout_seconds=5)
        assert config.cli_path == "/custom/path"
        assert config.timeout_seconds == 5


class TestTaskstateAdapterMetadata:
    def test_adapter_name(self):
        adapter = TaskstateAdapter()
        assert adapter.name == "taskstate"

    def test_adapter_capability(self):
        adapter = TaskstateAdapter()
        assert adapter.capability == "task-state"

    def test_adapter_metadata(self):
        adapter = TaskstateAdapter()
        metadata = adapter.get_metadata()
        assert metadata.name == "taskstate"
        assert metadata.operation_mode == OperationMode.APPEND_ONLY


class TestTaskstateAdapterHealthCheck:
    @patch("src.adapters.taskstate_adapter.subprocess.run")
    def test_health_check_success(self, mock_run):
        mock_run.return_value.returncode = 0
        adapter = TaskstateAdapter()
        assert adapter.health_check() is True

    @patch("src.adapters.taskstate_adapter.subprocess.run")
    def test_health_check_failure(self, mock_run):
        mock_run.side_effect = Exception("CLI not found")
        adapter = TaskstateAdapter()
        assert adapter.health_check() is False


# === ProtocolsAdapter Tests ===

class TestProtocolsAdapterConfig:
    def test_default_config(self):
        config = ProtocolsConfig()
        assert config.schemas_dir is None
        assert config.enabled is True

    def test_custom_config(self):
        config = ProtocolsConfig(schemas_dir="/custom/schemas/", enabled=False)
        assert config.schemas_dir == "/custom/schemas/"
        assert config.enabled is False


class TestProtocolsAdapterMetadata:
    def test_adapter_name(self):
        adapter = ProtocolsAdapter()
        assert adapter.name == "protocols"

    def test_adapter_capability(self):
        adapter = ProtocolsAdapter()
        assert adapter.capability == "contract-risk-approval"

    def test_adapter_metadata(self):
        adapter = ProtocolsAdapter()
        metadata = adapter.get_metadata()
        assert metadata.name == "protocols"
        assert metadata.operation_mode == OperationMode.READ_ONLY


class TestProtocolsAdapterRisk:
    def test_derive_risk_level_low(self):
        adapter = ProtocolsAdapter()
        # Empty capabilities = low risk
        result = adapter.derive_risk_level([])
        assert result == "low"

    def test_derive_risk_level_high(self):
        adapter = ProtocolsAdapter()
        # HIGH_CAPABILITIES contains "install_deps"
        result = adapter.derive_risk_level(["install_deps"])
        assert result == "high"

    def test_derive_risk_level_critical(self):
        adapter = ProtocolsAdapter()
        # CRITICAL_CAPABILITIES contains "production_data_access"
        result = adapter.derive_risk_level(["production_data_access"])
        assert result == "critical"


class TestProtocolsAdapterApprovals:
    def test_derive_required_approvals_low(self):
        adapter = ProtocolsAdapter()
        # low risk auto-approved, empty approvals
        result = adapter.derive_required_approvals("low")
        assert result == []

    def test_derive_required_approvals_high(self):
        adapter = ProtocolsAdapter()
        # high risk requires project_lead, security_reviewer
        result = adapter.derive_required_approvals("high")
        assert "project_lead" in result
        assert "security_reviewer" in result


# === MemxAdapter Tests ===

class TestMemxAdapterConfig:
    def test_default_config(self):
        config = MemxConfig()
        assert config.base_url is None
        assert config.cli_path is None
        assert config.timeout_seconds == 3

    def test_custom_config(self):
        config = MemxConfig(base_url="http://custom:9000", timeout_seconds=5)
        assert config.base_url == "http://custom:9000"
        assert config.timeout_seconds == 5


class TestMemxAdapterMetadata:
    def test_adapter_name(self):
        adapter = MemxAdapter()
        assert adapter.name == "memx"

    def test_adapter_capability(self):
        adapter = MemxAdapter()
        assert adapter.capability == "docs-stale-ack"

    def test_adapter_metadata(self):
        adapter = MemxAdapter()
        metadata = adapter.get_metadata()
        assert metadata.name == "memx"
        assert metadata.operation_mode == OperationMode.APPEND_ONLY


class TestMemxAdapterResolve:
    def test_resolve_docs_returns_result(self):
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "docs": [{"doc_id": "DOC-001", "version": "v1"}]
        }
        mock_response.status_code = 200
        adapter._session.post = MagicMock(return_value=mock_response)

        result = adapter.resolve_docs("TASK-001", "code_change")

        assert "docs" in result


class TestMemxAdapterStaleCheck:
    def test_stale_check_fresh(self):
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        # Mock _http_call method directly
        adapter._http_call = MagicMock(return_value={
            "fresh": True,
            "stale_items": []
        })

        result = adapter.stale_check("TASK-001")

        assert result["fresh"] is True


# === ShipyardAdapter Tests ===

class TestShipyardAdapterConfig:
    def test_default_config(self):
        config = ShipyardConfig()
        assert config.base_url == "http://localhost:3000"
        assert config.timeout_seconds == 5

    def test_custom_config(self):
        config = ShipyardConfig(base_url="http://custom:4000", timeout_seconds=3)
        assert config.base_url == "http://custom:4000"
        assert config.timeout_seconds == 3


class TestShipyardAdapterMetadata:
    def test_adapter_name(self):
        adapter = ShipyardAdapter()
        assert adapter.name == "shipyard"

    def test_adapter_capability(self):
        adapter = ShipyardAdapter()
        assert adapter.capability == "pipeline-stage-transition"

    def test_adapter_metadata(self):
        adapter = ShipyardAdapter()
        metadata = adapter.get_metadata()
        assert metadata.name == "shipyard"
        assert metadata.operation_mode == OperationMode.CONTROLLED_MUTATION


class TestShipyardAdapterStage:
    def test_get_pipeline_stage(self):
        adapter = ShipyardAdapter()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "stage": "dev",
            "status": "active"
        }
        mock_response.status_code = 200
        adapter._session.get = MagicMock(return_value=mock_response)

        result = adapter.get_pipeline_stage("RUN-001")

        assert result["stage"] == "dev"


# === WorkflowAdapter Tests ===

class TestWorkflowAdapterConfig:
    def test_default_config(self):
        config = WorkflowConfig()
        assert config.cookbook_path is None
        assert config.timeout_seconds == 2

    def test_custom_config(self):
        config = WorkflowConfig(cookbook_path="/custom/cookbook", timeout_seconds=5)
        assert config.cookbook_path == "/custom/cookbook"
        assert config.timeout_seconds == 5


class TestWorkflowAdapterMetadata:
    def test_adapter_name(self):
        adapter = WorkflowAdapter()
        assert adapter.name == "workflow"

    def test_adapter_capability(self):
        adapter = WorkflowAdapter()
        assert adapter.capability == "evidence-acceptance-governance"

    def test_adapter_metadata(self):
        adapter = WorkflowAdapter()
        metadata = adapter.get_metadata()
        assert metadata.name == "workflow"
        assert metadata.operation_mode == OperationMode.READ_ONLY


class TestWorkflowAdapterEvidence:
    def test_get_evidence_report_raises_when_not_found(self):
        adapter = WorkflowAdapter()
        # Raises EvidenceNotFoundError when evidence file doesn't exist
        with pytest.raises(EvidenceNotFoundError):
            adapter.get_evidence_report("TASK-001")


# === AdapterRegistry Tests ===

class TestAdapterRegistry:
    def test_register_adapter(self):
        registry = AdapterRegistry()
        adapter = GatefieldAdapter()
        registry.register(adapter)
        assert registry.get("gatefield") == adapter

    def test_get_nonexistent_adapter(self):
        registry = AdapterRegistry()
        assert registry.get("nonexistent") is None

    def test_list_adapters(self):
        registry = AdapterRegistry()
        registry.register(GatefieldAdapter())
        registry.register(TaskstateAdapter())
        names = registry.get_names()
        assert "gatefield" in names
        assert "taskstate" in names

    def test_health_check_all(self):
        registry = AdapterRegistry()
        adapter = GatefieldAdapter()
        registry.register(adapter)

        with patch.object(adapter, "health_check", return_value=True):
            results = registry.health_check_all()
            assert results["gatefield"] is True


class TestAdapterRegistryGetByCapability:
    def test_get_by_capability(self):
        registry = AdapterRegistry()
        registry.register(GatefieldAdapter())
        adapters = registry.get_by_capability("state-space-gate")
        assert len(adapters) == 1
        assert adapters[0].name == "gatefield"

    def test_get_by_capability_not_found(self):
        registry = AdapterRegistry()
        adapters = registry.get_by_capability("unknown-capability")
        assert len(adapters) == 0


# === Additional GatefieldAdapter Tests ===

class TestGatefieldAdapterEnqueueReview:
    def test_enqueue_review_returns_id(self):
        adapter = GatefieldAdapter()
        mock_response = MagicMock()
        mock_response.json.return_value = {"review_id": "REV-001"}
        mock_response.status_code = 200
        adapter._session.post = MagicMock(return_value=mock_response)

        result = adapter.enqueue_review({
            "decision_id": "DEC-001",
            "run_id": "RUN-001",
            "severity": "high"
        })
        assert result == "REV-001"

    def test_enqueue_review_unavailable(self):
        adapter = GatefieldAdapter()
        mock_response = MagicMock()
        mock_response.status_code = 503
        adapter._session.post = MagicMock(return_value=mock_response)
        from src.adapters.base import AdapterUnavailableError
        with pytest.raises(AdapterUnavailableError):
            adapter.enqueue_review({"decision_id": "DEC-001"})


class TestGatefieldAdapterExportAudit:
    def test_export_audit_returns_events(self):
        adapter = GatefieldAdapter()
        mock_response = MagicMock()
        mock_response.json.return_value = {"audit_events": [{"event_id": "EVT-001"}]}
        mock_response.status_code = 200
        adapter._session.get = MagicMock(return_value=mock_response)

        result = adapter.export_audit("RUN-001")
        assert "audit_events" in result


class TestGatefieldAdapterGetDecisionPacket:
    def test_get_decision_packet_returns_packet(self):
        adapter = GatefieldAdapter()
        mock_response = MagicMock()
        mock_response.json.return_value = {"decision_id": "DEC-001", "decision": "pass"}
        mock_response.status_code = 200
        adapter._session.get = MagicMock(return_value=mock_response)

        result = adapter.get_decision_packet("DEC-001")
        assert result["decision_id"] == "DEC-001"

    def test_get_decision_packet_not_found(self):
        adapter = GatefieldAdapter()
        mock_response = MagicMock()
        mock_response.status_code = 404
        adapter._session.get = MagicMock(return_value=mock_response)
        from src.adapters.base import DecisionNotFoundError
        with pytest.raises(DecisionNotFoundError):
            adapter.get_decision_packet("DEC-UNKNOWN")


class TestGatefieldAdapterGetStateVector:
    def test_get_state_vector_returns_vector(self):
        adapter = GatefieldAdapter()
        mock_response = MagicMock()
        mock_response.json.return_value = {"run_id": "RUN-001", "vector": {}}
        mock_response.status_code = 200
        adapter._session.get = MagicMock(return_value=mock_response)

        result = adapter.get_state_vector("RUN-001")
        assert result["run_id"] == "RUN-001"


# === Additional TaskstateAdapter Tests ===

class TestTaskstateAdapterGetTask:
    @patch("src.adapters.taskstate_adapter.subprocess.run")
    def test_get_task_returns_task(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b'{"task_id": "TASK-001", "status": "active"}'
        mock_run.return_value = mock_result

        adapter = TaskstateAdapter()
        result = adapter.get_task("TASK-001")
        assert result["task_id"] == "TASK-001"


class TestTaskstateAdapterGetRun:
    @patch("src.adapters.taskstate_adapter.subprocess.run")
    def test_get_run_returns_run(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b'{"run_id": "RUN-001", "stage": "dev"}'
        mock_run.return_value = mock_result

        adapter = TaskstateAdapter()
        result = adapter.get_run("RUN-001")
        assert result["run_id"] == "RUN-001"


class TestTaskstateAdapterGetContextBundle:
    @patch("src.adapters.taskstate_adapter.subprocess.run")
    def test_get_context_bundle_returns_bundle(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b'{"bundle_id": "BUNDLE-001", "docs": []}'
        mock_run.return_value = mock_result

        adapter = TaskstateAdapter()
        result = adapter.get_context_bundle("BUNDLE-001")
        assert result["bundle_id"] == "BUNDLE-001"


# === Additional ProtocolsAdapter Tests ===

class TestProtocolsAdapterIsAutoApproved:
    def test_is_auto_approved_low(self):
        adapter = ProtocolsAdapter()
        result = adapter.is_auto_approved("low")
        assert result is True

    def test_is_auto_approved_high(self):
        adapter = ProtocolsAdapter()
        result = adapter.is_auto_approved("high")
        assert result is False


class TestProtocolsAdapterMedium:
    def test_derive_risk_level_medium(self):
        adapter = ProtocolsAdapter()
        result = adapter.derive_risk_level(["write_repo"])
        assert result == "medium"


# === Additional MemxAdapter Tests ===

class TestMemxAdapterResolveDocs:
    def test_resolve_docs_with_http(self):
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        adapter._http_call = MagicMock(return_value={
            "docs": [{"doc_id": "DOC-001", "version": "v1"}]
        })
        result = adapter.resolve_docs("TASK-001", "code_change")
        assert "docs" in result


class TestMemxAdapterGetChunks:
    def test_get_chunks_with_http(self):
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        adapter._http_call = MagicMock(return_value={
            "chunks": [{"chunk_id": "CHUNK-001"}]
        })
        result = adapter.get_chunks("DOC-001", ["CHUNK-001"])
        assert len(result) == 1
        assert result[0]["chunk_id"] == "CHUNK-001"


class TestMemxAdapterAckReads:
    def test_ack_reads_success(self):
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        adapter._http_call = MagicMock(return_value={"ack_ref": "ACK-001"})
        result = adapter.ack_reads("TASK-001", "DOC-001", "v1", ["CHUNK-001"])
        assert result == "ACK-001"


# === Additional ShipyardAdapter Tests ===

class TestShipyardAdapterHoldForReview:
    def test_hold_for_review_success(self):
        adapter = ShipyardAdapter()
        adapter._http_call = MagicMock(return_value={"hold_id": "HOLD-001"})

        result = adapter.hold_for_review("RUN-001", "ASM-001", "security review needed")
        assert result == "HOLD-001"


class TestShipyardAdapterResume:
    def test_resume_from_review_success(self):
        adapter = ShipyardAdapter()
        adapter._http_call = MagicMock(return_value={"success": True})

        result = adapter.resume_from_review("RUN-001", "HOLD-001", "approved")
        assert result is True


# === Additional AdapterRegistry Tests ===

class TestAdapterRegistryUnregister:
    def test_unregister_existing(self):
        registry = AdapterRegistry()
        adapter = GatefieldAdapter()
        registry.register(adapter)
        result = registry.unregister("gatefield")
        assert result is True
        assert registry.get("gatefield") is None

    def test_unregister_nonexistent(self):
        registry = AdapterRegistry()
        result = registry.unregister("nonexistent")
        assert result is False


class TestAdapterRegistryClear:
    def test_clear_removes_all(self):
        registry = AdapterRegistry()
        registry.register(GatefieldAdapter())
        registry.register(TaskstateAdapter())
        registry.clear()
        assert len(registry.get_all()) == 0


class TestAdapterRegistryGetAll:
    def test_get_all_returns_list(self):
        registry = AdapterRegistry()
        registry.register(GatefieldAdapter())
        registry.register(TaskstateAdapter())
        all_adapters = registry.get_all()
        assert len(all_adapters) == 2


# === Additional WorkflowAdapter Tests ===

class TestWorkflowAdapterBirdseye:
    def test_get_birdseye_caps_empty(self):
        adapter = WorkflowAdapter({"cookbook_path": "/nonexistent/path"})
        result = adapter.get_birdseye_caps("/nonexistent/repo")
        assert result["capabilities"] == []

    def test_get_birdseye_caps_returns_empty_when_missing(self):
        adapter = WorkflowAdapter()
        result = adapter.get_birdseye_caps("/nonexistent/repo")
        assert "capabilities" in result


class TestWorkflowAdapterAcceptance:
    def test_get_acceptance_index_empty(self):
        adapter = WorkflowAdapter({"cookbook_path": "/nonexistent/path"})
        result = adapter.get_acceptance_index("TASK-001")
        assert result["acceptances"] == []

    def test_get_acceptance_index_returns_task_id(self):
        adapter = WorkflowAdapter({"cookbook_path": "/nonexistent/path"})
        result = adapter.get_acceptance_index("TASK-001")
        assert result["task_id"] == "TASK-001"


class TestWorkflowAdapterGovernance:
    def test_get_governance_policy_empty(self):
        adapter = WorkflowAdapter({"cookbook_path": "/nonexistent/path"})
        result = adapter.get_governance_policy("policy-001")
        assert result["policy_id"] == "policy-001"

    def test_get_governance_policy_returns_rules(self):
        adapter = WorkflowAdapter({"cookbook_path": "/nonexistent/path"})
        result = adapter.get_governance_policy("policy-001")
        assert result["rules"] == []


class TestWorkflowAdapterEvidence:
    def test_get_evidence_report_raises_not_found(self):
        adapter = WorkflowAdapter({"cookbook_path": "/nonexistent/path"})
        with pytest.raises(EvidenceNotFoundError):
            adapter.get_evidence_report("TASK-001")

    def test_get_evidence_report_with_stage_raises_not_found(self):
        adapter = WorkflowAdapter({"cookbook_path": "/nonexistent/path"})
        with pytest.raises(EvidenceNotFoundError):
            adapter.get_evidence_report("TASK-001", stage="acceptance")


class TestWorkflowAdapterCodemap:
    def test_get_codemap_returns_empty(self):
        adapter = WorkflowAdapter({"cookbook_path": "/nonexistent/path"})
        result = adapter.get_codemap("scope://test")
        assert result["scope"] == "scope://test"


# === Additional MemxAdapter Tests ===

class TestMemxAdapterResolveContract:
    def test_resolve_contract_with_http(self):
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        adapter._http_call = MagicMock(return_value={
            "contract_id": "CTR-001",
            "contract_type": "Intent"
        })
        result = adapter.resolve_contract("Intent", {"task_id": "TASK-001"})
        assert result["contract_id"] == "CTR-001"


# === Additional TaskstateAdapter Tests ===

class TestTaskstateAdapterRecordReadReceipt:
    def test_record_read_receipt(self):
        adapter = TaskstateAdapter()
        adapter._run_cli = MagicMock(return_value={"receipt_id": "RCPT-001"})
        result = adapter.record_read_receipt("TASK-001", "DOC-001", "v1", ["CHUNK-001"])
        assert result == "RCPT-001"


# === Additional ShipyardAdapter Tests ===

class TestShipyardAdapterGetWorkerCapabilities:
    def test_get_worker_capabilities(self):
        adapter = ShipyardAdapter()
        adapter._http_call = MagicMock(return_value={"capabilities": ["state-space-gate", "docs-stale-ack"]})
        result = adapter.get_worker_capabilities("worker-001")
        assert len(result) == 2


# === Additional Registry Tests ===

class TestRegistryInitialize:
    def test_initialize_empty_config(self):
        from src.adapters.registry import initialize_adapters
        registry = initialize_adapters({})
        assert len(registry.get_all()) == 0

    def test_initialize_with_gatefield_enabled(self):
        from src.adapters.registry import initialize_adapters
        config = {"adapters": {"gatefield": {"enabled": True}}}
        registry = initialize_adapters(config)
        assert registry.get("gatefield") is not None

    def test_initialize_with_multiple_adapters(self):
        from src.adapters.registry import initialize_adapters
        config = {
            "adapters": {
                "gatefield": {"enabled": True},
                "taskstate": {"enabled": True},
                "protocols": {"enabled": True},
            }
        }
        registry = initialize_adapters(config)
        assert registry.get("gatefield") is not None
        assert registry.get("taskstate") is not None
        assert registry.get("protocols") is not None


# === Additional ProtocolsAdapter Tests ===

class TestProtocolsAdapterDeriveApprovals:
    def test_derive_required_approvals_medium(self):
        adapter = ProtocolsAdapter()
        result = adapter.derive_required_approvals("medium", ["read_repo"])
        assert result == []

    def test_derive_required_approvals_high_risk(self):
        adapter = ProtocolsAdapter()
        result = adapter.derive_required_approvals("high", ["write_repo"])
        assert len(result) >= 1

    def test_derive_required_approvals_critical(self):
        adapter = ProtocolsAdapter()
        result = adapter.derive_required_approvals("critical", ["admin_access"])
        assert len(result) >= 1

    def test_derive_required_approvals_unknown_level_raises(self):
        adapter = ProtocolsAdapter()
        with pytest.raises(Exception):  # SchemaValidationError
            adapter.derive_required_approvals("unknown_level")

    def test_is_auto_approved_medium(self):
        adapter = ProtocolsAdapter()
        result = adapter.is_auto_approved("medium")
        assert result is True

    def test_is_auto_approved_critical(self):
        adapter = ProtocolsAdapter()
        result = adapter.is_auto_approved("critical")
        assert result is False

    def test_is_auto_approved_unknown(self):
        adapter = ProtocolsAdapter()
        result = adapter.is_auto_approved("unknown")
        assert result is False

    def test_resolve_definition_of_done_missing(self):
        adapter = ProtocolsAdapter()
        with pytest.raises(Exception):  # SchemaValidationError
            adapter.resolve_definition_of_done("UnknownContract")

    def test_resolve_publish_requirements_missing(self):
        adapter = ProtocolsAdapter()
        with pytest.raises(Exception):  # SchemaValidationError
            adapter.resolve_publish_requirements("unknown_target")


# === Additional MemxAdapter Tests ===

class TestMemxAdapterResolveDocsEmpty:
    def test_resolve_docs_empty_result(self):
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        adapter._http_call = MagicMock(return_value={
            "required_docs": [],
            "recommended_docs": []
        })
        result = adapter.resolve_docs("TASK-001", "edit_repo")
        assert result["required_docs"] == []


class TestMemxAdapterStaleCheckFresh:
    def test_stale_check_with_session(self):
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        adapter._http_call = MagicMock(return_value={
            "fresh": True,
            "stale_items": []
        })
        result = adapter.stale_check("TASK-001")
        assert result["fresh"] is True


class TestMemxAdapterErrorHandling:
    def test_resolve_docs_raises_on_error(self):
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        from src.adapters.base import AdapterUnavailableError
        adapter._http_call = MagicMock(side_effect=AdapterUnavailableError("memx", "connection failed"))
        with pytest.raises(AdapterUnavailableError):
            adapter.resolve_docs("TASK-001", "edit_repo")

    def test_stale_check_raises_on_error(self):
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        from src.adapters.base import AdapterUnavailableError, StaleCheckError
        adapter._http_call = MagicMock(side_effect=AdapterUnavailableError("memx", "connection failed"))
        with pytest.raises(StaleCheckError):
            adapter.stale_check("TASK-001")


# === Additional WorkflowAdapter Tests ===

class TestWorkflowAdapterGetEvidence:
    def test_get_evidence_report_with_path(self):
        adapter = WorkflowAdapter()
        adapter._cookbook_path = MagicMock()
        adapter._cookbook_path.exists = MagicMock(return_value=True)
        adapter._run_cli = MagicMock(return_value={
            "task_id": "TASK-001",
            "evidence_strength": 1.0
        })
        result = adapter.get_evidence_report("TASK-001")
        assert result["task_id"] == "TASK-001"


class TestWorkflowAdapterGetCodemap:
    def test_get_codemap_with_cli(self):
        adapter = WorkflowAdapter()
        adapter._run_cli = MagicMock(return_value={
            "scope": "scope://test",
            "entries": []
        })
        result = adapter.get_codemap("scope://test")
        assert result["scope"] == "scope://test"


class TestWorkflowAdapterHealthCheck:
    def test_health_check_nonexistent_path(self):
        adapter = WorkflowAdapter({"cookbook_path": "/nonexistent/path"})
        result = adapter.health_check()
        assert result is False


class TestWorkflowAdapterAdditional:
    def test_get_birdseye_caps_json_decode_error(self):
        """Get birdseye caps handles JSON decode error."""
        adapter = WorkflowAdapter()
        from src.adapters.base import AdapterUnavailableError
        import tempfile
        import os
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = tmpdir
            birdseye_dir = os.path.join(repo_path, "birdseye")
            os.makedirs(birdseye_dir)
            index_file = os.path.join(birdseye_dir, "index.json")
            with open(index_file, "w") as f:
                f.write("not valid json")
            # Mock _run_cli to raise error so fallback is used
            adapter._run_cli = MagicMock(side_effect=AdapterUnavailableError("workflow", "error"))
            result = adapter.get_birdseye_caps(repo_path)
            assert result["capabilities"] == []

    def test_get_birdseye_caps_success(self):
        """Get birdseye caps reads valid JSON."""
        adapter = WorkflowAdapter()
        from src.adapters.base import AdapterUnavailableError
        import tempfile
        import os
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = tmpdir
            birdseye_dir = os.path.join(repo_path, "birdseye")
            os.makedirs(birdseye_dir)
            index_file = os.path.join(birdseye_dir, "index.json")
            with open(index_file, "w") as f:
                json.dump({"capabilities": ["read_repo"], "roles": ["dev"]}, f)
            adapter._run_cli = MagicMock(side_effect=AdapterUnavailableError("workflow", "error"))
            result = adapter.get_birdseye_caps(repo_path)
            assert result["capabilities"] == ["read_repo"]

    def test_get_acceptance_index_with_files(self):
        """Get acceptance index scans acceptance files."""
        adapter = WorkflowAdapter()
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            acceptance_dir = os.path.join(tmpdir, "docs", "acceptance")
            os.makedirs(acceptance_dir)
            acc_file = os.path.join(acceptance_dir, "acc-001.md")
            with open(acc_file, "w") as f:
                f.write("TASK-001 acceptance criteria")
            adapter._cookbook_path = Path(tmpdir)
            result = adapter.get_acceptance_index("TASK-001")
            assert len(result["acceptances"]) == 1

    def test_get_governance_policy_yaml_error(self):
        """Get governance policy handles YAML decode error."""
        adapter = WorkflowAdapter()
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            governance_dir = os.path.join(tmpdir, "governance")
            os.makedirs(governance_dir)
            policy_file = os.path.join(governance_dir, "policy-001.yaml")
            # Write malformed YAML
            with open(policy_file, "w") as f:
                f.write("not: valid: yaml: :::")
            adapter._cookbook_path = Path(tmpdir)
            result = adapter.get_governance_policy("policy-001")
            assert result["policy_id"] == "policy-001"

    def test_get_governance_policy_with_default_file(self):
        """Get governance policy reads default policy.yaml."""
        adapter = WorkflowAdapter()
        import tempfile
        import os
        import yaml
        with tempfile.TemporaryDirectory() as tmpdir:
            governance_dir = os.path.join(tmpdir, "governance")
            os.makedirs(governance_dir)
            policy_file = os.path.join(governance_dir, "policy.yaml")
            with open(policy_file, "w") as f:
                yaml.dump({"rules": ["rule1"]}, f)
            adapter._cookbook_path = Path(tmpdir)
            result = adapter.get_governance_policy("nonexistent")
            assert "rules" in result

    def test_get_evidence_report_from_file(self):
        """Get evidence report reads from fallback file."""
        adapter = WorkflowAdapter()
        from src.adapters.base import AdapterUnavailableError
        import tempfile
        import os
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, ".workflow-cache")
            os.makedirs(cache_dir)
            evidence_file = os.path.join(cache_dir, "evidence.json")
            with open(evidence_file, "w") as f:
                json.dump({
                    "evidences": [{"task_id": "TASK-001", "strength": 0.9}],
                    "acceptances": [],
                    "linked": [],
                    "unlinked_acceptances": [],
                    "unlinked_evidences": []
                }, f)
            adapter._cookbook_path = Path(tmpdir)
            adapter._run_cli = MagicMock(side_effect=AdapterUnavailableError("workflow", "error"))
            result = adapter.get_evidence_report("TASK-001")
            assert len(result["evidences"]) == 1

    def test_get_evidence_report_json_decode_error(self):
        """Get evidence report handles JSON decode error in fallback."""
        adapter = WorkflowAdapter()
        from src.adapters.base import AdapterUnavailableError, EvidenceNotFoundError
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, ".workflow-cache")
            os.makedirs(cache_dir)
            evidence_file = os.path.join(cache_dir, "evidence.json")
            with open(evidence_file, "w") as f:
                f.write("not valid json")
            adapter._cookbook_path = Path(tmpdir)
            adapter._run_cli = MagicMock(side_effect=AdapterUnavailableError("workflow", "error"))
            with pytest.raises(EvidenceNotFoundError):
                adapter.get_evidence_report("TASK-001")

    def test_get_codemap_from_file(self):
        """Get codemap reads from fallback file."""
        adapter = WorkflowAdapter()
        from src.adapters.base import AdapterUnavailableError
        import tempfile
        import os
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            codemap_dir = os.path.join(tmpdir, "codemap")
            os.makedirs(codemap_dir)
            # Scope should be simple filename-friendly
            codemap_file = os.path.join(codemap_dir, "test_scope.json")
            with open(codemap_file, "w") as f:
                json.dump({"scope": "test_scope", "modules": ["mod1"]}, f)
            adapter._cookbook_path = Path(tmpdir)
            adapter._run_cli = MagicMock(side_effect=AdapterUnavailableError("workflow", "error"))
            result = adapter.get_codemap("test_scope")
            assert result["modules"] == ["mod1"]

    def test_get_codemap_json_decode_error(self):
        """Get codemap handles JSON decode error in fallback."""
        adapter = WorkflowAdapter()
        from src.adapters.base import AdapterUnavailableError
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            codemap_dir = os.path.join(tmpdir, "codemap")
            os.makedirs(codemap_dir)
            codemap_file = os.path.join(codemap_dir, "test_scope.json")
            with open(codemap_file, "w") as f:
                f.write("not valid json")
            adapter._cookbook_path = Path(tmpdir)
            adapter._run_cli = MagicMock(side_effect=AdapterUnavailableError("workflow", "error"))
            result = adapter.get_codemap("test_scope")
            assert result["modules"] == []

    def test_health_check_exception(self):
        """Health check returns False on exception."""
        adapter = WorkflowAdapter()
        # Use nonexistent path to trigger exception in is_dir()
        adapter._cookbook_path = Path("/nonexistent/path/that/does/not/exist")
        result = adapter.health_check()
        assert result is False


# === Additional TaskstateAdapter Tests ===

class TestTaskstateAdapterMethods:
    def test_get_task_with_mock(self):
        adapter = TaskstateAdapter()
        adapter._run_cli = MagicMock(return_value={
            "task_id": "TASK-001",
            "state": "pending"
        })
        result = adapter.get_task("TASK-001")
        assert result["task_id"] == "TASK-001"

    def test_get_run_with_mock(self):
        adapter = TaskstateAdapter()
        adapter._run_cli = MagicMock(return_value={
            "run_id": "RUN-001",
            "stage": "dev"
        })
        result = adapter.get_run("RUN-001")
        assert result["run_id"] == "RUN-001"

    def test_get_context_bundle_with_mock(self):
        adapter = TaskstateAdapter()
        adapter._run_cli = MagicMock(return_value={
            "bundle_id": "BND-001",
            "docs": []
        })
        result = adapter.get_context_bundle("BND-001")
        assert result["bundle_id"] == "BND-001"

    def test_get_task_not_found(self):
        """Get task raises TaskNotFoundError when not found."""
        adapter = TaskstateAdapter()
        from src.adapters.base import AdapterUnavailableError, TaskNotFoundError
        adapter._run_cli = MagicMock(side_effect=AdapterUnavailableError("taskstate", "task TASK-001 not found"))
        with pytest.raises(TaskNotFoundError):
            adapter.get_task("TASK-001")

    def test_get_run_not_found(self):
        """Get run raises RunNotFoundError when not found."""
        adapter = TaskstateAdapter()
        from src.adapters.base import AdapterUnavailableError, RunNotFoundError
        adapter._run_cli = MagicMock(side_effect=AdapterUnavailableError("taskstate", "run RUN-001 not found"))
        with pytest.raises(RunNotFoundError):
            adapter.get_run("RUN-001")

    def test_get_context_bundle_not_found(self):
        """Get context bundle raises BundleNotFoundError when not found."""
        adapter = TaskstateAdapter()
        from src.adapters.base import AdapterUnavailableError, BundleNotFoundError
        adapter._run_cli = MagicMock(side_effect=AdapterUnavailableError("taskstate", "bundle BND-001 not found"))
        with pytest.raises(BundleNotFoundError):
            adapter.get_context_bundle("BND-001")

    def test_record_read_receipt_success(self):
        """Record read receipt returns receipt_id."""
        adapter = TaskstateAdapter()
        adapter._run_cli = MagicMock(return_value={"receipt_id": "RCPT-001"})
        result = adapter.record_read_receipt("TASK-001", "DOC-001", "v1", ["chunk-1"])
        assert result == "RCPT-001"

    def test_append_state_event_success(self):
        """Append state event returns event_id."""
        adapter = TaskstateAdapter()
        adapter._run_cli = MagicMock(return_value={"event_id": "EVT-001"})
        result = adapter.append_state_event("TASK-001", {"type": "progress"})
        assert result == "EVT-001"

    def test_list_decisions_success(self):
        """List decisions returns decision list."""
        adapter = TaskstateAdapter()
        adapter._run_cli = MagicMock(return_value={"decisions": [{"decision_id": "DEC-001"}]})
        result = adapter.list_decisions("TASK-001")
        assert len(result) == 1

    def test_list_decisions_not_found(self):
        """List decisions raises TaskNotFoundError when task not found."""
        adapter = TaskstateAdapter()
        from src.adapters.base import AdapterUnavailableError, TaskNotFoundError
        adapter._run_cli = MagicMock(side_effect=AdapterUnavailableError("taskstate", "task TASK-001 not found"))
        with pytest.raises(TaskNotFoundError):
            adapter.list_decisions("TASK-001")

    def test_health_check_exception(self):
        """Health check returns False on exception."""
        adapter = TaskstateAdapter({"cli_path": "/nonexistent/cli"})
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("CLI not found")
            result = adapter.health_check()
            assert result is False

    def test_run_cli_nonzero_returncode(self):
        """_run_cli raises on nonzero returncode."""
        adapter = TaskstateAdapter()
        from src.adapters.base import AdapterUnavailableError
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr=b"error message"
            )
            with pytest.raises(AdapterUnavailableError):
                adapter._run_cli(["task", "show", "--task", "TASK-001"])

    def test_run_cli_timeout(self):
        """_run_cli raises on timeout."""
        adapter = TaskstateAdapter()
        from src.adapters.base import AdapterUnavailableError
        import subprocess
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("cmd", 30)
            with pytest.raises(AdapterUnavailableError):
                adapter._run_cli(["task", "show", "--task", "TASK-001"])

    def test_run_cli_json_decode_error(self):
        """_run_cli raises on JSON decode error."""
        adapter = TaskstateAdapter()
        from src.adapters.base import AdapterUnavailableError
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b'not valid json'
            )
            with pytest.raises(AdapterUnavailableError):
                adapter._run_cli(["task", "show", "--task", "TASK-001"])


# === MemxAdapter CLI Mode Tests ===

class TestMemxAdapterCLIHealthCheck:
    def test_health_check_cli_success(self):
        """Health check via CLI returns True."""
        adapter = MemxAdapter({"cli_path": "/usr/bin/memx", "use_http": False})
        with patch.object(adapter, "_config") as cfg:
            cfg.cli_path = "/usr/bin/memx"
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = adapter.health_check()
                assert result is True

    def test_health_check_cli_failure(self):
        """Health check via CLI returns False on error."""
        adapter = MemxAdapter({"cli_path": "/usr/bin/memx", "use_http": False})
        with patch.object(adapter, "_config") as cfg:
            cfg.cli_path = "/usr/bin/memx"
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = Exception("CLI not found")
                result = adapter.health_check()
                assert result is False


class TestMemxAdapterCLIResolveDocs:
    def test_resolve_docs_cli_mode(self):
        """Resolve docs via CLI."""
        adapter = MemxAdapter({"cli_path": "/usr/bin/memx", "use_http": False})
        adapter._cli_call = MagicMock(return_value={
            "required_docs": [{"doc_id": "DOC-001"}],
            "recommended_docs": []
        })
        result = adapter.resolve_docs("TASK-001", "edit_repo", feature="auth")
        assert "required_docs" in result

    def test_resolve_docs_cli_with_paths(self):
        """Resolve docs via CLI with touched paths."""
        adapter = MemxAdapter({"cli_path": "/usr/bin/memx", "use_http": False})
        adapter._cli_call = MagicMock(return_value={
            "required_docs": [],
            "recommended_docs": []
        })
        result = adapter.resolve_docs("TASK-001", "edit_repo", touched_paths=["src/auth.py"])
        assert adapter._cli_call.called


class TestMemxAdapterCLIGetChunks:
    def test_get_chunks_cli_mode(self):
        """Get chunks via CLI."""
        adapter = MemxAdapter({"cli_path": "/usr/bin/memx", "use_http": False})
        adapter._cli_call = MagicMock(return_value={"chunks": [{"id": "chunk-1"}]})
        result = adapter.get_chunks("DOC-001", ["chunk-1"])
        assert len(result) == 1


class TestMemxAdapterCLIAckReads:
    def test_ack_reads_cli_mode(self):
        """Ack reads via CLI."""
        adapter = MemxAdapter({"cli_path": "/usr/bin/memx", "use_http": False})
        adapter._cli_call = MagicMock(return_value={"ack_ref": "memx:ack:local:01HACK01"})
        result = adapter.ack_reads("TASK-001", "DOC-001", "v1", ["chunk-1"])
        assert result == "memx:ack:local:01HACK01"

    def test_ack_reads_cli_raises_ack_failed(self):
        """Ack reads via CLI raises AckFailedError on failure."""
        adapter = MemxAdapter({"cli_path": "/usr/bin/memx", "use_http": False})
        from src.adapters.base import AdapterUnavailableError, AckFailedError
        adapter._cli_call = MagicMock(side_effect=AdapterUnavailableError("memx", "error"))
        with pytest.raises(AckFailedError):
            adapter.ack_reads("TASK-001", "DOC-001", "v1", ["chunk-1"])


class TestMemxAdapterCLIStaleCheck:
    def test_stale_check_cli_mode(self):
        """Stale check via CLI."""
        adapter = MemxAdapter({"cli_path": "/usr/bin/memx", "use_http": False})
        adapter._cli_call = MagicMock(return_value={"fresh": True, "stale_items": []})
        result = adapter.stale_check("TASK-001")
        assert result["fresh"] is True

    def test_stale_check_cli_raises_error(self):
        """Stale check via CLI raises StaleCheckError on failure."""
        adapter = MemxAdapter({"cli_path": "/usr/bin/memx", "use_http": False})
        from src.adapters.base import AdapterUnavailableError, StaleCheckError
        adapter._cli_call = MagicMock(side_effect=AdapterUnavailableError("memx", "error"))
        with pytest.raises(StaleCheckError):
            adapter.stale_check("TASK-001")


class TestMemxAdapterCLIResolveContract:
    def test_resolve_contract_cli_mode(self):
        """Resolve contract via CLI."""
        adapter = MemxAdapter({"cli_path": "/usr/bin/memx", "use_http": False})
        adapter._cli_call = MagicMock(return_value={"contract_id": "CTR-001"})
        result = adapter.resolve_contract("Intent", {"task_id": "TASK-001"})
        assert "contract_id" in result


class TestMemxAdapterCliCall:
    def test_cli_call_success(self):
        """CLI call returns parsed JSON."""
        adapter = MemxAdapter({"cli_path": "/usr/bin/memx", "use_http": False})
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b'{"result": "ok"}'
            )
            result = adapter._cli_call("docs:resolve", ["--task", "TASK-001"])
            assert result["result"] == "ok"

    def test_cli_call_nonzero_returncode_raises(self):
        """CLI call raises on nonzero returncode."""
        adapter = MemxAdapter({"cli_path": "/usr/bin/memx", "use_http": False})
        from src.adapters.base import AdapterUnavailableError
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr=b"error message"
            )
            with pytest.raises(AdapterUnavailableError):
                adapter._cli_call("docs:resolve", ["--task", "TASK-001"])

    def test_cli_call_timeout_raises(self):
        """CLI call raises on timeout."""
        adapter = MemxAdapter({"cli_path": "/usr/bin/memx", "use_http": False})
        from src.adapters.base import AdapterUnavailableError
        import subprocess
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("cmd", 30)
            with pytest.raises(AdapterUnavailableError):
                adapter._cli_call("docs:resolve", ["--task", "TASK-001"])

    def test_cli_call_json_decode_error_raises(self):
        """CLI call raises on JSON decode error."""
        adapter = MemxAdapter({"cli_path": "/usr/bin/memx", "use_http": False})
        from src.adapters.base import AdapterUnavailableError
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b'not valid json'
            )
            with pytest.raises(AdapterUnavailableError):
                adapter._cli_call("docs:resolve", ["--task", "TASK-001"])


class TestMemxAdapterHttpCall:
    def test_http_call_get_success(self):
        """HTTP GET call returns JSON."""
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"result": "ok"}
            )
            result = adapter._http_call("GET", "http://localhost:8000/v1/test")
            assert result["result"] == "ok"

    def test_http_call_post_success(self):
        """HTTP POST call returns JSON."""
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        with patch.object(adapter._session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"result": "ok"}
            )
            result = adapter._http_call("POST", "http://localhost:8000/v1/test", {"key": "value"})
            assert result["result"] == "ok"

    def test_http_call_503_raises_unavailable(self):
        """HTTP 503 raises AdapterUnavailableError."""
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        from src.adapters.base import AdapterUnavailableError
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=503)
            with pytest.raises(AdapterUnavailableError):
                adapter._http_call("GET", "http://localhost:8000/v1/test")

    def test_http_call_404_raises_docs_not_found(self):
        """HTTP 404 raises DocsNotFoundError."""
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        from src.adapters.base import DocsNotFoundError
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            with pytest.raises(DocsNotFoundError):
                adapter._http_call("GET", "http://localhost:8000/v1/test")

    def test_http_call_timeout_raises_unavailable(self):
        """HTTP timeout raises AdapterUnavailableError."""
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        from src.adapters.base import AdapterUnavailableError
        import requests
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.side_effect = requests.Timeout()
            with pytest.raises(AdapterUnavailableError):
                adapter._http_call("GET", "http://localhost:8000/v1/test")

    def test_http_call_connection_error_raises_unavailable(self):
        """HTTP connection error raises AdapterUnavailableError."""
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        from src.adapters.base import AdapterUnavailableError
        import requests
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.side_effect = requests.ConnectionError()
            with pytest.raises(AdapterUnavailableError):
                adapter._http_call("GET", "http://localhost:8000/v1/test")

    def test_http_call_unsupported_method_raises(self):
        """HTTP unsupported method raises ValueError."""
        adapter = MemxAdapter({"base_url": "http://localhost:8000"})
        with pytest.raises(ValueError):
            adapter._http_call("DELETE", "http://localhost:8000/v1/test")


class TestMemxAdapterNoSession:
    def test_resolve_docs_no_session_no_cli(self):
        """Resolve docs raises when no session or CLI."""
        adapter = MemxAdapter({"use_http": False})
        from src.adapters.base import AdapterUnavailableError
        with pytest.raises(AdapterUnavailableError):
            adapter.resolve_docs("TASK-001", "edit_repo")

    def test_get_chunks_no_session_no_cli(self):
        """Get chunks raises when no session or CLI."""
        adapter = MemxAdapter({"use_http": False})
        from src.adapters.base import AdapterUnavailableError
        with pytest.raises(AdapterUnavailableError):
            adapter.get_chunks("DOC-001", ["chunk-1"])

    def test_ack_reads_no_session_no_cli(self):
        """Ack reads raises when no session or CLI."""
        adapter = MemxAdapter({"use_http": False})
        from src.adapters.base import AdapterUnavailableError, AckFailedError
        with pytest.raises(AckFailedError):
            adapter.ack_reads("TASK-001", "DOC-001", "v1", ["chunk-1"])

    def test_health_check_no_session_no_cli(self):
        """Health check returns False when no session or CLI."""
        adapter = MemxAdapter({"use_http": False})
        result = adapter.health_check()
        assert result is False


# === ProtocolsAdapter Additional Tests ===

class TestProtocolsAdapterAdditional:
    def test_derive_required_approvals_empty_risks(self):
        """Derive approvals for low risk."""
        adapter = ProtocolsAdapter()
        adapter._run_cli = MagicMock(return_value={"approvals": []})
        result = adapter.derive_required_approvals("low")
        assert result == []

    def test_is_auto_approved_empty_context(self):
        """Is auto approved for low risk."""
        adapter = ProtocolsAdapter()
        adapter._run_cli = MagicMock(return_value={"auto_approved": True})
        result = adapter.is_auto_approved("low")
        assert result is True

    def test_derive_required_approvals_unknown_level(self):
        """Derive approvals for unknown risk level raises."""
        adapter = ProtocolsAdapter()
        from src.adapters.base import SchemaValidationError
        with pytest.raises(SchemaValidationError):
            adapter.derive_required_approvals("unknown")

    def test_is_auto_approved_unknown_level(self):
        """Is auto approved for unknown risk returns False."""
        adapter = ProtocolsAdapter()
        result = adapter.is_auto_approved("unknown")
        assert result is False

    def test_resolve_definition_of_done_not_found(self):
        """Resolve definition of done raises when schema not found."""
        adapter = ProtocolsAdapter()
        from src.adapters.base import SchemaValidationError
        with pytest.raises(SchemaValidationError):
            adapter.resolve_definition_of_done("Nonexistent")

    def test_resolve_publish_requirements_not_found(self):
        """Resolve publish requirements raises when schema not found."""
        adapter = ProtocolsAdapter()
        from src.adapters.base import SchemaValidationError
        with pytest.raises(SchemaValidationError):
            adapter.resolve_publish_requirements("nonexistent_target")

    def test_validate_contract_missing_required(self):
        """Validate contract raises when required field missing."""
        adapter = ProtocolsAdapter()
        from src.adapters.base import SchemaValidationError
        # Create a mock schema with required fields
        adapter._schemas_path = MagicMock()
        adapter._schemas_path.exists = MagicMock(return_value=True)
        mock_schema_file = MagicMock()
        mock_schema_file.exists = MagicMock(return_value=True)
        adapter._schemas_path.__truediv__ = MagicMock(return_value=mock_schema_file)
        # Mock the schema content to have required fields
        with patch("builtins.open", MagicMock()):
            with patch("json.load", MagicMock(return_value={"required": ["intent_id", "task_id"]})):
                with pytest.raises(SchemaValidationError):
                    adapter.validate_contract({"intent_id": "INT-001"}, "Intent")

    def test_health_check_nonexistent_path(self):
        """Health check returns False for nonexistent path."""
        adapter = ProtocolsAdapter({"schemas_dir": "/nonexistent/path"})
        result = adapter.health_check()
        assert result is False

    def test_get_risk_levels_schema_default(self):
        """Get risk levels schema returns default when file not found."""
        adapter = ProtocolsAdapter()
        result = adapter.get_risk_levels_schema()
        assert "levels" in result

    def test_get_approval_matrix_schema_default(self):
        """Get approval matrix schema returns default when file not found."""
        adapter = ProtocolsAdapter()
        result = adapter.get_approval_matrix_schema()
        assert "low" in result

    def test_derive_risk_level_critical(self):
        """Derive risk level returns critical for critical capabilities."""
        adapter = ProtocolsAdapter()
        result = adapter.derive_risk_level(["production_data_access"])
        assert result == "critical"

    def test_derive_risk_level_high(self):
        """Derive risk level returns high for high capabilities."""
        adapter = ProtocolsAdapter()
        result = adapter.derive_risk_level(["install_deps", "network_access"])
        assert result == "high"

    def test_derive_risk_level_medium(self):
        """Derive risk level returns medium for medium capabilities."""
        adapter = ProtocolsAdapter()
        result = adapter.derive_risk_level(["write_repo"])
        assert result == "medium"

    def test_derive_risk_level_low(self):
        """Derive risk level returns low for no special capabilities."""
        adapter = ProtocolsAdapter()
        result = adapter.derive_risk_level(["read_repo"])
        assert result == "low"

    def test_health_check_exception(self):
        """Health check returns False on exception."""
        adapter = ProtocolsAdapter()
        adapter._schemas_path = MagicMock()
        adapter._schemas_path.exists = MagicMock(side_effect=Exception("error"))
        result = adapter.health_check()
        assert result is False

    def test_resolve_definition_of_done_with_schema(self):
        """Resolve definition of done reads schema file."""
        adapter = ProtocolsAdapter()
        import tempfile
        import os
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            schema_dir = os.path.join(tmpdir, "contract_types")
            os.makedirs(schema_dir)
            schema_file = os.path.join(schema_dir, "intent.schema.json")
            with open(schema_file, "w") as f:
                json.dump({"type": "object", "properties": {}}, f)
            adapter._schemas_path = Path(tmpdir)
            result = adapter.resolve_definition_of_done("Intent")
            assert "type" in result

    def test_resolve_definition_of_done_json_error(self):
        """Resolve definition of done handles JSON decode error."""
        adapter = ProtocolsAdapter()
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            schema_dir = os.path.join(tmpdir, "contract_types")
            os.makedirs(schema_dir)
            schema_file = os.path.join(schema_dir, "intent.schema.json")
            with open(schema_file, "w") as f:
                f.write("not valid json")
            adapter._schemas_path = Path(tmpdir)
            from src.adapters.base import SchemaValidationError
            with pytest.raises(SchemaValidationError):
                adapter.resolve_definition_of_done("Intent")

    def test_resolve_publish_requirements_with_schema(self):
        """Resolve publish requirements reads schema file."""
        adapter = ProtocolsAdapter()
        import tempfile
        import os
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            schema_dir = os.path.join(tmpdir, "publish_gates")
            os.makedirs(schema_dir)
            schema_file = os.path.join(schema_dir, "npm.schema.json")
            with open(schema_file, "w") as f:
                json.dump({"type": "object", "properties": {}}, f)
            adapter._schemas_path = Path(tmpdir)
            result = adapter.resolve_publish_requirements("npm")
            assert "type" in result

    def test_resolve_publish_requirements_json_error(self):
        """Resolve publish requirements handles JSON decode error."""
        adapter = ProtocolsAdapter()
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            schema_dir = os.path.join(tmpdir, "publish_gates")
            os.makedirs(schema_dir)
            schema_file = os.path.join(schema_dir, "npm.schema.json")
            with open(schema_file, "w") as f:
                f.write("not valid json")
            adapter._schemas_path = Path(tmpdir)
            from src.adapters.base import SchemaValidationError
            with pytest.raises(SchemaValidationError):
                adapter.resolve_publish_requirements("npm")

    def test_validate_contract_success(self):
        """Validate contract passes when all required fields present."""
        adapter = ProtocolsAdapter()
        import tempfile
        import os
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            schema_dir = os.path.join(tmpdir, "contract_types")
            os.makedirs(schema_dir)
            schema_file = os.path.join(schema_dir, "intent.schema.json")
            with open(schema_file, "w") as f:
                json.dump({"required": ["intent_id", "task_id"]}, f)
            adapter._schemas_path = Path(tmpdir)
            result = adapter.validate_contract({"intent_id": "INT-001", "task_id": "TASK-001"}, "Intent")
            assert result is True

    def test_get_risk_levels_schema_with_file(self):
        """Get risk levels schema reads YAML file."""
        adapter = ProtocolsAdapter()
        import tempfile
        import os
        import yaml
        with tempfile.TemporaryDirectory() as tmpdir:
            schema_file = os.path.join(tmpdir, "risk_levels.yaml")
            with open(schema_file, "w") as f:
                yaml.dump({"levels": ["low", "high"], "custom": True}, f)
            adapter._schemas_path = Path(tmpdir)
            result = adapter.get_risk_levels_schema()
            assert "levels" in result

    def test_get_risk_levels_schema_yaml_error(self):
        """Get risk levels schema handles YAML decode error."""
        adapter = ProtocolsAdapter()
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            schema_file = os.path.join(tmpdir, "risk_levels.yaml")
            with open(schema_file, "w") as f:
                f.write("not: valid: yaml: :::")
            adapter._schemas_path = Path(tmpdir)
            result = adapter.get_risk_levels_schema()
            assert result == {}

    def test_get_approval_matrix_schema_with_file(self):
        """Get approval matrix schema reads YAML file."""
        adapter = ProtocolsAdapter()
        import tempfile
        import os
        import yaml
        with tempfile.TemporaryDirectory() as tmpdir:
            schema_file = os.path.join(tmpdir, "approval_matrix.yaml")
            with open(schema_file, "w") as f:
                yaml.dump({"low": {"auto_approved": True}}, f)
            adapter._schemas_path = Path(tmpdir)
            result = adapter.get_approval_matrix_schema()
            assert "low" in result

    def test_get_approval_matrix_schema_yaml_error(self):
        """Get approval matrix schema handles YAML decode error."""
        adapter = ProtocolsAdapter()
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            schema_file = os.path.join(tmpdir, "approval_matrix.yaml")
            with open(schema_file, "w") as f:
                f.write("not: valid: yaml: :::")
            adapter._schemas_path = Path(tmpdir)
            result = adapter.get_approval_matrix_schema()
            # Returns default APPROVAL_MATRIX on error
            assert "low" in result

    def test_derive_required_approvals_high(self):
        """Derive approvals for high risk."""
        adapter = ProtocolsAdapter()
        result = adapter.derive_required_approvals("high")
        assert "project_lead" in result
        assert "security_reviewer" in result

    def test_derive_required_approvals_critical(self):
        """Derive approvals for critical risk."""
        adapter = ProtocolsAdapter()
        result = adapter.derive_required_approvals("critical")
        assert "project_lead" in result
        assert "security_reviewer" in result
        assert "release_manager" in result

    def test_is_auto_approved_high(self):
        """Is auto approved for high risk returns False."""
        adapter = ProtocolsAdapter()
        result = adapter.is_auto_approved("high")
        assert result is False

    def test_is_auto_approved_critical(self):
        """Is auto approved for critical risk returns False."""
        adapter = ProtocolsAdapter()
        result = adapter.is_auto_approved("critical")
        assert result is False

    def test_is_auto_approved_medium(self):
        """Is auto approved for medium risk returns True."""
        adapter = ProtocolsAdapter()
        result = adapter.is_auto_approved("medium")
        assert result is True


# === ShipyardAdapter Additional Tests ===

class TestShipyardAdapterAdditional:
    def test_get_pipeline_stage_success(self):
        """Get pipeline stage."""
        adapter = ShipyardAdapter({"base_url": "http://localhost:3000"})
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"stage": "dev", "status": "active"}
            )
            result = adapter.get_pipeline_stage("RUN-001")
            assert result["stage"] == "dev"

    def test_hold_for_review_no_config(self):
        """Hold for review raises without config."""
        adapter = ShipyardAdapter()
        from src.adapters.base import AdapterUnavailableError
        with pytest.raises(AdapterUnavailableError):
            adapter.hold_for_review("RUN-001", "ASM-001", "needs review")

    def test_resume_from_review_no_config(self):
        """Resume from review raises without config."""
        adapter = ShipyardAdapter()
        from src.adapters.base import AdapterUnavailableError
        with pytest.raises(AdapterUnavailableError):
            adapter.resume_from_review("RUN-001", "HOLD-001", "approved")

    def test_hold_for_review_success(self):
        """Hold for review returns hold_id."""
        adapter = ShipyardAdapter({"base_url": "http://localhost:3000"})
        with patch.object(adapter._session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"hold_id": "HOLD-001"}
            )
            result = adapter.hold_for_review("RUN-001", "ASM-001", "needs review")
            assert result == "HOLD-001"

    def test_resume_from_review_success(self):
        """Resume from review returns True."""
        adapter = ShipyardAdapter({"base_url": "http://localhost:3000"})
        with patch.object(adapter._session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"success": True}
            )
            result = adapter.resume_from_review("RUN-001", "HOLD-001", "approved")
            assert result is True

    def test_resume_from_review_transition_not_allowed(self):
        """Resume from review returns False on TransitionNotAllowed."""
        adapter = ShipyardAdapter({"base_url": "http://localhost:3000"})
        from src.adapters.base import TransitionNotAllowedError
        with patch.object(adapter._session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=409,
                json=lambda: {"detail": "transition not allowed"}
            )
            result = adapter.resume_from_review("RUN-001", "HOLD-001", "approved")
            assert result is False

    def test_get_worker_capabilities_success(self):
        """Get worker capabilities returns list."""
        adapter = ShipyardAdapter({"base_url": "http://localhost:3000"})
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"capabilities": ["read_repo", "write_repo"]}
            )
            result = adapter.get_worker_capabilities("WORKER-001")
            assert len(result) == 2

    def test_health_check_success(self):
        """Health check returns True on success."""
        adapter = ShipyardAdapter({"base_url": "http://localhost:3000"})
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            result = adapter.health_check()
            assert result is True

    def test_health_check_exception(self):
        """Health check returns False on exception."""
        adapter = ShipyardAdapter({"base_url": "http://localhost:3000"})
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.side_effect = Exception("error")
            result = adapter.health_check()
            assert result is False

    def test_http_call_503_raises(self):
        """HTTP call 503 raises AdapterUnavailableError."""
        adapter = ShipyardAdapter({"base_url": "http://localhost:3000"})
        from src.adapters.base import AdapterUnavailableError
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=503)
            with pytest.raises(AdapterUnavailableError):
                adapter._http_call("GET", "http://localhost:3000/v1/test")

    def test_http_call_404_without_task_raises_unavailable(self):
        """HTTP call 404 without task_id raises AdapterUnavailableError."""
        adapter = ShipyardAdapter({"base_url": "http://localhost:3000"})
        from src.adapters.base import AdapterUnavailableError
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            with pytest.raises(AdapterUnavailableError):
                adapter._http_call("GET", "http://localhost:3000/v1/test")

    def test_http_call_404_with_task_raises_stage_not_found(self):
        """HTTP call 404 with task_id raises StageNotFoundError."""
        adapter = ShipyardAdapter({"base_url": "http://localhost:3000"})
        from src.adapters.base import StageNotFoundError
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            with pytest.raises(StageNotFoundError):
                adapter._http_call("GET", "http://localhost:3000/v1/test", task_id="RUN-001")

    def test_http_call_409_raises_transition_not_allowed(self):
        """HTTP call 409 raises TransitionNotAllowedError."""
        adapter = ShipyardAdapter({"base_url": "http://localhost:3000"})
        from src.adapters.base import TransitionNotAllowedError
        with patch.object(adapter._session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=409,
                json=lambda: {"detail": "cannot transition"}
            )
            with pytest.raises(TransitionNotAllowedError):
                adapter._http_call("POST", "http://localhost:3000/v1/test", payload={"from_stage": "dev", "to_stage": "prod"}, task_id="RUN-001")

    def test_http_call_timeout_raises(self):
        """HTTP call timeout raises AdapterUnavailableError."""
        adapter = ShipyardAdapter({"base_url": "http://localhost:3000"})
        from src.adapters.base import AdapterUnavailableError
        import requests
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.side_effect = requests.Timeout()
            with pytest.raises(AdapterUnavailableError):
                adapter._http_call("GET", "http://localhost:3000/v1/test")

    def test_http_call_connection_error_raises(self):
        """HTTP call connection error raises AdapterUnavailableError."""
        adapter = ShipyardAdapter({"base_url": "http://localhost:3000"})
        from src.adapters.base import AdapterUnavailableError
        import requests
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.side_effect = requests.ConnectionError()
            with pytest.raises(AdapterUnavailableError):
                adapter._http_call("GET", "http://localhost:3000/v1/test")

    def test_http_call_unsupported_method_raises(self):
        """HTTP call unsupported method raises ValueError."""
        adapter = ShipyardAdapter({"base_url": "http://localhost:3000"})
        with pytest.raises(ValueError):
            adapter._http_call("DELETE", "http://localhost:3000/v1/test")


# === GatefieldAdapter Additional Tests ===

class TestGatefieldAdapterAdditional:
    def test_get_state_vector_http(self):
        """Get state vector via HTTP."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "taboo_proximity": 0.1,
                    "scope_drift": 0.2
                }
            )
            result = adapter.get_state_vector("RUN-001")
            assert "taboo_proximity" in result

    def test_enqueue_review_http(self):
        """Enqueue review via HTTP."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        with patch.object(adapter._session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"review_id": "REV-001"}
            )
            result = adapter.enqueue_review({"decision_id": "DEC-001", "severity": "HIGH"})
            assert result == "REV-001"

    def test_export_audit_http(self):
        """Export audit via HTTP."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"audit_events": []}
            )
            result = adapter.export_audit("RUN-001")
            assert "audit_events" in result

    def test_health_check_success(self):
        """Health check returns True on success."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            result = adapter.health_check()
            assert result is True

    def test_health_check_exception(self):
        """Health check returns False on exception."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.side_effect = Exception("error")
            result = adapter.health_check()
            assert result is False

    def test_evaluate_success(self):
        """Evaluate returns decision packet."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        with patch.object(adapter._session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"decision_id": "DEC-001", "decision": "pass"}
            )
            result = adapter.evaluate(
                {"artifact_id": "ART-001", "artifact_ref": "ref", "diff_hash": "hash"},
                {"run_id": "RUN-001", "trace_id": "TR-001"}
            )
            assert result["decision_id"] == "DEC-001"

    def test_evaluate_503_raises(self):
        """Evaluate 503 raises AdapterUnavailableError."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        from src.adapters.base import AdapterUnavailableError
        with patch.object(adapter._session, "post") as mock_post:
            mock_post.return_value = MagicMock(status_code=503)
            with pytest.raises(AdapterUnavailableError):
                adapter.evaluate({}, {"run_id": "RUN-001"})

    def test_evaluate_timeout_raises(self):
        """Evaluate timeout raises AdapterUnavailableError."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        from src.adapters.base import AdapterUnavailableError
        import requests
        with patch.object(adapter._session, "post") as mock_post:
            mock_post.side_effect = requests.Timeout()
            with pytest.raises(AdapterUnavailableError):
                adapter.evaluate({}, {"run_id": "RUN-001"})

    def test_evaluate_connection_error_raises(self):
        """Evaluate connection error raises AdapterUnavailableError."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        from src.adapters.base import AdapterUnavailableError
        import requests
        with patch.object(adapter._session, "post") as mock_post:
            mock_post.side_effect = requests.ConnectionError()
            with pytest.raises(AdapterUnavailableError):
                adapter.evaluate({}, {"run_id": "RUN-001"})

    def test_enqueue_review_503_raises(self):
        """Enqueue review 503 raises AdapterUnavailableError."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        from src.adapters.base import AdapterUnavailableError
        with patch.object(adapter._session, "post") as mock_post:
            mock_post.return_value = MagicMock(status_code=503)
            with pytest.raises(AdapterUnavailableError):
                adapter.enqueue_review({"decision_id": "DEC-001"})

    def test_enqueue_review_timeout_raises(self):
        """Enqueue review timeout raises AdapterUnavailableError."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        from src.adapters.base import AdapterUnavailableError
        import requests
        with patch.object(adapter._session, "post") as mock_post:
            mock_post.side_effect = requests.Timeout()
            with pytest.raises(AdapterUnavailableError):
                adapter.enqueue_review({"decision_id": "DEC-001"})

    def test_export_audit_503_raises(self):
        """Export audit 503 raises AdapterUnavailableError."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        from src.adapters.base import AdapterUnavailableError
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=503)
            with pytest.raises(AdapterUnavailableError):
                adapter.export_audit("RUN-001")

    def test_export_audit_timeout_raises(self):
        """Export audit timeout raises AdapterUnavailableError."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        from src.adapters.base import AdapterUnavailableError
        import requests
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.side_effect = requests.Timeout()
            with pytest.raises(AdapterUnavailableError):
                adapter.export_audit("RUN-001")

    def test_get_decision_packet_success(self):
        """Get decision packet returns packet."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"decision_id": "DEC-001", "decision": "pass"}
            )
            result = adapter.get_decision_packet("DEC-001")
            assert result["decision_id"] == "DEC-001"

    def test_get_decision_packet_404_raises(self):
        """Get decision packet 404 raises DecisionNotFoundError."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        from src.adapters.base import DecisionNotFoundError
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            with pytest.raises(DecisionNotFoundError):
                adapter.get_decision_packet("DEC-001")

    def test_get_state_vector_503_raises(self):
        """Get state vector 503 raises AdapterUnavailableError."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        from src.adapters.base import AdapterUnavailableError
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=503)
            with pytest.raises(AdapterUnavailableError):
                adapter.get_state_vector("RUN-001")

    def test_get_state_vector_timeout_raises(self):
        """Get state vector timeout raises AdapterUnavailableError."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        from src.adapters.base import AdapterUnavailableError
        import requests
        with patch.object(adapter._session, "get") as mock_get:
            mock_get.side_effect = requests.Timeout()
            with pytest.raises(AdapterUnavailableError):
                adapter.get_state_vector("RUN-001")

    def test_evaluate_with_rule_results(self):
        """Evaluate with rule_results included."""
        adapter = GatefieldAdapter({"base_url": "http://localhost:8080"})
        with patch.object(adapter._session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"decision_id": "DEC-001"}
            )
            adapter.evaluate(
                {"artifact_id": "ART-001"},
                {"run_id": "RUN-001"},
                {"rule1": "result1"}
            )
            # Check that rule_results was passed
            call_args = mock_post.call_args
            assert "rule_results" in call_args[1]["json"]
