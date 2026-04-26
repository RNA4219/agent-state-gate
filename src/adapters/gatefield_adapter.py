"""
GatefieldAdapter Module

Adapter for agent-gatefield state-space gate evaluation.
Provides DecisionPacket ingestion, review queue, and audit export.

Reference: adapter_contract.md Section 1, 10.1
Reference: agent-gatefield DATA_TYPES_SPEC v1.0.0
"""

from dataclasses import dataclass
from typing import Any

import requests

from .base import (
    AdapterMetadata,
    AdapterUnavailableError,
    BaseAdapter,
    DecisionNotFoundError,
    FailurePolicy,
    OperationMode,
)


@dataclass
class GatefieldConfig:
    """Configuration for GatefieldAdapter."""
    base_url: str = "http://localhost:8080"
    api_key: str | None = None
    timeout_seconds: int = 5
    enabled: bool = True


class GatefieldAdapter(BaseAdapter):
    """
    Adapter for agent-gatefield HTTP API.

    Capabilities:
    - Evaluate artifact for gate decision
    - Enqueue review items
    - Export audit events
    - Get DecisionPacket by ID
    - Get StateVector by run_id

    Operation Mode: read + append-only decision
    Failure Policy: fail-closed for production, fail-open for dev
    """

    def __init__(self, config: dict[str, Any] = None):
        self._config = GatefieldConfig(**(config or {}))
        self._session = requests.Session()
        if self._config.api_key:
            self._session.headers["X-API-Key"] = self._config.api_key

    @property
    def name(self) -> str:
        return "gatefield"

    @property
    def capability(self) -> str:
        return "state-space-gate"

    def health_check(self) -> bool:
        """Check agent-gatefield health endpoint."""
        try:
            response = self._session.get(
                f"{self._config.base_url}/v1/health",
                timeout=2
            )
            return response.status_code == 200
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

    def evaluate(
        self,
        artifact: dict[str, Any],
        trace: dict[str, Any],
        rule_results: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Evaluate artifact for gate decision.

        Args:
            artifact: Artifact dict with artifact_id, artifact_ref, diff_hash.
            trace: Trace dict with run_id, trace_id, context.
            rule_results: Optional pre-computed rule results.

        Returns:
            DecisionPacket (DATA_TYPES_SPEC v1.0.0 format).

        Raises:
            AdapterUnavailableError: If gatefield is unavailable.
        """
        payload = {
            "artifact_id": artifact.get("artifact_id"),
            "run_id": trace.get("run_id"),
            "artifact_ref": artifact.get("artifact_ref"),
            "diff_hash": artifact.get("diff_hash"),
            "trace": trace,
        }
        if rule_results:
            payload["rule_results"] = rule_results

        try:
            response = self._session.post(
                f"{self._config.base_url}/v1/evaluate",
                json=payload,
                timeout=self._config.timeout_seconds
            )

            if response.status_code == 503:
                raise AdapterUnavailableError(self.name, "evaluate endpoint unavailable")

            response.raise_for_status()
            return response.json()

        except requests.Timeout:
            raise AdapterUnavailableError(self.name, "evaluate timeout")
        except requests.ConnectionError:
            raise AdapterUnavailableError(self.name, "connection failed")

    def enqueue_review(
        self,
        review_item: dict[str, Any]
    ) -> str:
        """
        Enqueue item for human review.

        Args:
            review_item: Dict with decision_id, run_id, severity, top_factors.

        Returns:
            review_id (UUID).

        Raises:
            AdapterUnavailableError: If gatefield is unavailable.
        """
        try:
            response = self._session.post(
                f"{self._config.base_url}/v1/review/items",
                json=review_item,
                timeout=self._config.timeout_seconds
            )

            if response.status_code == 503:
                raise AdapterUnavailableError(self.name, "review queue unavailable")

            response.raise_for_status()
            return response.json()["review_id"]

        except requests.Timeout:
            raise AdapterUnavailableError(self.name, "enqueue_review timeout")
        except requests.ConnectionError:
            raise AdapterUnavailableError(self.name, "connection failed")

    def export_audit(
        self,
        run_id: str
    ) -> dict[str, Any]:
        """
        Export audit events for a run.

        Args:
            run_id: Run identifier.

        Returns:
            Dict with audit_events array.

        Raises:
            AdapterUnavailableError: If gatefield is unavailable.
        """
        try:
            response = self._session.get(
                f"{self._config.base_url}/v1/audit/{run_id}",
                timeout=self._config.timeout_seconds
            )

            if response.status_code == 503:
                raise AdapterUnavailableError(self.name, "audit export unavailable")

            response.raise_for_status()
            return response.json()

        except requests.Timeout:
            raise AdapterUnavailableError(self.name, "export_audit timeout")
        except requests.ConnectionError:
            raise AdapterUnavailableError(self.name, "connection failed")

    def get_decision_packet(
        self,
        decision_id: str
    ) -> dict[str, Any]:
        """
        Get DecisionPacket by decision_id.

        Args:
            decision_id: Decision identifier.

        Returns:
            DecisionPacket (DATA_TYPES_SPEC v1.0.0 format).

        Raises:
            DecisionNotFoundError: If decision not found.
            AdapterUnavailableError: If gatefield is unavailable.
        """
        try:
            response = self._session.get(
                f"{self._config.base_url}/v1/decisions/{decision_id}",
                timeout=self._config.timeout_seconds
            )

            if response.status_code == 404:
                raise DecisionNotFoundError(decision_id)
            if response.status_code == 503:
                raise AdapterUnavailableError(self.name, "decisions endpoint unavailable")

            response.raise_for_status()
            return response.json()

        except requests.Timeout:
            raise AdapterUnavailableError(self.name, "get_decision_packet timeout")
        except requests.ConnectionError:
            raise AdapterUnavailableError(self.name, "connection failed")

    def get_state_vector(
        self,
        run_id: str
    ) -> dict[str, Any]:
        """
        Get StateVector by run_id.

        Args:
            run_id: Run identifier.

        Returns:
            StateVector (DATA_TYPES_SPEC format).

        Raises:
            AdapterUnavailableError: If gatefield is unavailable.
        """
        try:
            response = self._session.get(
                f"{self._config.base_url}/v1/state-vectors/{run_id}",
                timeout=self._config.timeout_seconds
            )

            if response.status_code == 503:
                raise AdapterUnavailableError(self.name, "state-vectors endpoint unavailable")

            response.raise_for_status()
            return response.json()

        except requests.Timeout:
            raise AdapterUnavailableError(self.name, "get_state_vector timeout")
        except requests.ConnectionError:
            raise AdapterUnavailableError(self.name, "connection failed")
