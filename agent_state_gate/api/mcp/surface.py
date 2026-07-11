"""MCP facade delegating all gate decisions to GateService."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from agent_state_gate.adapters import AdapterRegistry
from agent_state_gate.adapters.base import AdapterUnavailableError
from agent_state_gate.auth import local_request_context
from agent_state_gate.config import AppConfig, RuntimeProfile
from agent_state_gate.core import StaleSummary
from agent_state_gate.models import (
    GateEvaluationRequest,
    ReplayResult,
    RequestContext,
    StateGateAssessRequest,
    StateGateAssessResult,
)
from agent_state_gate.service import GateService, create_gate_service

from .types import (
    AttentionListResult,
    ContractRef,
    DocRef,
    EvaluateResult,
    RecallResult,
    SLAStatus,
    StaleCheckResult,
    StaleItem,
)


class MCPSurface:
    def __init__(
        self,
        adapter_registry: AdapterRegistry,
        assessment_engine: Any | None = None,
        human_queue: Any | None = None,
        evidence_recorder: Any | None = None,
        config: AppConfig | dict[str, Any] | None = None,
        gate_service: GateService | None = None,
    ):
        del assessment_engine, human_queue, evidence_recorder
        if config is None:
            self._config = AppConfig.model_validate(
                {"database": {"url": "sqlite:///:memory:"}, "runtime_profile": "local_advisory"}
            )
        elif isinstance(config, AppConfig):
            self._config = config
        else:
            self._config = AppConfig.model_validate(config)
        self._registry = adapter_registry
        self._service = gate_service or create_gate_service(self._config, adapter_registry)

    def _context(self, context: RequestContext | None) -> RequestContext:
        if context is not None:
            return context
        if self._config.runtime_profile not in {
            RuntimeProfile.LOCAL_ADVISORY,
            RuntimeProfile.CI_CONTRACT,
        }:
            raise PermissionError("RequestContext is required outside local/CI profiles")
        return local_request_context(
            profile=self._config.runtime_profile,
            tenant_id="local",
            subject="mcp-local",
            roles={"developer"},
        )

    def context_recall(
        self,
        task_id: str,
        action: str,
        feature: str | None = None,
        touched_paths: list[str] | None = None,
        limit: int = 10,
    ) -> RecallResult:
        memx_adapter: Any = self._registry.get("memx")
        if not memx_adapter:
            raise AdapterUnavailableError("memx", "adapter not registered")
        resolve_result = memx_adapter.resolve_docs(
            task_id=task_id,
            action=action,
            feature=feature,
            touched_paths=touched_paths,
        )
        required_docs = [
            DocRef(
                doc_id=str(item.get("doc_id", "")),
                version=str(item.get("version", "")),
                priority="required",
                doc_type=str(item.get("doc_type", "unknown")),
                title=str(item.get("title", "")),
            )
            for item in resolve_result.get("required_docs", [])[:limit]
        ]
        recommended_docs = [
            DocRef(
                doc_id=str(item.get("doc_id", "")),
                version=str(item.get("version", "")),
                priority="recommended",
                doc_type=str(item.get("doc_type", "unknown")),
                title=str(item.get("title", "")),
            )
            for item in resolve_result.get("recommended_docs", [])[:limit]
        ]
        contracts = [
            ContractRef(
                contract_id=str(item.get("contract_id", "")),
                contract_type=str(item.get("contract_type", "")),
                version=str(item.get("version", "")),
            )
            for item in resolve_result.get("contract_refs", [])
        ]
        stale_raw = resolve_result.get("stale_summary", {})
        return RecallResult(
            required_docs=required_docs,
            recommended_docs=recommended_docs,
            contract_refs=contracts,
            stale_summary=StaleSummary(
                fresh=bool(stale_raw.get("fresh", False)),
                stale_items=list(stale_raw.get("stale_items", [])),
                stale_reasons=list(stale_raw.get("stale_reasons", [])),
            ),
            ack_required=bool(required_docs),
        )

    def gate_evaluate(
        self,
        task_id: str,
        action: str,
        capabilities: list[str],
        risk_hints: dict[str, Any] | None = None,
        touched_paths: list[str] | None = None,
        *,
        run_id: str | None = None,
        artifact_refs: list[str] | None = None,
        diff_hash: str | None = None,
        semantic_evidence: dict[str, Any] | None = None,
        context: RequestContext | None = None,
    ) -> EvaluateResult:
        resolved_context = self._context(context)
        if run_id is None:
            if self._config.runtime_profile not in {
                RuntimeProfile.LOCAL_ADVISORY,
                RuntimeProfile.CI_CONTRACT,
            }:
                raise ValueError("run_id is required outside local/CI profiles")
            run_id = f"RUN-{task_id}"
        return self._service.evaluate(
            GateEvaluationRequest(
                task_id=task_id,
                run_id=run_id,
                action=action,
                capabilities=capabilities,
                risk_hints=risk_hints or {},
                touched_paths=touched_paths or [],
                artifact_refs=artifact_refs or [],
                diff_hash=diff_hash,
                semantic_evidence=semantic_evidence,
            ),
            resolved_context,
        )

    def context_stale_check(self, task_id: str) -> StaleCheckResult:
        memx_adapter: Any = self._registry.get("memx")
        if not memx_adapter:
            return StaleCheckResult(
                fresh=False,
                stale_items=[],
                stale_reasons=["memx adapter unavailable"],
                last_check_at=datetime.now().astimezone(),
            )
        try:
            result = memx_adapter.stale_check(task_id)
        except Exception as exc:
            return StaleCheckResult(
                fresh=False,
                stale_items=[],
                stale_reasons=[f"memx unavailable: {type(exc).__name__}"],
                last_check_at=datetime.now().astimezone(),
            )
        return StaleCheckResult(
            fresh=bool(result.get("fresh", False)),
            stale_items=[
                StaleItem(
                    item_type=str(item.get("item_type", "unknown")),
                    item_id=str(item.get("item_id", "")),
                    current_version=str(item.get("current_version", "")),
                    expected_version=str(item.get("expected_version", "")),
                    stale_reason=str(item.get("stale_reason", "")),
                )
                for item in result.get("stale_items", [])
            ],
            stale_reasons=[str(reason) for reason in result.get("stale_reasons", [])],
            last_check_at=datetime.now().astimezone(),
        )

    def state_gate_assess(
        self,
        artifact_refs: list[str],
        diff_hash: str,
        run_id: str,
        stage: str,
        *,
        redacted_diff: str | None = None,
        semantic_evidence: dict[str, Any] | None = None,
        context: RequestContext | None = None,
    ) -> StateGateAssessResult:
        if len(diff_hash) != 64:
            if self._config.runtime_profile not in {
                RuntimeProfile.LOCAL_ADVISORY,
                RuntimeProfile.CI_CONTRACT,
            }:
                raise ValueError("raw diff is forbidden outside local/CI profiles")
            redacted_diff = redacted_diff or diff_hash
            diff_hash = hashlib.sha256(diff_hash.encode()).hexdigest()
        return self._service.assess_state(
            StateGateAssessRequest(
                artifact_refs=artifact_refs,
                diff_hash=diff_hash,
                redacted_diff=redacted_diff,
                semantic_evidence=semantic_evidence,
                run_id=run_id,
                stage=stage,
            ),
            self._context(context),
        )

    def attention_list(
        self,
        queue_scope: str = "all",
        reviewer_role: str | None = None,
        status: str | None = None,
        *,
        context: RequestContext | None = None,
    ) -> AttentionListResult:
        del queue_scope
        resolved_context = self._context(context)
        items = self._service.database.list_attention(
            resolved_context.tenant_id,
            status=status,
            reviewer_role=reviewer_role,
        )
        by_severity = {
            severity: sum(item.get("severity") == severity for item in items)
            for severity in ("critical", "high", "medium", "low")
        }
        pending = sum(item.get("status") == "pending" for item in items)
        return AttentionListResult(
            items=items,
            total_pending=pending,
            by_severity=by_severity,
            sla_status={
                "global": SLAStatus(
                    pending_count=pending,
                    ack_timeout_count=0,
                    decision_timeout_count=0,
                    escalated_count=sum(item.get("status") == "escalated" for item in items),
                )
            },
        )

    def run_replay_context(
        self,
        run_id: str,
        as_of: datetime | None = None,
        *,
        context: RequestContext | None = None,
    ) -> ReplayResult:
        return self._service.replay(run_id, as_of, self._context(context))


def create_mcp_surface(
    adapter_registry: AdapterRegistry,
    config: AppConfig | dict[str, Any] | None = None,
) -> MCPSurface:
    return MCPSurface(adapter_registry=adapter_registry, config=config)


__all__ = ["MCPSurface", "create_mcp_surface"]
