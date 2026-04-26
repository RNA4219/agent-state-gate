"""
TaskstateAdapter Module

Adapter for agent-taskstate CLI/API.
Provides task/run/context_bundle management and event recording.

Reference: adapter_contract.md Section 2, 10.2
Reference: agent-taskstate MVP spec
"""

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from .base import (
    AdapterMetadata,
    AdapterUnavailableError,
    BaseAdapter,
    BundleNotFoundError,
    FailurePolicy,
    OperationMode,
    RunNotFoundError,
    TaskNotFoundError,
)


@dataclass
class TaskstateConfig:
    """Configuration for TaskstateAdapter."""
    cli_path: str = "agent-taskstate"
    timeout_seconds: int = 3
    working_dir: str | None = None
    enabled: bool = True


class TaskstateAdapter(BaseAdapter):
    """
    Adapter for agent-taskstate CLI.

    Capabilities:
    - Get task by ID
    - Get run by ID
    - Get context bundle by ID
    - Record read receipt (append-only event)
    - Append state event
    - List decisions for task

    Operation Mode: read + append-only event
    Failure Policy: fail-closed
    """

    def __init__(self, config: dict[str, Any] = None):
        self._config = TaskstateConfig(**(config or {}))

    @property
    def name(self) -> str:
        return "taskstate"

    @property
    def capability(self) -> str:
        return "task-state"

    def health_check(self) -> bool:
        """Check agent-taskstate CLI availability."""
        try:
            result = subprocess.run(
                [self._config.cli_path, "task", "list", "--limit", "1"],
                capture_output=True,
                timeout=2,
                cwd=self._config.working_dir
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name=self.name,
            capability=self.capability,
            operation_mode=OperationMode.APPEND_ONLY,
            timeout_ms=self._config.timeout_seconds * 1000,
            failure_policy=FailurePolicy.FAIL_CLOSED,
            audit_required=True
        )

    def _run_cli(self, args: list[str]) -> dict[str, Any]:
        """
        Execute agent-taskstate CLI command.

        Args:
            args: CLI arguments.

        Returns:
            JSON output dict.

        Raises:
            AdapterUnavailableError: If CLI fails.
        """
        try:
            result = subprocess.run(
                [self._config.cli_path] + args,
                capture_output=True,
                timeout=self._config.timeout_seconds,
                cwd=self._config.working_dir
            )

            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace")
                raise AdapterUnavailableError(
                    self.name,
                    f"CLI error: {stderr}"
                )

            return json.loads(result.stdout.decode("utf-8"))

        except subprocess.TimeoutExpired:
            raise AdapterUnavailableError(self.name, "CLI timeout")
        except json.JSONDecodeError as e:
            raise AdapterUnavailableError(self.name, f"JSON decode error: {e}")

    def get_task(
        self,
        task_id: str
    ) -> dict[str, Any]:
        """
        Get task by ID.

        Args:
            task_id: Task identifier.

        Returns:
            Task dict (MVP spec format).

        Raises:
            TaskNotFoundError: If task not found.
        """
        try:
            result = self._run_cli(["task", "show", "--task", task_id])
            return result
        except AdapterUnavailableError as e:
            # Check if it's a not-found error from stderr
            if "not found" in str(e).lower():
                raise TaskNotFoundError(task_id)
            raise

    def get_run(
        self,
        run_id: str
    ) -> dict[str, Any]:
        """
        Get run by ID.

        Args:
            run_id: Run identifier.

        Returns:
            Run dict (MVP spec format).

        Raises:
            RunNotFoundError: If run not found.
        """
        try:
            result = self._run_cli(["run", "show", "--run", run_id])
            return result
        except AdapterUnavailableError as e:
            if "not found" in str(e).lower():
                raise RunNotFoundError(run_id)
            raise

    def get_context_bundle(
        self,
        bundle_id: str
    ) -> dict[str, Any]:
        """
        Get context bundle by ID.

        Args:
            bundle_id: Bundle identifier.

        Returns:
            ContextBundle dict (MVP spec format).

        Raises:
            BundleNotFoundError: If bundle not found.
        """
        try:
            result = self._run_cli(["context", "show", "--bundle", bundle_id])
            return result
        except AdapterUnavailableError as e:
            if "not found" in str(e).lower():
                raise BundleNotFoundError(bundle_id)
            raise

    def record_read_receipt(
        self,
        task_id: str,
        doc_id: str,
        version: str,
        chunk_ids: list[str]
    ) -> str:
        """
        Record read receipt for document chunks.

        Args:
            task_id: Task identifier.
            doc_id: Document identifier.
            version: Document version.
            chunk_ids: List of chunk IDs read.

        Returns:
            receipt_id (typed_ref format).

        Raises:
            AdapterUnavailableError: If append fails.
        """
        event = {
            "event_type": "read_receipt",
            "doc_id": doc_id,
            "version": version,
            "chunk_ids": chunk_ids,
            "timestamp": _get_timestamp()
        }

        try:
            result = self._run_cli([
                "state", "append",
                "--task", task_id,
                "--event", json.dumps(event)
            ])
            return result.get("receipt_id", "")
        except AdapterUnavailableError:
            raise

    def append_state_event(
        self,
        task_id: str,
        event: dict[str, Any]
    ) -> str:
        """
        Append state event to task.

        Args:
            task_id: Task identifier.
            event: Event dict.

        Returns:
            event_id (typed_ref format).

        Raises:
            AdapterUnavailableError: If append fails.
        """
        try:
            result = self._run_cli([
                "state", "append",
                "--task", task_id,
                "--event", json.dumps(event)
            ])
            return result.get("event_id", "")
        except AdapterUnavailableError:
            raise

    def list_decisions(
        self,
        task_id: str
    ) -> list[dict[str, Any]]:
        """
        List decisions for a task.

        Args:
            task_id: Task identifier.

        Returns:
            List of decision dicts.

        Raises:
            TaskNotFoundError: If task not found.
        """
        try:
            result = self._run_cli(["decision", "list", "--task", task_id])
            return result.get("decisions", [])
        except AdapterUnavailableError as e:
            if "not found" in str(e).lower():
                raise TaskNotFoundError(task_id)
            raise


def _get_timestamp() -> str:
    """Get current ISO timestamp."""
    from ..common import iso_timestamp
    return iso_timestamp()
