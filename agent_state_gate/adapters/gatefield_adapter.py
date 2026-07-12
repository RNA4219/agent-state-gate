"""
GatefieldAdapter Module

Adapter for agent-gatefield state-space gate evaluation.
Provides DecisionPacket ingestion, review queue, and audit export.

Reference: adapter_contract.md Section 1, 10.1
Reference: agent-gatefield DecisionPacket v2.0.0
"""

import os
from typing import Any

import requests

from agent_state_gate.config import GatefieldConfig

from .base import (
    AdapterMetadata,
    AdapterUnavailableError,
    BaseAdapter,
    DecisionNotFoundError,
    FailurePolicy,
    OperationMode,
)


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
    Failure Policy: fail-closed. Authentication/contract failures are configuration errors.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = GatefieldConfig.model_validate(config or {})
        self._session = requests.Session()
        environment_key = os.getenv("AGENT_GATEFIELD_API_KEY")
        if environment_key:
            self._session.headers["X-API-Key"] = environment_key

    @property
    def name(self) -> str:
        return "gatefield"

    @property
    def capability(self) -> str:
        return "state-space-gate"

    def readiness(self) -> dict[str, Any]:
        """Return backend/readiness evidence without reimplementing pgvector."""
        try:
            response = self._session.get(
                f"{self._config.base_url}/v1/health",
                timeout=self._config.timeout_seconds,
            )
            payload_raw = response.json()
            payload = payload_raw if isinstance(payload_raw, dict) else {}
            backend = payload.get("backend", {}) if isinstance(payload.get("backend", {}), dict) else {}
            pgvector_ready = bool(
                payload.get("pgvector_ready")
                or payload.get("pgvector")
                or backend.get("pgvector")
                or backend.get("pgvector_ready")
            )
            return {
                "healthy": response.status_code == 200,
                "pgvector_ready": pgvector_ready,
                "backend": backend,
            }
        except Exception as exc:
            return {"healthy": False, "pgvector_ready": False, "error_type": type(exc).__name__}

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
            timeout_ms=self._config.timeout_ms,
            failure_policy=FailurePolicy(self._config.failure_policy.value),
            audit_required=True
        )

    @staticmethod
    def _raise_for_gatefield_error(response, operation: str) -> None:
        if response.status_code in {429, 503}:
            raise AdapterUnavailableError("gatefield", f"{operation} unavailable ({response.status_code})")
        if response.status_code in {400, 401, 403}:
            try:
                body = response.json()
                code = body.get("error", {}).get("code", "contract_error")
            except Exception:
                code = "contract_error"
            raise ValueError(f"Gatefield {operation} configuration/contract error: {code}")

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
            DecisionPacket v2 (legacy URLs and field names retained).

        Raises:
            AdapterUnavailableError: If gatefield is unavailable.
        """
        trace_run_id = trace.get("run_id")
        artifact_run_id = artifact.get("run_id")
        if artifact_run_id and artifact_run_id != trace_run_id:
            raise ValueError("artifact.run_id and trace.run_id must match")
        evidence = artifact.get("semantic_evidence")
        redacted = artifact.get("redacted_artifact") or artifact.get("artifact")
        if (evidence is None) == (redacted is None):
            raise ValueError("exactly one redacted artifact or semantic evidence is required")

        payload = {
            "artifact_id": artifact.get("artifact_id"),
            "run_id": trace_run_id,
            "artifact_ref": artifact.get("artifact_ref"),
            "diff_hash": artifact.get("diff_hash"),
            "trace": trace,
        }
        if rule_results:
            payload["rule_results"] = rule_results
        if evidence is not None:
            payload["semantic_evidence"] = evidence
        else:
            payload["artifact"] = redacted

        try:
            response = self._session.post(
                f"{self._config.base_url}/v1/evaluate",
                json=payload,
                timeout=self._config.timeout_seconds
            )

            self._raise_for_gatefield_error(response, "evaluate")
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

            self._raise_for_gatefield_error(response, "review queue")

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

            self._raise_for_gatefield_error(response, "audit export")

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
            DecisionPacket v2.

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
            self._raise_for_gatefield_error(response, "decisions")

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

            self._raise_for_gatefield_error(response, "state-vectors")

            response.raise_for_status()
            return response.json()

        except requests.Timeout:
            raise AdapterUnavailableError(self.name, "get_state_vector timeout")
        except requests.ConnectionError:
            raise AdapterUnavailableError(self.name, "connection failed")
