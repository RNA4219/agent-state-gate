"""CLI 0.5 service-backed contract tests."""

import json
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from agent_state_gate.cli import build_parser, dispatch_command, main, output_result
from agent_state_gate.config import AppConfig, RuntimeProfile
from agent_state_gate.models import EvaluateResult, ReplayResult, ReplayStatus, RequestContext


def _runtime(service: MagicMock) -> tuple[AppConfig, MagicMock, RequestContext]:
    config = AppConfig.model_validate(
        {"runtime_profile": "local_advisory", "database": {"url": "sqlite:///:memory:"}}
    )
    context = RequestContext(tenant_id="tenant-a", subject="reviewer", roles=frozenset({"developer"}))
    return config, service, context


def _evaluate_args() -> Namespace:
    return Namespace(
        command="gate",
        action="evaluate",
        task="TASK-1",
        run="RUN-1",
        action_type="edit_repo",
        capability=[],
        artifact_ref=[],
        touched_path=[],
        diff_hash=None,
    )


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        ("allow", 0),
        ("needs_approval", 2),
        ("require_human", 2),
        ("revise", 2),
        ("stale_blocked", 2),
        ("deny", 3),
    ],
)
def test_gate_exit_code_contract(verdict: str, expected: int) -> None:
    service = MagicMock()
    service.evaluate.return_value = EvaluateResult(
        verdict=verdict,
        assessment_id="ASM-1",
        verdict_reason="contract test",
        runtime_profile=RuntimeProfile.LOCAL_ADVISORY,
    )
    with patch("agent_state_gate.cli._runtime", return_value=_runtime(service)):
        payload, exit_code = dispatch_command(_evaluate_args())
    assert payload["verdict"] == verdict
    assert exit_code == expected


def test_queue_take_requires_reviewer() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["queue", "take", "--item", "Q-1"])
    assert exc.value.code == 2


def test_queue_state_is_read_from_persistent_service() -> None:
    service = MagicMock()
    service.database.list_attention.return_value = [{"item_id": "Q-1", "tenant_id": "tenant-a"}]
    args = Namespace(command="queue", action="list", status=None, reviewer_role=None)
    with patch("agent_state_gate.cli._runtime", return_value=_runtime(service)):
        payload, exit_code = dispatch_command(args)
    service.database.list_attention.assert_called_once_with("tenant-a", status=None, reviewer_role=None)
    assert payload["count"] == 1
    assert exit_code == 0


def test_replay_unavailable_is_nonzero() -> None:
    service = MagicMock()
    service.replay.return_value = ReplayResult(run_id="RUN-1", status=ReplayStatus.UNAVAILABLE)
    args = Namespace(command="replay", run="RUN-1")
    with patch("agent_state_gate.cli._runtime", return_value=_runtime(service)):
        payload, exit_code = dispatch_command(args)
    assert payload["status"] == "unavailable"
    assert exit_code == 2


def test_output_result_json(capsys: pytest.CaptureFixture[str]) -> None:
    output_result({"key": "value"}, "json")
    assert json.loads(capsys.readouterr().out) == {"key": "value"}


def test_output_result_text(capsys: pytest.CaptureFixture[str]) -> None:
    output_result({"key": "value"}, "text")
    assert capsys.readouterr().out == "key: value\n"


@patch("sys.argv", ["agent-state-gate", "--help"])
def test_main_help() -> None:
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


@patch("sys.argv", ["agent-state-gate", "--version"])
def test_main_version() -> None:
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_unknown_command_is_rejected() -> None:
    service = MagicMock()
    args = Namespace(command="unknown")
    with patch("agent_state_gate.cli._runtime", return_value=_runtime(service)):
        with pytest.raises(ValueError, match="unsupported command"):
            dispatch_command(args)


def test_dispatch_state_assess_branch():
    service = MagicMock()
    service.assess_state.return_value = MagicMock(
        model_dump=lambda mode: {"recommendation": "continue"}, recommendation="continue", human_queue_required=False
    )
    args = Namespace(command="gate", action="state-assess", run="RUN-1", stage="dev", artifact_ref=["a"], diff_hash="a" * 64, redacted_diff="redacted")
    with patch("agent_state_gate.cli._runtime", return_value=_runtime(service)):
        payload, code = dispatch_command(args)
    assert payload["recommendation"] == "continue" and code == 0


def test_dispatch_queue_take_and_resolve():
    service = MagicMock()
    service.database.take_attention.return_value = {"item_id": "Q-1"}
    service.database.resolve_attention.return_value = {"item_id": "Q-1", "status": "resolved"}
    with patch("agent_state_gate.cli._runtime", return_value=_runtime(service)):
        take, take_code = dispatch_command(Namespace(command="queue", action="take", item="Q-1", reviewer="reviewer"))
        resolved, resolve_code = dispatch_command(Namespace(command="queue", action="resolve", item="Q-1", reviewer="reviewer", resolution="approved", comment="ok"))
    assert take["item_id"] == "Q-1" and resolved["status"] == "resolved" and take_code == resolve_code == 0


def test_dispatch_audit_health_and_maintenance():
    service = MagicMock()
    service.database.list_audit_packets.return_value = [{"packet_id": "A-1"}]
    service.health.return_value = MagicMock(model_dump=lambda mode: {"ready": True}, ready=True)
    service.database.purge_expired.return_value = {"manifest_id": "PURGE-1"}
    args = [
        Namespace(command="audit", run=None),
        Namespace(command="health", action="check"),
        Namespace(command="maintenance", action="purge", rationale="test"),
    ]
    with patch("agent_state_gate.cli._runtime", return_value=_runtime(service)), patch("agent_state_gate.cli.require_role"):
        audit, _ = dispatch_command(args[0])
        health, _ = dispatch_command(args[1])
        purge, _ = dispatch_command(args[2])
    assert audit["packets"] and health["ready"] and purge["manifest_id"] == "PURGE-1"
