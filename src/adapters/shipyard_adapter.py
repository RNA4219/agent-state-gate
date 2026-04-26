"""
ShipyardAdapter Module

Adapter for shipyard-cp HTTP API.
Provides pipeline stage management and transitions.

Reference: adapter_contract.md Section 5, 10.5
Reference: shipyard-cp api-contract.md
"""

from dataclasses import dataclass
from typing import Any

import requests

from .base import (
    AdapterMetadata,
    AdapterUnavailableError,
    BaseAdapter,
    FailurePolicy,
    OperationMode,
    StageNotFoundError,
    TransitionNotAllowedError,
)


@dataclass
class ShipyardConfig:
    """Configuration for ShipyardAdapter."""
    base_url: str = "http://localhost:3000"
    jwt_token: str | None = None
    timeout_seconds: int = 5
    enabled: bool = True


class ShipyardAdapter(BaseAdapter):
    """
    Adapter for shipyard-cp HTTP API.

    Capabilities:
    - Get pipeline stage for run
    - Hold for review
    - Resume from review
    - Get worker capabilities
    - Record transition

    Operation Mode: read + controlled-mutation
    Failure Policy: fail-closed for production
    """

    def __init__(self, config: dict[str, Any] = None):
        self._config = ShipyardConfig(**(config or {}))
        self._session = requests.Session()
        if self._config.jwt_token:
            self._session.headers["Authorization"] = f"Bearer {self._config.jwt_token}"

    @property
    def name(self) -> str:
        return "shipyard"

    @property
    def capability(self) -> str:
        return "pipeline-stage-transition"

    def health_check(self) -> bool:
        """Check shipyard-cp health endpoint."""
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
            operation_mode=OperationMode.CONTROLLED_MUTATION,
            timeout_ms=self._config.timeout_seconds * 1000,
            failure_policy=FailurePolicy.FAIL_CLOSED,
            audit_required=True
        )

    def _http_call(
        self,
        method: str,
        endpoint: str,
        payload: dict | None = None,
        task_id: str | None = None
    ) -> dict[str, Any]:
        """Execute HTTP API call."""
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
                raise AdapterUnavailableError(self.name, "shipyard unavailable")
            if response.status_code == 404:
                if task_id:
                    raise StageNotFoundError(task_id)
                raise AdapterUnavailableError(self.name, "resource not found")
            if response.status_code == 409:
                # Transition not allowed
                detail = response.json().get("detail", "unknown")
                raise TransitionNotAllowedError(
                    task_id or "unknown",
                    payload.get("from_stage", "unknown") if payload else "unknown",
                    payload.get("to_stage", "unknown") if payload else "unknown",
                    detail
                )

            response.raise_for_status()
            return response.json()

        except requests.Timeout:
            raise AdapterUnavailableError(self.name, "timeout")
        except requests.ConnectionError:
            raise AdapterUnavailableError(self.name, "connection failed")

    def get_pipeline_stage(
        self,
        run_id: str
    ) -> dict[str, Any]:
        """
        Get pipeline stage for run.

        Args:
            run_id: Run identifier.

        Returns:
            Stage dict with stage, status, blocked_reason.

        Raises:
            StageNotFoundError: If run not found.
        """
        return self._http_call(
            "GET",
            f"{self._config.base_url}/v1/tasks/{run_id}",
            task_id=run_id
        )

    def hold_for_review(
        self,
        run_id: str,
        assessment_id: str,
        reason: str
    ) -> str:
        """
        Hold pipeline for review.

        Args:
            run_id: Run identifier.
            assessment_id: Assessment identifier.
            reason: Hold reason.

        Returns:
            hold_id (UUID).

        Raises:
            TransitionNotAllowedError: If transition not allowed.
        """
        payload = {
            "transition_type": "hold_for_review",
            "assessment_id": assessment_id,
            "reason": reason,
        }

        result = self._http_call(
            "POST",
            f"{self._config.base_url}/v1/tasks/{run_id}/transitions",
            payload=payload,
            task_id=run_id
        )

        return result.get("hold_id", "")

    def resume_from_review(
        self,
        run_id: str,
        hold_id: str,
        resolution: str
    ) -> bool:
        """
        Resume pipeline from review hold.

        Args:
            run_id: Run identifier.
            hold_id: Hold identifier.
            resolution: Resolution (approved/rejected/revoked).

        Returns:
            True if successful.

        Raises:
            TransitionNotAllowedError: If transition not allowed.
        """
        payload = {
            "transition_type": "resume_from_review",
            "hold_id": hold_id,
            "resolution": resolution,
        }

        try:
            result = self._http_call(
                "POST",
                f"{self._config.base_url}/v1/tasks/{run_id}/transitions",
                payload=payload,
                task_id=run_id
            )
            return result.get("success", False)
        except TransitionNotAllowedError:
            return False

    def get_worker_capabilities(
        self,
        worker_id: str
    ) -> list[str]:
        """
        Get worker capabilities.

        Args:
            worker_id: Worker identifier.

        Returns:
            List of capability strings.

        Raises:
            AdapterUnavailableError: If worker not found.
        """
        result = self._http_call(
            "GET",
            f"{self._config.base_url}/v1/workers/{worker_id}/caps"
        )
        return result.get("capabilities", [])

    def record_transition(
        self,
        run_id: str,
        from_stage: str,
        to_stage: str,
        reason: str
    ) -> str:
        """
        Record pipeline transition.

        Args:
            run_id: Run identifier.
            from_stage: Source stage.
            to_stage: Target stage.
            reason: Transition reason.

        Returns:
            transition_id (UUID).

        Raises:
            TransitionNotAllowedError: If transition not allowed.
        """
        payload = {
            "transition_type": "stage_change",
            "from_stage": from_stage,
            "to_stage": to_stage,
            "reason": reason,
        }

        result = self._http_call(
            "POST",
            f"{self._config.base_url}/v1/tasks/{run_id}/transitions",
            payload=payload,
            task_id=run_id
        )

        return result.get("transition_id", "")
