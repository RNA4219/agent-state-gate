"""MCP facade tests for the strict 0.5 contracts."""

import hashlib
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from agent_state_gate.adapters import AdapterRegistry
from agent_state_gate.api import AttentionListResult, MCPSurface, SLAStatus
from agent_state_gate.config import AppConfig, RuntimeProfile
from agent_state_gate.models import (
    EvaluateResult,
    ReplayResult,
    ReplayStatus,
    RequestContext,
    StateGateAssessResult,
)


def _config() -> AppConfig:
    return AppConfig.model_validate(
        {"runtime_profile": "local_advisory", "database": {"url": "sqlite:///:memory:"}}
    )


def _context() -> RequestContext:
    return RequestContext(tenant_id="tenant-a", subject="agent-a", roles=frozenset({"developer"}))


def test_gate_evaluate_delegates_to_gate_service() -> None:
    service = MagicMock()
    service.evaluate.return_value = EvaluateResult(
        verdict="deny",
        assessment_id="ASM-1",
        verdict_reason="taskstate unavailable",
        runtime_profile=RuntimeProfile.LOCAL_ADVISORY,
        degraded=True,
        unavailable_axes=["taskstate"],
        failure_policy_applied={"taskstate": "deny"},
    )
    surface = MCPSurface(AdapterRegistry(), config=_config(), gate_service=service)
    result = surface.gate_evaluate(
        "TASK-1",
        "publish",
        ["release"],
        run_id="RUN-1",
        diff_hash="a" * 64,
        context=_context(),
    )
    assert result.verdict == "deny"
    assert result.degraded is True
    service.evaluate.assert_called_once()


def test_stale_check_fails_safe_without_memx() -> None:
    surface = MCPSurface(AdapterRegistry(), config=_config(), gate_service=MagicMock())
    result = surface.context_stale_check("TASK-1")
    assert result.fresh is False
    assert "unavailable" in result.stale_reasons[0]


def test_state_assess_hashes_local_raw_diff_then_delegates() -> None:
    service = MagicMock()
    service.assess_state.return_value = StateGateAssessResult(
        assessment_id="ASM-1",
        recommendation="hold_for_review",
        human_queue_required=True,
        degraded=True,
        unavailable_axes=["gatefield"],
    )
    surface = MCPSurface(AdapterRegistry(), config=_config(), gate_service=service)
    surface.state_gate_assess(["artifact://one"], "redacted diff", "RUN-1", "dev", context=_context())
    request = service.assess_state.call_args.args[0]
    assert request.diff_hash == hashlib.sha256(b"redacted diff").hexdigest()
    assert request.redacted_diff == "redacted diff"


def test_replay_never_claims_placeholder_verified() -> None:
    service = MagicMock()
    service.replay.return_value = ReplayResult(run_id="RUN-404", status=ReplayStatus.UNAVAILABLE)
    surface = MCPSurface(AdapterRegistry(), config=_config(), gate_service=service)
    result = surface.run_replay_context("RUN-404", context=_context())
    assert result.status == ReplayStatus.UNAVAILABLE
    assert result.reproducibility_verified is False


def test_attention_is_tenant_scoped() -> None:
    service = MagicMock()
    service.database.list_attention.return_value = [
        {"item_id": "Q-1", "status": "pending", "severity": "critical"}
    ]
    surface = MCPSurface(AdapterRegistry(), config=_config(), gate_service=service)
    result = surface.attention_list(context=_context())
    service.database.list_attention.assert_called_once_with(
        "tenant-a", status=None, reviewer_role=None
    )
    assert result.total_pending == 1
    assert result.by_severity["critical"] == 1


def test_strict_contract_rejects_positional_and_extra_fields() -> None:
    with pytest.raises(TypeError):
        SLAStatus(0, 0, 0, 0)
    with pytest.raises(ValidationError):
        EvaluateResult(
            verdict="allow",
            assessment_id="ASM-1",
            verdict_reason="ok",
            runtime_profile="local_advisory",
            unexpected=True,
        )


def test_attention_contract_accepts_named_sla_status() -> None:
    result = AttentionListResult(
        items=[],
        total_pending=0,
        by_severity={},
        sla_status={
            "global": SLAStatus(
                pending_count=0,
                ack_timeout_count=0,
                decision_timeout_count=0,
                escalated_count=0,
            )
        },
    )
    assert result.total_pending == 0
