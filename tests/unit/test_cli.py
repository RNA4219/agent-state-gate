"""
Unit tests for CLI module.

Tests command-line interface for agent-state-gate.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.cli import dispatch_command, handle_audit, handle_gate, handle_queue, main, output_result


class TestCLIMain:
    @patch("sys.argv", ["agent-state-gate", "--help"])
    def test_main_help(self):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0

    @patch("sys.argv", ["agent-state-gate", "--version"])
    def test_main_version(self):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0


class TestDispatchCommand:
    def test_dispatch_gate(self):
        args = MagicMock()
        args.command = "gate"
        args.action = "assess"
        args.task = "TASK-001"
        args.run = "RUN-001"
        args.output = "json"

        result = dispatch_command(args)
        assert "task_id" in result

    def test_dispatch_queue(self):
        args = MagicMock()
        args.command = "queue"
        args.action = "list"
        args.status = None

        result = dispatch_command(args)
        assert "items" in result

    def test_dispatch_audit(self):
        args = MagicMock()
        args.command = "audit"
        args.action = "export"

        result = dispatch_command(args)
        assert "packets" in result

    def test_dispatch_unknown(self):
        args = MagicMock()
        args.command = "unknown"
        with pytest.raises(ValueError):
            dispatch_command(args)


class TestHandleGate:
    def test_handle_gate_assess(self):
        args = MagicMock()
        args.action = "assess"
        args.task = "TASK-001"
        args.run = "RUN-001"

        result = handle_gate(args)
        assert result["task_id"] == "TASK-001"
        assert "assessments" in result

    def test_handle_gate_evaluate(self):
        args = MagicMock()
        args.action = "evaluate"
        args.task = "TASK-001"
        args.run = "RUN-001"

        result = handle_gate(args)
        assert result["task_id"] == "TASK-001"
        assert result["run_id"] == "RUN-001"
        assert result["status"] == "mock_evaluation"

    def test_handle_gate_unknown_action(self):
        args = MagicMock()
        args.action = "unknown"
        with pytest.raises(ValueError):
            handle_gate(args)


class TestHandleQueue:
    def test_handle_queue_list(self):
        args = MagicMock()
        args.action = "list"
        args.status = None

        result = handle_queue(args)
        assert "items" in result

    def test_handle_queue_list_with_status(self):
        args = MagicMock()
        args.action = "list"
        args.status = "pending"

        result = handle_queue(args)
        assert "items" in result

    def test_handle_queue_take_missing_item(self):
        args = MagicMock()
        args.action = "take"
        args.item = None

        with pytest.raises(ValueError, match="--item required"):
            handle_queue(args)

    def test_handle_queue_resolve_missing_item(self):
        args = MagicMock()
        args.action = "resolve"
        args.item = None
        args.resolution = "approved"

        with pytest.raises(ValueError, match="--item required"):
            handle_queue(args)

    def test_handle_queue_resolve_missing_resolution(self):
        args = MagicMock()
        args.action = "resolve"
        args.item = "ITEM-001"
        args.resolution = None

        with pytest.raises(ValueError, match="--resolution required"):
            handle_queue(args)


class TestHandleAudit:
    def test_handle_audit_export(self):
        args = MagicMock()
        args.action = "export"
        args.run = None

        result = handle_audit(args)
        assert "packets" in result

    def test_handle_audit_generate_missing_task(self):
        args = MagicMock()
        args.action = "generate"
        args.task = None
        args.run = "RUN-001"

        with pytest.raises(ValueError, match="--task required"):
            handle_audit(args)

    def test_handle_audit_generate_with_task(self):
        args = MagicMock()
        args.action = "generate"
        args.task = "TASK-001"
        args.run = "RUN-001"

        result = handle_audit(args)
        assert "audit_packet_id" in result
        assert "trace_id" in result


class TestOutputResult:
    def test_output_json(self, capsys):
        result = {"key": "value", "list": [1, 2, 3]}
        output_result(result, "json")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["key"] == "value"

    def test_output_text_simple(self, capsys):
        result = {"key": "value"}
        output_result(result, "text")

        captured = capsys.readouterr()
        assert "key: value" in captured.out

    def test_output_text_with_list(self, capsys):
        result = {"items": ["a", "b"]}
        output_result(result, "text")

        captured = capsys.readouterr()
        assert "items:" in captured.out
        assert "- a" in captured.out


class TestHandleAuditUnknown:
    def test_handle_audit_unknown_action(self):
        args = MagicMock()
        args.action = "unknown"

        with pytest.raises(ValueError, match="Unknown audit action"):
            handle_audit(args)


class TestHandleQueueUnknown:
    def test_handle_queue_unknown_action(self):
        args = MagicMock()
        args.action = "unknown"

        with pytest.raises(ValueError, match="Unknown queue action"):
            handle_queue(args)
