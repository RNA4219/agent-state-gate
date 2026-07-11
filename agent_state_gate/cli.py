"""CLI backed by the same GateService used by MCP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .adapters import initialize_adapters
from .auth import OIDCAuthenticator, local_request_context, require_role
from .common import __version__
from .config import AppConfig, load_config
from .models import GateEvaluationRequest, RequestContext, StateGateAssessRequest
from .service import GateService, create_gate_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-state-gate", description="Production governance integration gate")
    parser.add_argument("--version", "-v", action="version", version=f"agent-state-gate {__version__}")
    parser.add_argument("--config", default="config/gate_config.yaml")
    parser.add_argument("--token", default=None, help="OIDC bearer token; defaults to AGENT_STATE_GATE_TOKEN")
    parser.add_argument("--tenant", default="local")
    parser.add_argument("--subject", default="cli-local")
    parser.add_argument("--roles", default="developer")
    parser.add_argument("--output", "-o", choices=["json", "text"], default="text")

    commands = parser.add_subparsers(dest="command", required=True)

    gate = commands.add_parser("gate")
    gate_actions = gate.add_subparsers(dest="action", required=True)
    evaluate = gate_actions.add_parser("evaluate")
    evaluate.add_argument("--task", required=True)
    evaluate.add_argument("--run", required=True)
    evaluate.add_argument("--action-type", default="edit_repo")
    evaluate.add_argument("--capability", action="append", default=[])
    evaluate.add_argument("--artifact-ref", action="append", default=[])
    evaluate.add_argument("--touched-path", action="append", default=[])
    evaluate.add_argument("--diff-hash")

    state_assess = gate_actions.add_parser("state-assess")
    state_assess.add_argument("--run", required=True)
    state_assess.add_argument("--stage", required=True)
    state_assess.add_argument("--artifact-ref", action="append", required=True)
    state_assess.add_argument("--diff-hash", required=True)
    state_assess.add_argument("--redacted-diff", required=True)

    queue = commands.add_parser("queue")
    queue_actions = queue.add_subparsers(dest="action", required=True)
    queue_list = queue_actions.add_parser("list")
    queue_list.add_argument("--status")
    queue_list.add_argument("--reviewer-role")
    queue_take = queue_actions.add_parser("take")
    queue_take.add_argument("--item", required=True)
    queue_take.add_argument("--reviewer", required=True)
    queue_resolve = queue_actions.add_parser("resolve")
    queue_resolve.add_argument("--item", required=True)
    queue_resolve.add_argument("--reviewer", required=True)
    queue_resolve.add_argument("--resolution", required=True)
    queue_resolve.add_argument("--comment", default="")

    replay = commands.add_parser("replay")
    replay.add_argument("--run", required=True)

    audit = commands.add_parser("audit")
    audit.add_argument("--run")

    health = commands.add_parser("health")
    health.set_defaults(action="check")

    maintenance = commands.add_parser("maintenance")
    maintenance_actions = maintenance.add_subparsers(dest="action", required=True)
    purge = maintenance_actions.add_parser("purge")
    purge.add_argument("--rationale", default="scheduled retention purge")

    return parser


def _context(config: AppConfig, args: argparse.Namespace) -> RequestContext:
    token = args.token or os.getenv("AGENT_STATE_GATE_TOKEN")
    if config.oidc.enabled:
        return OIDCAuthenticator(config.oidc).authenticate(token or "")
    return local_request_context(
        profile=config.runtime_profile,
        tenant_id=args.tenant,
        subject=args.subject,
        roles={role for role in args.roles.replace(",", " ").split() if role},
    )


def _runtime(args: argparse.Namespace) -> tuple[AppConfig, GateService, RequestContext]:
    config = load_config(args.config)
    registry = initialize_adapters(config)
    service = create_gate_service(config, registry)
    return config, service, _context(config, args)
class DispatchResult(tuple):
    """Tuple result that preserves the v0 mapping access used by integrations."""

    def __new__(cls, payload: dict[str, Any], exit_code: int):
        return super().__new__(cls, (payload, exit_code))

    @property
    def payload(self) -> dict[str, Any]:
        return tuple.__getitem__(self, 0)

    @property
    def exit_code(self) -> int:
        return tuple.__getitem__(self, 1)

    def __getitem__(self, key):
        if isinstance(key, str):
            return self.payload[key]
        return tuple.__getitem__(self, key)

    def __contains__(self, key):
        if isinstance(key, str):
            return key in self.payload
        return tuple.__contains__(self, key)



def _dispatch_command(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    config, service, context = _runtime(args)

    if args.command == "gate" and args.action == "evaluate":
        result = service.evaluate(
            GateEvaluationRequest(
                task_id=args.task,
                run_id=args.run,
                action=args.action_type,
                capabilities=args.capability,
                artifact_refs=args.artifact_ref,
                touched_paths=args.touched_path,
                diff_hash=args.diff_hash,
            ),
            context,
        )
        exit_code = {
            "allow": 0,
            "revise": 2,
            "needs_approval": 2,
            "require_human": 2,
            "stale_blocked": 2,
            "deny": 3,
        }[result.verdict]
        return result.model_dump(mode="json"), exit_code

    if args.command == "gate" and args.action == "state-assess":
        state_result = service.assess_state(
            StateGateAssessRequest(
                artifact_refs=args.artifact_ref,
                diff_hash=args.diff_hash,
                redacted_diff=args.redacted_diff,
                run_id=args.run,
                stage=args.stage,
            ),
            context,
        )
        return state_result.model_dump(mode="json"), 3 if state_result.recommendation == "block" else (2 if state_result.human_queue_required else 0)

    if args.command == "queue" and args.action == "list":
        items = service.database.list_attention(
            context.tenant_id,
            status=args.status,
            reviewer_role=args.reviewer_role,
        )
        return {"items": items, "count": len(items)}, 0

    if args.command == "queue" and args.action == "take":
        item = service.database.take_attention(context.tenant_id, args.item, args.reviewer)
        if item is None:
            raise ValueError("queue item is missing or no longer takeable")
        return item, 0

    if args.command == "queue" and args.action == "resolve":
        item = service.database.resolve_attention(
            context.tenant_id,
            args.item,
            reviewer=args.reviewer,
            resolution=args.resolution,
            comment=args.comment,
        )
        if item is None:
            raise ValueError("queue item cannot be resolved by this reviewer")
        return item, 0

    if args.command == "replay":
        replay_result = service.replay(args.run, None, context)
        return replay_result.model_dump(mode="json"), 0 if replay_result.reproducibility_verified else 2

    if args.command == "audit":
        return {"packets": service.database.list_audit_packets(context.tenant_id, args.run)}, 0

    if args.command == "health":
        health_result = service.health(context)
        return health_result.model_dump(mode="json"), 0 if health_result.ready else 1

    if args.command == "maintenance" and args.action == "purge":
        require_role(context, "governance_board", "data_retention_admin")
        return service.database.purge_expired(
            context.tenant_id,
            executed_by=context.subject,
            rationale=args.rationale,
        ), 0

    raise ValueError(f"unsupported command: {args.command}")


def output_result(result: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for key, value in result.items():
        print(f"{key}: {value}")
def dispatch_command(args: argparse.Namespace) -> DispatchResult:
    """Dispatch a command while retaining tuple unpacking and mapping access."""
    payload, exit_code = _dispatch_command(args)
    return DispatchResult(payload, exit_code)

def handle_gate(args: argparse.Namespace) -> dict[str, Any]:
    action = getattr(args, "action", None)
    if action == "assess":
        return {"task_id": args.task, "assessments": []}
    if action == "evaluate":
        return {"task_id": args.task, "run_id": args.run, "status": "mock_evaluation"}
    raise ValueError(f"Unknown gate action: {action}")

def handle_queue(args: argparse.Namespace) -> dict[str, Any]:
    action = getattr(args, "action", None)
    if action == "list":
        return {"items": []}
    if action in {"take", "resolve"} and not getattr(args, "item", None):
        raise ValueError("--item required")
    if action == "resolve" and not getattr(args, "resolution", None):
        raise ValueError("--resolution required")
    if action in {"take", "resolve"}:
        return {"item": args.item, "status": "updated"}
    raise ValueError(f"Unknown queue action: {action}")

def handle_audit(args: argparse.Namespace) -> dict[str, Any]:
    action = getattr(args, "action", None)
    if action == "export":
        return {"packets": []}
    if action == "generate":
        if not getattr(args, "task", None):
            raise ValueError("--task required")
        return {"audit_packet_id": f"audit:{args.task}:{getattr(args, 'run', '')}", "trace_id": getattr(args, "run", "") or "local"}
    raise ValueError(f"Unknown audit action: {action}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result, exit_code = dispatch_command(args)
        output_result(result, args.output)
        raise SystemExit(exit_code)
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
