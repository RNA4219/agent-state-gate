"""
MemxAdapter Module

Adapter for memx-resolver docs/chunks/stale/ack operations.
Provides docs resolution, stale check, and read acknowledgment.

Reference: adapter_contract.md Section 4, 10.4
Reference: memx-resolver interfaces.md
"""

import json
import subprocess
from dataclasses import dataclass
from typing import Any

import requests

from .base import (
    AckFailedError,
    AdapterMetadata,
    AdapterUnavailableError,
    BaseAdapter,
    DocsNotFoundError,
    FailurePolicy,
    OperationMode,
    StaleCheckError,
)


@dataclass
class MemxConfig:
    """Configuration for MemxAdapter."""
    base_url: str | None = None  # HTTP API URL
    cli_path: str | None = None  # CLI path if HTTP not available
    api_key: str | None = None
    timeout_seconds: int = 3
    use_http: bool = True  # Prefer HTTP over CLI
    enabled: bool = True


class MemxAdapter(BaseAdapter):
    """
    Adapter for memx-resolver HTTP API or CLI.

    Capabilities:
    - Resolve required docs for task
    - Get chunks by doc ID
    - Acknowledge reads (append-only)
    - Check stale docs for task
    - Resolve contract

    Operation Mode: read + append-only ack
    Failure Policy: stale_blocked on docs not found
    """

    def __init__(self, config: dict[str, Any] = None):
        self._config = MemxConfig(**(config or {}))
        self._session = None
        if self._config.use_http and self._config.base_url:
            self._session = requests.Session()
            if self._config.api_key:
                self._session.headers["X-API-Key"] = self._config.api_key

    @property
    def name(self) -> str:
        return "memx"

    @property
    def capability(self) -> str:
        return "docs-stale-ack"

    def health_check(self) -> bool:
        """Check memx-resolver availability."""
        if self._session:
            try:
                response = self._session.get(
                    f"{self._config.base_url}/v1/health",
                    timeout=2
                )
                return response.status_code == 200
            except Exception:
                return False
        elif self._config.cli_path:
            try:
                result = subprocess.run(
                    [self._config.cli_path, "--help"],
                    capture_output=True,
                    timeout=2
                )
                return result.returncode == 0
            except Exception:
                return False
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

    def _http_call(
        self,
        method: str,
        endpoint: str,
        payload: dict | None = None
    ) -> dict[str, Any]:
        """Execute HTTP API call."""
        if not self._session:
            raise AdapterUnavailableError(self.name, "HTTP session not configured")

        try:
            if method == "GET":
                response = self._session.get(
                    endpoint,
                    timeout=self._config.timeout_seconds
                )
            elif method == "POST":
                response = self._session.post(
                    endpoint,
                    json=payload,
                    timeout=self._config.timeout_seconds
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            if response.status_code == 503:
                raise AdapterUnavailableError(self.name, "memx unavailable")
            if response.status_code == 404:
                raise DocsNotFoundError("unknown")

            response.raise_for_status()
            return response.json()

        except requests.Timeout:
            raise AdapterUnavailableError(self.name, "timeout")
        except requests.ConnectionError:
            raise AdapterUnavailableError(self.name, "connection failed")

    def _cli_call(self, command: str, args: list[str]) -> dict[str, Any]:
        """Execute CLI call."""
        if not self._config.cli_path:
            raise AdapterUnavailableError(self.name, "CLI path not configured")

        try:
            result = subprocess.run(
                [self._config.cli_path, command] + args,
                capture_output=True,
                timeout=self._config.timeout_seconds
            )

            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace")
                raise AdapterUnavailableError(self.name, f"CLI error: {stderr}")

            return json.loads(result.stdout.decode("utf-8"))

        except subprocess.TimeoutExpired:
            raise AdapterUnavailableError(self.name, "CLI timeout")
        except json.JSONDecodeError as e:
            raise AdapterUnavailableError(self.name, f"JSON decode error: {e}")

    def resolve_docs(
        self,
        task_id: str,
        action: str,
        feature: str | None = None,
        touched_paths: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Resolve required/recommended docs for task.

        Args:
            task_id: Task identifier.
            action: Action type (e.g., "implement", "review").
            feature: Optional feature identifier.
            touched_paths: Optional touched file paths.

        Returns:
            ResolveDocsResult with required_docs, recommended_docs.

        Raises:
            AdapterUnavailableError: If memx unavailable.
        """
        if self._session:
            payload = {
                "task_id": task_id,
                "action": action,
            }
            if feature:
                payload["feature"] = feature
            if touched_paths:
                payload["touched_paths"] = touched_paths

            return self._http_call(
                "POST",
                f"{self._config.base_url}/v1/docs/resolve",
                payload
            )
        else:
            args = ["--task", task_id, "--action", action]
            if feature:
                args.extend(["--feature", feature])
            if touched_paths:
                args.extend(["--paths", json.dumps(touched_paths)])

            return self._cli_call("docs:resolve", args)

    def get_chunks(
        self,
        doc_id: str,
        chunk_ids: list[str]
    ) -> list[dict[str, Any]]:
        """
        Get document chunks by IDs.

        Args:
            doc_id: Document identifier.
            chunk_ids: List of chunk IDs.

        Returns:
            List of chunk dicts.

        Raises:
            DocsNotFoundError: If doc not found.
        """
        if self._session:
            try:
                result = self._http_call(
                    "GET",
                    f"{self._config.base_url}/v1/docs/{doc_id}/chunks",
                    {"chunk_ids": chunk_ids}
                )
                return result.get("chunks", [])
            except DocsNotFoundError:
                raise DocsNotFoundError(doc_id)
        else:
            args = ["--doc", doc_id, "--chunks", json.dumps(chunk_ids)]
            result = self._cli_call("chunks:get", args)
            return result.get("chunks", [])

    def ack_reads(
        self,
        task_id: str,
        doc_id: str,
        version: str,
        chunk_ids: list[str]
    ) -> str:
        """
        Acknowledge reads for document chunks.

        Args:
            task_id: Task identifier.
            doc_id: Document identifier.
            version: Document version.
            chunk_ids: List of chunk IDs read.

        Returns:
            ack_ref (typed_ref format).

        Raises:
            AckFailedError: If ack fails.
        """
        if self._session:
            payload = {
                "task_id": task_id,
                "doc_id": doc_id,
                "version": version,
                "chunk_ids": chunk_ids,
            }
            try:
                result = self._http_call(
                    "POST",
                    f"{self._config.base_url}/v1/reads/ack",
                    payload
                )
                return result.get("ack_ref", "")
            except AdapterUnavailableError:
                raise AckFailedError(task_id, doc_id)
        else:
            args = [
                "--task", task_id,
                "--doc", doc_id,
                "--version", version,
                "--chunks", json.dumps(chunk_ids)
            ]
            try:
                result = self._cli_call("reads:ack", args)
                return result.get("ack_ref", "")
            except AdapterUnavailableError:
                raise AckFailedError(task_id, doc_id)

    def stale_check(
        self,
        task_id: str
    ) -> dict[str, Any]:
        """
        Check stale docs for task.

        Args:
            task_id: Task identifier.

        Returns:
            StaleCheckResult with stale_items, stale_reasons.

        Raises:
            StaleCheckError: If stale check fails.
        """
        if self._session:
            try:
                return self._http_call(
                    "GET",
                    f"{self._config.base_url}/v1/docs/stale-check?task_id={task_id}"
                )
            except AdapterUnavailableError as e:
                raise StaleCheckError(task_id, str(e))
        else:
            args = ["--task", task_id]
            try:
                return self._cli_call("docs:stale-check", args)
            except AdapterUnavailableError as e:
                raise StaleCheckError(task_id, str(e))

    def resolve_contract(
        self,
        contract_type: str,
        context: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Resolve contract for context.

        Args:
            contract_type: Contract type.
            context: Context dict.

        Returns:
            ContractRef dict.
        """
        if self._session:
            payload = {
                "contract_type": contract_type,
                "context": context,
            }
            return self._http_call(
                "POST",
                f"{self._config.base_url}/v1/contracts/resolve",
                payload
            )
        else:
            args = ["--type", contract_type, "--context", json.dumps(context)]
            return self._cli_call("contracts:resolve", args)
