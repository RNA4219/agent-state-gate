"""
CLI module for agent-state-gate.

Provides command-line interface for:
- gate evaluation
- assessment management
- human queue operations
- audit packet generation
"""

import argparse
import json
import sys

from .audit.audit_packet import AuditPacket, AuditPacketStore, RetentionClass
from .common import __version__
from .core.assessment_engine import AssessmentEngine
from .queue.human_attention_queue import HumanAttentionQueue


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="agent-state-gate",
        description="Engineering governance integration layer"
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"agent-state-gate {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # gate evaluate command
    gate_parser = subparsers.add_parser("gate", help="Gate evaluation commands")
    gate_parser.add_argument("action", choices=["evaluate", "assess"], help="Action to perform")
    gate_parser.add_argument("--task", required=True, help="Task ID")
    gate_parser.add_argument("--run", required=True, help="Run ID")
    gate_parser.add_argument("--output", "-o", choices=["json", "text"], default="text", help="Output format")

    # queue commands
    queue_parser = subparsers.add_parser("queue", help="Human attention queue commands")
    queue_parser.add_argument("action", choices=["list", "take", "resolve"], help="Queue action")
    queue_parser.add_argument("--status", choices=["pending", "acknowledged", "in_review", "resolved"], help="Filter by status")
    queue_parser.add_argument("--item", help="Queue item ID for take/resolve")
    queue_parser.add_argument("--resolution", choices=["approved", "rejected", "escalated"], help="Resolution type")

    # audit commands
    audit_parser = subparsers.add_parser("audit", help="Audit commands")
    audit_parser.add_argument("action", choices=["generate", "export"], help="Audit action")
    audit_parser.add_argument("--task", help="Task ID")
    audit_parser.add_argument("--run", help="Run ID")
    audit_parser.add_argument("--format", choices=["jsonl", "json"], default="json", help="Export format")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    try:
        result = dispatch_command(args)
        output_result(result, args.output if hasattr(args, "output") else "text")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def dispatch_command(args) -> dict:
    """Dispatch command to appropriate handler."""
    if args.command == "gate":
        return handle_gate(args)
    elif args.command == "queue":
        return handle_queue(args)
    elif args.command == "audit":
        return handle_audit(args)
    else:
        raise ValueError(f"Unknown command: {args.command}")


def handle_gate(args) -> dict:
    """Handle gate evaluation commands."""
    engine = AssessmentEngine()

    if args.action == "assess":
        assessments = engine.list_assessments_by_task(args.task)
        return {
            "task_id": args.task,
            "assessments": [
                {
                    "assessment_id": a.assessment_id,
                    "verdict": a.final_verdict.value,
                    "reason": a.verdict_reason,
                    "created_at": a.created_at.isoformat()
                }
                for a in assessments
            ]
        }
    elif args.action == "evaluate":
        return {
            "task_id": args.task,
            "run_id": args.run,
            "status": "mock_evaluation",
            "message": "Gate evaluation requires adapter connections"
        }
    else:
        raise ValueError(f"Unknown gate action: {args.action}")


def handle_queue(args) -> dict:
    """Handle queue commands."""
    queue = HumanAttentionQueue()

    if args.action == "list":
        # Use get_pending_items for list action
        items = queue.get_pending_items()
        return {
            "items": [
                {
                    "item_id": i.item_id,
                    "task_id": i.task_id,
                    "severity": i.severity.value,
                    "status": i.status.value,
                    "created_at": i.created_at.isoformat()
                }
                for i in items
            ]
        }
    elif args.action == "take":
        if not args.item:
            raise ValueError("--item required for take action")
        item = queue.take_item(args.item)
        return {
            "item_id": item.item_id,
            "status": item.status.value,
            "acknowledged_at": item.acknowledged_at.isoformat() if item.acknowledged_at else None
        }
    elif args.action == "resolve":
        if not args.item:
            raise ValueError("--item required for resolve action")
        if not args.resolution:
            raise ValueError("--resolution required for resolve action")
        item = queue.resolve_item(args.item, args.resolution)
        return {
            "item_id": item.item_id,
            "status": item.status.value,
            "resolution": args.resolution
        }
    else:
        raise ValueError(f"Unknown queue action: {args.action}")


def handle_audit(args) -> dict:
    """Handle audit commands."""
    store = AuditPacketStore()

    if args.action == "generate":
        if not args.task:
            raise ValueError("--task required for generate action")
        # For CLI, create a minimal packet without full assessment
        from .common import generate_audit_packet_id, generate_span_id, generate_trace_id
        packet = AuditPacket(
            packet_id=generate_audit_packet_id(),
            trace_id=generate_trace_id(),
            span_id=generate_span_id(),
            assessment_id="CLI-GENERATED",
            run_id=args.run or "unknown",
            decision_packet_ref="",
            decision_packet_hash="",
            stale_check_result={},
            obligation_check_result={},
            approval_check_result={},
            evidence_check_result={},
            final_verdict="allow",
            verdict_reason="CLI generated packet",
            causal_trace=[],
            context_hash="",
            diff_hash="",
            threshold_version="",
            retention_class=RetentionClass.AUDIT,
            environment="local",
        )
        return {
            "audit_packet_id": packet.packet_id,
            "trace_id": packet.trace_id,
            "task_id": args.task,
            "created_at": packet.created_at.isoformat()
        }
    elif args.action == "export":
        # List from store
        packets = store.list_by_run(args.run or "all") if args.run else []
        return {
            "packets": [
                {
                    "audit_packet_id": p.packet_id,
                    "task_id": args.task if args.task else "unknown",
                    "trace_id": p.trace_id
                }
                for p in packets
            ]
        }
    else:
        raise ValueError(f"Unknown audit action: {args.action}")


def output_result(result: dict, format: str):
    """Output result in specified format."""
    if format == "json":
        print(json.dumps(result, indent=2))
    else:
        for key, value in result.items():
            if isinstance(value, list):
                print(f"{key}:")
                for item in value:
                    print(f"  - {item}")
            else:
                print(f"{key}: {value}")


if __name__ == "__main__":
    main()
