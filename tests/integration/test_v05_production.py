"""v0.5 production contract integration tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from agent_state_gate.adapters.base import AdapterMetadata, BaseAdapter, FailurePolicy, OperationMode
from agent_state_gate.adapters.registry import AdapterRegistry
from agent_state_gate.auth import AuthenticationError, OIDCAuthenticator
from agent_state_gate.config import AppConfig, RuntimeProfile, load_config
from agent_state_gate.models import (
    ApprovalBinding,
    AssessmentModel,
    GateEvaluationRequest,
    RequestContext,
    RiskLevel,
    StateGateAssessRequest,
)
from agent_state_gate.persistence import Database
from agent_state_gate.service import create_gate_service
from agent_state_gate.typed_ref import assessment_ref


class FakeAdapter(BaseAdapter):
    def __init__(self, name: str, methods: dict[str, object]):
        self._name, self._methods = name, methods

    @property
    def name(self) -> str:
        return self._name

    @property
    def capability(self) -> str:
        return self._name

    def health_check(self) -> bool:
        return True

    def get_metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name=self.name,
            capability=self.capability,
            operation_mode=OperationMode.READ_ONLY,
            failure_policy=FailurePolicy.FAIL_CLOSED,
        )

    def __getattr__(self, name: str):
        if name not in self._methods:
            raise AttributeError(name)
        value = self._methods[name]
        if isinstance(value, BaseException):
            raise value
        return lambda *args, **kwargs: value


def ctx(subject: str = "reviewer") -> RequestContext:
    return RequestContext(tenant_id="tenant-a", subject=subject, roles={"developer"})


def config(tmp_path, profile: str = "local_advisory") -> AppConfig:
    return AppConfig.model_validate(
        {"runtime_profile": profile, "database": {"url": f"sqlite:///{tmp_path / 'gate.db'}"}}
    )


def registry() -> AdapterRegistry:
    packet = {
        "schema_version": "2.0.0", "decision_id": "DEC-1", "run_id": "RUN-1",
        "artifact_id": "artifact-1", "decision": "pass", "composite_score": 0.95,
        "factors": [], "exemplar_refs": [], "action": {}, "threshold_version": "t1", "policy_version": "0.5.0",
    }
    values = {
        "taskstate": {"get_task": {"task_id": "TASK-1", "stage": "dev"}, "get_run": {"run_id": "RUN-1", "stage": "dev"}},
        "protocols": {"derive_risk_level": "low", "derive_required_approvals": []},
        "memx": {"stale_check": {"fresh": True, "stale_items": [], "stale_reasons": []}},
        "workflow": {"get_evidence_report": {"required_evidence": [], "collected_evidence": []}},
        "gatefield": {"evaluate": packet}, "shipyard": {"get_pipeline_stage": {"stage": "dev"}},
    }
    result = AdapterRegistry()
    for name, methods in values.items():
        result.register(FakeAdapter(name, methods))
    return result


def test_yaml_and_runtime_profile(monkeypatch):
    monkeypatch.setenv("SHIPYARD_CP_URL", "http://shipyard.example")
    loaded = load_config("config/gate_config.yaml")
    assert loaded.runtime_profile == RuntimeProfile.LOCAL_ADVISORY
    assert loaded.adapters.shipyard.endpoint == "http://shipyard.example"


def test_strict_config_and_production_requirements():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"database": {"url": "sqlite:///:memory:"}, "typoo": True})
    with pytest.raises(ValueError, match="requires PostgreSQL"):
        AppConfig.model_validate({"runtime_profile": "production_shadow", "database": {"url": "sqlite:///:memory:"}})


def test_gate_service_allow_replay_and_context_mismatch(tmp_path):
    service = create_gate_service(config(tmp_path), registry())
    request = GateEvaluationRequest(task_id="TASK-1", run_id="RUN-1", action="edit_repo", diff_hash="a" * 64)
    result = service.evaluate(request, ctx())
    assert result.verdict == "allow"
    assert service.replay("RUN-1", None, ctx()).status.value == "verified"
    assert service.replay("RUN-1", None, ctx("other")).status.value == "mismatch"


def test_missing_taskstate_is_deny(tmp_path):
    service = create_gate_service(config(tmp_path), AdapterRegistry())
    result = service.evaluate(
        GateEvaluationRequest(task_id="TASK-1", run_id="RUN-1", action="publish", diff_hash="a" * 64), ctx()
    )
    assert result.verdict == "deny"
    assert result.degraded and result.failure_policy_applied["taskstate"] == "deny"


def test_database_tenant_approval_queue_and_typed_ref(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'store.db'}")
    db.create_schema()
    assessment = AssessmentModel(
        assessment_id="ASM-1", tenant_id="tenant-a", task_id="TASK-1", run_id="RUN-1", stage="dev",
        decision_packet_ref="", final_verdict="allow", verdict_reason="ok", context_hash="b" * 64,
        diff_hash="a" * 64, policy_version="0.5.0", threshold_version="t1",
    )
    db.save_assessment(assessment)
    assert db.get_assessment("tenant-a", assessment_ref("ASM-1")).assessment_id == "ASM-1"
    assert db.get_assessment("tenant-a", "agent-taskstate:run:local:RUN-1") is None
    assert db.get_assessment("tenant-b", "ASM-1") is None
    binding = ApprovalBinding(
        approval_id="APR-1", tenant_id="tenant-a", diff_hash="a" * 64, context_hash="b" * 64,
        policy_version="0.5.0", approved_roles={"reviewer"}, expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    db.save_approval_binding(binding)
    assert db.approval_is_current("tenant-a", "APR-1", diff_hash="a" * 64, context_hash="b" * 64, policy_version="0.5.0")
    item = db.enqueue_attention(tenant_id="tenant-a", payload={"assessment_id": "ASM-1", "task_id": "TASK-1", "run_id": "RUN-1", "severity": "high", "required_role": "reviewer"})
    assert db.take_attention("tenant-b", item, "reviewer") is None
    assert db.take_attention("tenant-a", item, "reviewer")["assigned_to"] == "reviewer"
    assert db.resolve_attention("tenant-a", item, reviewer="reviewer", resolution="approved") is not None


def test_oidc_roles_claim_mapping(monkeypatch):
    oidc = AppConfig.model_validate({"oidc": {"enabled": True, "issuer": "https://issuer", "audience": "gate", "jwks_url": "https://issuer/jwks"}}).oidc
    auth = OIDCAuthenticator(oidc)
    auth._jwk_client = MagicMock(get_signing_key_from_jwt=MagicMock(return_value=MagicMock(key="secret")))
    monkeypatch.setattr("agent_state_gate.auth.jwt.decode", lambda *args, **kwargs: {"sub": "s", "tenant_id": "t", "roles": ["reviewer"]})
    assert "reviewer" in auth.authenticate("token").roles
    monkeypatch.setattr("agent_state_gate.auth.jwt.decode", lambda *args, **kwargs: {"sub": "s", "tenant_id": "t"})
    with pytest.raises(AuthenticationError):
        auth.authenticate("token")


def test_binding_hash_is_strict():
    with pytest.raises(ValidationError):
        ApprovalBinding(approval_id="APR-1", tenant_id="tenant-a", diff_hash="diff", context_hash="context", policy_version="0.5.0")


def test_service_assess_state_contract(tmp_path):
    service = create_gate_service(config(tmp_path), registry())
    result = service.assess_state(
        StateGateAssessRequest(artifact_refs=["artifact://one"], diff_hash="a" * 64, redacted_diff="redacted", run_id="RUN-1", stage="dev"),
        ctx(),
    )
    assert result.recommendation == "continue"


def test_service_health_reports_all_adapters(tmp_path):
    service = create_gate_service(config(tmp_path), registry())
    report = service.health(ctx())
    assert report.ready is True
    assert report.database_healthy is True
    assert set(report.adapters) == {"taskstate", "protocols", "memx", "workflow", "gatefield", "shipyard"}


def test_persistence_snapshot_audit_list_and_purge(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'audit.db'}")
    db.create_schema()
    db.append_audit_packet(
        packet_id="AUD-1", tenant_id="tenant-a", run_id="RUN-1", assessment_id="ASM-1",
        retention_class="audit", payload={"packet_id": "AUD-1"},
    )
    assert db.list_audit_packets("tenant-a", "RUN-1")[0]["packet_id"] == "AUD-1"
    snapshot_id = db.save_snapshot(
        tenant_id="tenant-a", run_id="RUN-1", assessment_id="ASM-1", attestation_hash="a" * 64,
        payload={"request": {"diff_hash": "a" * 64}},
    )
    assert snapshot_id.startswith("SNP-")
    assert db.latest_snapshot("tenant-a", "RUN-1") is not None
    manifest = db.purge_expired("tenant-a", executed_by="retention-admin", now=datetime.now(UTC) + timedelta(days=400))
    assert manifest["manifest_id"].startswith("PURGE-")


def test_gatefield_readiness_evidence(monkeypatch):
    from agent_state_gate.adapters.gatefield_adapter import GatefieldAdapter

    adapter = GatefieldAdapter({"endpoint": "http://gatefield"})
    response = MagicMock(status_code=200)
    response.json.return_value = {"status": "ok", "backend": {"pgvector_ready": True}}
    monkeypatch.setattr(adapter._session, "get", lambda *args, **kwargs: response)
    readiness = adapter.readiness()
    assert readiness["healthy"] is True and readiness["pgvector_ready"] is True


def test_production_context_requires_authentication(tmp_path):
    production = AppConfig.model_validate(
        {"runtime_profile": "production_shadow", "database": {"url": "postgresql+psycopg://gate"}, "oidc": {"enabled": True, "issuer": "https://issuer", "audience": "gate"}}
    )
    service = create_gate_service(production, AdapterRegistry())
    with pytest.raises(PermissionError):
        service.health(RequestContext(tenant_id="tenant-a", subject="dev", roles={"developer"}, authenticated=False))


def test_oidc_failure_modes(monkeypatch):
    disabled = OIDCAuthenticator(AppConfig().oidc)
    with pytest.raises(AuthenticationError):
        disabled.authenticate("token")
    enabled = AppConfig.model_validate({"oidc": {"enabled": True, "issuer": "https://issuer", "audience": "gate"}}).oidc
    auth = OIDCAuthenticator(enabled)
    with pytest.raises(AuthenticationError):
        auth.authenticate("")
    with pytest.raises(AuthenticationError):
        auth._jwks_url()
    monkeypatch.setattr("agent_state_gate.auth.requests.get", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(AuthenticationError):
        OIDCAuthenticator(enabled)._jwks_url()
    auth._jwk_client = MagicMock(get_signing_key_from_jwt=MagicMock(return_value=MagicMock(key="secret")))
    from jwt.exceptions import InvalidTokenError
    monkeypatch.setattr("agent_state_gate.auth.jwt.decode", MagicMock(side_effect=InvalidTokenError("bad")))
    with pytest.raises(AuthenticationError):
        auth.authenticate("token")


def test_oidc_roles_type_is_rejected(monkeypatch):
    enabled = AppConfig.model_validate({"oidc": {"enabled": True, "issuer": "https://issuer", "audience": "gate", "jwks_url": "https://issuer/jwks"}}).oidc
    auth = OIDCAuthenticator(enabled)
    auth._jwk_client = MagicMock(get_signing_key_from_jwt=MagicMock(return_value=MagicMock(key="secret")))
    monkeypatch.setattr("agent_state_gate.auth.jwt.decode", lambda *args, **kwargs: {"sub": "s", "tenant_id": "t", "roles": {"bad": True}})
    with pytest.raises(AuthenticationError):
        auth.authenticate("token")


def test_oidc_discovery_and_role_shapes(monkeypatch):
    enabled = AppConfig.model_validate({"oidc": {"enabled": True, "issuer": "https://issuer", "audience": "gate"}}).oidc
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"jwks_uri": "https://issuer/keys"}
    monkeypatch.setattr("agent_state_gate.auth.requests.get", lambda *args, **kwargs: response)
    auth = OIDCAuthenticator(enabled)
    assert auth._jwks_url() == "https://issuer/keys"
    auth._jwk_client = MagicMock(get_signing_key_from_jwt=MagicMock(return_value=MagicMock(key="secret")))
    monkeypatch.setattr("agent_state_gate.auth.jwt.decode", lambda *args, **kwargs: {"sub": "s", "tenant_id": "t", "roles": "reviewer,operator"})
    assert auth.authenticate("token").roles == frozenset({"reviewer", "operator"})
    monkeypatch.setattr("agent_state_gate.auth.jwt.decode", lambda *args, **kwargs: {"sub": "s", "tenant_id": "t", "roles": 1})
    with pytest.raises(AuthenticationError):
        auth.authenticate("token")
    response.json.return_value = {}
    with pytest.raises(AuthenticationError):
        OIDCAuthenticator(enabled)._jwks_url()


def test_all_adapter_failures_are_degraded_and_fail_safe(tmp_path):
    failure = RuntimeError("offline")
    bad = AdapterRegistry()
    bad.register(FakeAdapter("taskstate", {"get_task": failure, "get_run": failure}))
    bad.register(FakeAdapter("protocols", {"derive_risk_level": failure, "derive_required_approvals": failure}))
    bad.register(FakeAdapter("memx", {"stale_check": failure}))
    bad.register(FakeAdapter("workflow", {"get_evidence_report": failure}))
    bad.register(FakeAdapter("gatefield", {"evaluate": failure}))
    bad.register(FakeAdapter("shipyard", {"get_pipeline_stage": failure}))
    service = create_gate_service(config(tmp_path), bad)
    result = service.evaluate(GateEvaluationRequest(task_id="TASK-1", run_id="RUN-1", action="publish", diff_hash="a" * 64), ctx())
    assert result.verdict == "deny"
    assert result.degraded is True
    assert set(result.unavailable_axes) >= {"taskstate", "protocols", "memx", "workflow", "gatefield", "shipyard"}


def test_replay_as_of_before_snapshot_is_unavailable(tmp_path):
    service = create_gate_service(config(tmp_path), registry())
    service.evaluate(GateEvaluationRequest(task_id="TASK-1", run_id="RUN-1", action="edit_repo", diff_hash="a" * 64), ctx())
    result = service.replay("RUN-1", datetime.now(UTC) - timedelta(days=1), ctx())
    assert result.status.value == "unavailable"


def test_state_assess_missing_and_invalid_gatefield_are_safe(tmp_path):
    service = create_gate_service(config(tmp_path), AdapterRegistry())
    request = StateGateAssessRequest(artifact_refs=["artifact://one"], diff_hash="a" * 64, redacted_diff="redacted", run_id="RUN-1", stage="publish")
    missing = service.assess_state(request, ctx())
    assert missing.recommendation == "block" and missing.degraded is True
    invalid_registry = AdapterRegistry()
    invalid_registry.register(FakeAdapter("gatefield", {"evaluate": {"unexpected": True}}))
    (tmp_path / "invalid").mkdir()
    invalid = create_gate_service(config(tmp_path / "invalid"), invalid_registry).assess_state(request, ctx())
    assert invalid.recommendation == "hold_for_review" and invalid.degraded is True


def test_unknown_failure_axis_requires_approval(tmp_path):
    service = create_gate_service(config(tmp_path), AdapterRegistry())
    reasons: list[str] = []
    unavailable: list[str] = []
    applied: dict[str, str] = {}
    result = service._apply_failure(axis="unknown", risk_level=RiskLevel.LOW, action="edit_repo", verdict="allow", reasons=reasons, unavailable_axes=unavailable, applied=applied)
    assert result == "needs_approval"
    assert unavailable == ["unknown"] and applied["unknown"] == "needs_approval"


def test_verdict_priority_helper(tmp_path):
    service = create_gate_service(config(tmp_path), AdapterRegistry())
    assert service._more_restrictive("allow", "deny") == "deny"
    assert service._more_restrictive("deny", "allow") == "deny"


def test_high_risk_failure_policies_require_human_or_deny(tmp_path):
    service = create_gate_service(config(tmp_path), AdapterRegistry())
    reasons: list[str] = []
    unavailable: list[str] = []
    applied: dict[str, str] = {}
    human = service._apply_failure(axis="gatefield", risk_level=RiskLevel.HIGH, action="edit_repo", verdict="allow", reasons=reasons, unavailable_axes=unavailable, applied=applied)
    deny = service._apply_failure(axis="shipyard", risk_level=RiskLevel.CRITICAL, action="edit_repo", verdict="allow", reasons=reasons, unavailable_axes=unavailable, applied=applied)
    assert human == "require_human" and deny == "deny"
