"""Production application service for integrated gate evaluation."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from .adapters import AdapterRegistry
from .common import generate_audit_packet_id, hash_dict
from .config import AppConfig, RuntimeProfile
from .core.verdict_transformer import (
    ApprovalSummary,
    EvidenceSummary,
    ObligationSummary,
    StaleSummary,
    Verdict,
    resolve_verdict,
)
from .models import (
    AdapterHealth,
    AssessmentModel,
    DecisionPacket,
    EvaluateResult,
    EvidenceReport,
    GateEvaluationRequest,
    HealthReport,
    ReplayResult,
    ReplayStatus,
    RequestContext,
    RiskLevel,
    StateGateAssessRequest,
    StateGateAssessResult,
)
from .observability import Observability, configure_structured_logging
from .persistence import Database
from .typed_ref import audit_packet_ref, decision_ref

_VERDICT_PRIORITY = {
    Verdict.ALLOW.value: 1,
    Verdict.REVISE.value: 2,
    Verdict.NEEDS_APPROVAL.value: 3,
    Verdict.REQUIRE_HUMAN.value: 4,
    Verdict.STALE_BLOCKED.value: 5,
    Verdict.DENY.value: 6,
}


class GateService:
    """Single application-service boundary used by MCP and CLI."""

    def __init__(self, *, config: AppConfig, registry: AdapterRegistry, database: Database):
        self.config = config
        self.registry = registry
        self.database = database
        self.observability = Observability()
        self.logger = configure_structured_logging()

    def _require_context(self, context: RequestContext) -> None:
        if self.config.runtime_profile.is_production and not context.authenticated:
            raise PermissionError("authenticated RequestContext is required in production")

    @staticmethod
    def _more_restrictive(current: str, candidate: str) -> str:
        return candidate if _VERDICT_PRIORITY[candidate] > _VERDICT_PRIORITY[current] else current

    @staticmethod
    def _reason_for_verdict(verdict: str, reasons: list[str]) -> str:
        return "; ".join(dict.fromkeys(reasons)) if reasons else verdict.replace("_", " ")

    def _apply_failure(
        self,
        *,
        axis: str,
        risk_level: RiskLevel,
        action: str,
        verdict: str,
        reasons: list[str],
        unavailable_axes: list[str],
        applied: dict[str, str],
    ) -> str:
        if axis == "taskstate":
            candidate = Verdict.DENY.value
        elif axis == "memx":
            candidate = Verdict.STALE_BLOCKED.value
        elif axis in {"protocols", "workflow"}:
            candidate = Verdict.NEEDS_APPROVAL.value
        elif axis == "gatefield":
            if action in {"publish", "publish_release", "release"}:
                candidate = Verdict.DENY.value
            elif risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
                candidate = Verdict.REQUIRE_HUMAN.value
            else:
                candidate = Verdict.NEEDS_APPROVAL.value
        elif axis == "shipyard":
            candidate = (
                Verdict.DENY.value
                if risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
                else Verdict.REQUIRE_HUMAN.value
            )
        else:
            candidate = Verdict.NEEDS_APPROVAL.value
        unavailable_axes.append(axis)
        applied[axis] = candidate
        reasons.append(f"{axis} unavailable -> {candidate}")
        return self._more_restrictive(verdict, candidate)

    def _adapter_call(
        self,
        name: str,
        method: str,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[Any | None, Exception | None, float]:
        adapter = self.registry.get(name)
        if adapter is None:
            return None, RuntimeError(f"{name} adapter is not registered"), 0.0
        started = time.perf_counter()
        try:
            result = getattr(adapter, method)(*args, **kwargs)
            latency_ms = (time.perf_counter() - started) * 1000
            self.observability.record_adapter(name, latency_ms, True)
            return result, None, latency_ms
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            self.observability.record_adapter(name, latency_ms, False)
            self.logger.warning(
                "adapter call failed",
                extra={"adapter": name, "method": method, "error_type": type(exc).__name__},
            )
            return None, exc, latency_ms

    def evaluate(self, request: GateEvaluationRequest, context: RequestContext) -> EvaluateResult:
        self._require_context(context)
        reasons: list[str] = []
        unavailable_axes: list[str] = []
        applied: dict[str, str] = {}
        causal_trace: list[dict[str, Any]] = []
        verdict = Verdict.ALLOW.value
        risk_level = RiskLevel.MEDIUM

        task_data, task_error, _ = self._adapter_call("taskstate", "get_task", request.task_id)
        run_data, run_error, _ = self._adapter_call("taskstate", "get_run", request.run_id)
        if task_error or run_error:
            verdict = self._apply_failure(
                axis="taskstate",
                risk_level=risk_level,
                action=request.action,
                verdict=verdict,
                reasons=reasons,
                unavailable_axes=unavailable_axes,
                applied=applied,
            )
            task_data = task_data or {"task_id": request.task_id}
            run_data = run_data or {"run_id": request.run_id, "stage": "unknown"}

        context_bundle: dict[str, Any] = {}
        bundle_id = (run_data or {}).get("context_bundle_id") or (run_data or {}).get("context_bundle_ref")
        if bundle_id and not task_error:
            bundle_raw, bundle_error, _ = self._adapter_call("taskstate", "get_context_bundle", bundle_id)
            if bundle_error:
                verdict = self._apply_failure(
                    axis="taskstate",
                    risk_level=risk_level,
                    action=request.action,
                    verdict=verdict,
                    reasons=reasons,
                    unavailable_axes=unavailable_axes,
                    applied=applied,
                )
                context_bundle = {}
            elif isinstance(bundle_raw, dict):
                context_bundle = bundle_raw

        risk_value, protocols_error, _ = self._adapter_call(
            "protocols",
            "derive_risk_level",
            request.capabilities,
            request.risk_hints,
        )
        required_approvals: list[str] = []
        if protocols_error:
            verdict = self._apply_failure(
                axis="protocols",
                risk_level=risk_level,
                action=request.action,
                verdict=verdict,
                reasons=reasons,
                unavailable_axes=unavailable_axes,
                applied=applied,
            )
        else:
            risk_level = RiskLevel(str(risk_value))
            approvals, approval_error, _ = self._adapter_call(
                "protocols",
                "derive_required_approvals",
                risk_level.value,
                request.capabilities,
            )
            if approval_error:
                verdict = self._apply_failure(
                    axis="protocols",
                    risk_level=risk_level,
                    action=request.action,
                    verdict=verdict,
                    reasons=reasons,
                    unavailable_axes=unavailable_axes,
                    applied=applied,
                )
            else:
                required_approvals = list(approvals or [])

        safety_sources = [item for item in (task_data, run_data) if isinstance(item, dict)]
        hard_safety_keys = ("hard_block", "secret_detected", "compliance_violation")
        if any(bool(source.get(key)) for source in safety_sources for key in hard_safety_keys):
            verdict = self._more_restrictive(verdict, Verdict.DENY.value)
            reasons.append("hard safety indicator detected")

        stale_raw, stale_error, _ = self._adapter_call("memx", "stale_check", request.task_id)
        if stale_error:
            verdict = self._apply_failure(
                axis="memx",
                risk_level=risk_level,
                action=request.action,
                verdict=verdict,
                reasons=reasons,
                unavailable_axes=unavailable_axes,
                applied=applied,
            )
            stale_raw = {"fresh": False, "stale_items": [], "stale_reasons": ["memx unavailable"]}
        stale_summary = StaleSummary(
            fresh=bool((stale_raw or {}).get("fresh", False)),
            stale_items=list((stale_raw or {}).get("stale_items", [])),
            stale_reasons=list((stale_raw or {}).get("stale_reasons", [])),
        )

        evidence_raw, workflow_error, _ = self._adapter_call(
            "workflow",
            "get_evidence_report",
            request.task_id,
            (run_data or {}).get("stage"),
        )
        try:
            evidence_report = EvidenceReport.from_adapter(evidence_raw or {}) if not workflow_error else None
        except ValidationError as exc:
            workflow_error = exc
            evidence_report = None
        if workflow_error or evidence_report is None:
            verdict = self._apply_failure(
                axis="workflow",
                risk_level=risk_level,
                action=request.action,
                verdict=verdict,
                reasons=reasons,
                unavailable_axes=unavailable_axes,
                applied=applied,
            )
            evidence_report = EvidenceReport(required_evidence=["workflow-contract"], collected_evidence=[])

        approved_roles = set((run_data or {}).get("approved_roles", []))
        missing_approvals = [role for role in required_approvals if role not in approved_roles]
        approval_summary = ApprovalSummary(
            missing_approvals=missing_approvals,
            required_approvals=required_approvals,
            approved_roles=sorted(approved_roles),
            approval_rate=(len(required_approvals) - len(missing_approvals)) / len(required_approvals)
            if required_approvals
            else 1.0,
        )

        obligation_raw = (task_data or {}).get("obligation_summary", {"fulfillment_rate": 1.0})
        obligation_summary = ObligationSummary(
            fulfillment_rate=float(obligation_raw.get("fulfillment_rate", 1.0)),
            has_critical_unfulfilled=bool(obligation_raw.get("has_critical_unfulfilled", False)),
            has_high_unfulfilled=bool(obligation_raw.get("has_high_unfulfilled", False)),
            unfulfilled_items=list(obligation_raw.get("unfulfilled_items", [])),
        )
        evidence_summary = EvidenceSummary(
            evidence_strength=evidence_report.computed_strength,
            required_evidence=evidence_report.required_evidence,
            collected_evidence=evidence_report.collected_evidence,
            unlinked_evidence=evidence_report.unlinked_evidence,
        )

        critical_sla_timeout = any(
            str(source.get("sla_status", "")).lower() == "timeout"
            and str(source.get("severity", "")).lower() == "critical"
            for source in safety_sources
        )
        if risk_level == RiskLevel.CRITICAL and critical_sla_timeout:
            verdict = self._more_restrictive(verdict, Verdict.DENY.value)
            reasons.append("critical SLA timeout")
        artifact: dict[str, Any] = {
            "artifact_id": request.artifact_refs[0] if request.artifact_refs else f"task:{request.task_id}",
            "artifact_ref": request.artifact_refs[0] if request.artifact_refs else "",
            "diff_hash": request.diff_hash,
            "run_id": request.run_id,
        }
        if request.semantic_evidence is not None:
            artifact["semantic_evidence"] = request.semantic_evidence
        else:
            artifact["redacted_artifact"] = {
                "artifact_refs": request.artifact_refs,
                "touched_paths": request.touched_paths,
                "action": request.action,
            }
        packet_raw, gatefield_error, _ = self._adapter_call(
            "gatefield",
            "evaluate",
            artifact,
            {"run_id": request.run_id, "trace_id": context.trace_id, "tenant_id": context.tenant_id},
            {},
        )
        packet: DecisionPacket | None = None
        if not gatefield_error:
            try:
                packet = DecisionPacket.model_validate(packet_raw)
            except ValidationError as exc:
                gatefield_error = exc
        if gatefield_error or packet is None:
            verdict = self._apply_failure(
                axis="gatefield",
                risk_level=risk_level,
                action=request.action,
                verdict=verdict,
                reasons=reasons,
                unavailable_axes=unavailable_axes,
                applied=applied,
            )
        else:
            transformed = resolve_verdict(
                packet.decision,
                stale_summary,
                obligation_summary,
                approval_summary,
                evidence_summary,
                permission_level="admin" if "admin" in context.roles else "standard",
                uncertainty_score=packet.uncertainty_score,
                self_correction_count=packet.self_correction_count,
            ).value
            verdict = self._more_restrictive(verdict, transformed)
            reasons.append(f"gatefield={packet.decision} -> {transformed}")
            causal_trace.append(
                {
                    "source": "gatefield",
                    "decision_id": packet.decision_id,
                    "decision": packet.decision,
                    "threshold_version": packet.threshold_version,
                }
            )

        stage_raw, shipyard_error, _ = self._adapter_call("shipyard", "get_pipeline_stage", request.run_id)
        if shipyard_error:
            verdict = self._apply_failure(
                axis="shipyard",
                risk_level=risk_level,
                action=request.action,
                verdict=verdict,
                reasons=reasons,
                unavailable_axes=unavailable_axes,
                applied=applied,
            )
            stage = str((run_data or {}).get("stage", "unknown"))
        else:
            stage = str((stage_raw or {}).get("stage", (run_data or {}).get("stage", "unknown")))

        context_payload = {
            "tenant_id": context.tenant_id,
            "task": task_data,
            "run": run_data,
            "context_bundle": context_bundle,
            "stale": stale_raw,
            "obligation": obligation_raw,
            "approvals": {
                "required": required_approvals,
                "approved": sorted(approved_roles),
            },
            "evidence": evidence_report.model_dump(mode="json"),
            "decision_packet": packet.model_dump(mode="json") if packet else None,
        }
        context_hash = hash_dict(context_payload)
        assessment_id = f"ASM-{uuid.uuid4().hex}"
        packet_ref = decision_ref(packet.decision_id) if packet else ""
        policy_version = packet.policy_version if packet else str(self.config.version)
        threshold_version = packet.threshold_version if packet else ""
        assessment = AssessmentModel(
            assessment_id=assessment_id,
            tenant_id=context.tenant_id,
            task_id=request.task_id,
            run_id=request.run_id,
            stage=stage,
            decision_packet_ref=packet_ref,
            final_verdict=verdict,
            verdict_reason=self._reason_for_verdict(verdict, reasons),
            context_hash=context_hash,
            diff_hash=request.diff_hash or ("0" * 64),
            policy_version=policy_version,
            threshold_version=threshold_version,
            degraded=bool(unavailable_axes),
            unavailable_axes=sorted(set(unavailable_axes)),
            failure_policy_applied=applied,
            causal_trace=causal_trace,
            evidence_summary=evidence_report.model_dump(mode="json"),
            approval_summary={
                "required_approvals": required_approvals,
                "approved_roles": sorted(approved_roles),
                "missing_approvals": missing_approvals,
            },
        )
        self.database.save_assessment(assessment)

        audit_id = generate_audit_packet_id()
        audit_payload = {
            "packet_id": audit_id,
            "tenant_id": context.tenant_id,
            "trace_id": context.trace_id,
            "assessment": assessment.model_dump(mode="json"),
            "unavailable_axes": assessment.unavailable_axes,
            "failure_policy_applied": applied,
        }
        self.database.append_audit_packet(
            packet_id=audit_id,
            tenant_id=context.tenant_id,
            run_id=request.run_id,
            assessment_id=assessment_id,
            retention_class="audit" if verdict != Verdict.ALLOW.value else "ops",
            payload=audit_payload,
        )
        context_identity_hash = hash_dict(
            {
                "tenant_id": context.tenant_id,
                "subject": context.subject,
                "roles": sorted(context.roles),
            }
        )

        snapshot_payload = {
            "request": request.model_dump(mode="json"),
            "context_payload": context_payload,
            "expected_verdict": verdict,
            "assessment_id": assessment_id,
            "policy_version": policy_version,
            "context_identity_hash": context_identity_hash,
            "threshold_version": threshold_version,
            "failure_policy_applied": applied,
            "audit_packet_ref": audit_packet_ref(audit_id),
        }
        attestation_hash = hash_dict(snapshot_payload)
        self.database.save_snapshot(
            tenant_id=context.tenant_id,
            run_id=request.run_id,
            assessment_id=assessment_id,
            attestation_hash=attestation_hash,
            payload=snapshot_payload,
        )
        self.observability.record_verdict(
            verdict,
            assessment.degraded,
            self.config.runtime_profile.value,
        )
        self.logger.info(
            "gate evaluation completed",
            extra={
                "tenant_id": context.tenant_id,
                "task_id": request.task_id,
                "run_id": request.run_id,
                "verdict": verdict,
                "degraded": assessment.degraded,
                "unavailable_axes": assessment.unavailable_axes,
            },
        )
        if verdict in {Verdict.NEEDS_APPROVAL.value, Verdict.REQUIRE_HUMAN.value, Verdict.STALE_BLOCKED.value}:
            self.database.enqueue_attention(
                tenant_id=context.tenant_id,
                payload={
                    "assessment_id": assessment_id,
                    "task_id": request.task_id,
                    "run_id": request.run_id,
                    "severity": risk_level.value,
                    "required_role": required_approvals[0] if required_approvals else "governance_board",
                    "status": "pending",
                    "verdict": verdict,
                    "reason": assessment.verdict_reason,
                },
            )
        return EvaluateResult(
            verdict=verdict,
            assessment_id=assessment_id,
            verdict_reason=assessment.verdict_reason,
            runtime_profile=self.config.runtime_profile,
            degraded=assessment.degraded,
            unavailable_axes=assessment.unavailable_axes,
            failure_policy_applied=applied,
            policy_version=policy_version,
            audit_packet_ref=audit_packet_ref(audit_id),
            required_evidence=evidence_report.required_evidence,
            required_approvals=required_approvals,
            causal_trace=causal_trace,
        )

    def assess_state(self, request: StateGateAssessRequest, context: RequestContext) -> StateGateAssessResult:
        self._require_context(context)
        artifact: dict[str, Any] = {
            "artifact_id": request.artifact_refs[0],
            "artifact_ref": request.artifact_refs[0],
            "diff_hash": request.diff_hash,
            "run_id": request.run_id,
        }
        if request.semantic_evidence is not None:
            artifact["semantic_evidence"] = request.semantic_evidence
        else:
            artifact["redacted_artifact"] = request.redacted_diff
        raw, error, _ = self._adapter_call(
            "gatefield",
            "evaluate",
            artifact,
            {"run_id": request.run_id, "trace_id": context.trace_id, "stage": request.stage},
            {},
        )
        if error:
            recommendation = "block" if request.stage in {"publish", "release"} else "hold_for_review"
            return StateGateAssessResult(
                assessment_id=f"ASM-{uuid.uuid4().hex}",
                recommendation=recommendation,
                human_queue_required=True,
                degraded=True,
                unavailable_axes=["gatefield"],
            )
        try:
            packet = DecisionPacket.model_validate(raw)
        except ValidationError:
            return StateGateAssessResult(
                assessment_id=f"ASM-{uuid.uuid4().hex}",
                recommendation="hold_for_review",
                human_queue_required=True,
                degraded=True,
                unavailable_axes=["gatefield"],
            )
        recommendation = {
            "pass": "continue",
            "warn": "self_correct",
            "hold": "hold_for_review",
            "block": "block",
        }[packet.decision]
        return StateGateAssessResult(
            assessment_id=f"ASM-{uuid.uuid4().hex}",
            decision_packet_ref=decision_ref(packet.decision_id),
            scores={factor.name: factor.value for factor in packet.factors},
            recommendation=recommendation,
            human_queue_required=packet.decision == "hold"
            or (packet.decision == "warn" and packet.self_correction_count >= 2),
            exemplar_refs=[str(item.get("doc_id", "")) for item in packet.exemplar_refs],
            threshold_version=packet.threshold_version,
        )

    def _recompute_snapshot_verdict(self, snapshot: dict[str, Any], context: RequestContext) -> str:
        payload = snapshot.get("context_payload", {})
        stale_raw = payload.get("stale", {})
        obligation_raw = payload.get("obligation", {})
        approvals_raw = payload.get("approvals", {})
        evidence_raw = payload.get("evidence", {})
        packet_raw = payload.get("decision_packet")
        verdict = Verdict.ALLOW.value
        if packet_raw:
            packet = DecisionPacket.model_validate(packet_raw)
            required = list(evidence_raw.get("required_evidence", []))
            collected = list(evidence_raw.get("collected_evidence", []))
            strength = 1.0 if not required else len(set(required) & set(collected)) / len(set(required))
            transformed = resolve_verdict(
                packet.decision,
                StaleSummary(
                    fresh=bool(stale_raw.get("fresh", False)),
                    stale_items=list(stale_raw.get("stale_items", [])),
                    stale_reasons=list(stale_raw.get("stale_reasons", [])),
                ),
                ObligationSummary(
                    fulfillment_rate=float(obligation_raw.get("fulfillment_rate", 1.0)),
                    has_critical_unfulfilled=bool(obligation_raw.get("has_critical_unfulfilled", False)),
                    has_high_unfulfilled=bool(obligation_raw.get("has_high_unfulfilled", False)),
                    unfulfilled_items=list(obligation_raw.get("unfulfilled_items", [])),
                ),
                ApprovalSummary(
                    required_approvals=list(approvals_raw.get("required", [])),
                    approved_roles=list(approvals_raw.get("approved", [])),
                    missing_approvals=[
                        role
                        for role in approvals_raw.get("required", [])
                        if role not in approvals_raw.get("approved", [])
                    ],
                ),
                EvidenceSummary(
                    evidence_strength=strength,
                    required_evidence=required,
                    collected_evidence=collected,
                    unlinked_evidence=list(evidence_raw.get("unlinked_evidence", [])),
                ),
                permission_level="admin" if "admin" in context.roles else "standard",
                uncertainty_score=packet.uncertainty_score,
                self_correction_count=packet.self_correction_count,
            ).value
            verdict = self._more_restrictive(verdict, transformed)
        for applied_verdict in snapshot.get("failure_policy_applied", {}).values():
            verdict = self._more_restrictive(verdict, str(applied_verdict))
        return verdict

    def replay(
        self,
        run_id: str,
        as_of: datetime | None,
        context: RequestContext,
    ) -> ReplayResult:
        self._require_context(context)
        snapshot = self.database.latest_snapshot(context.tenant_id, run_id)
        if snapshot is None:
            return ReplayResult(
                run_id=run_id, status=ReplayStatus.UNAVAILABLE, details={"reason": "snapshot not found"}
            )
        snapshot_created_at = snapshot.created_at
        if snapshot_created_at.tzinfo is None:
            snapshot_created_at = snapshot_created_at.replace(tzinfo=UTC)
        if as_of is not None:
            if as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=UTC)
            if snapshot_created_at > as_of:
                return ReplayResult(
                    run_id=run_id,
                    status=ReplayStatus.UNAVAILABLE,
                    details={"reason": "no snapshot at requested time"},
                )
        current_hash = hash_dict(snapshot.payload)
        assessment = self.database.get_assessment(context.tenant_id, snapshot.assessment_id)
        if assessment is None:
            return ReplayResult(
                run_id=run_id,
                status=ReplayStatus.UNAVAILABLE,
                attestation_hash=current_hash,
                details={"reason": "assessment not found"},
            )
        expected = str(snapshot.payload.get("expected_verdict"))
        actual = self._recompute_snapshot_verdict(snapshot.payload, context)
        expected_context_hash = snapshot.payload.get("context_identity_hash")
        current_context_hash = hash_dict(
            {"tenant_id": context.tenant_id, "subject": context.subject, "roles": sorted(context.roles)}
        )
        context_matches = expected_context_hash is None or expected_context_hash == current_context_hash
        policy_matches = snapshot.payload.get("policy_version") in {None, self.config.version}
        status = (
            ReplayStatus.VERIFIED
            if current_hash == snapshot.attestation_hash
            and expected == actual
            and assessment.final_verdict == actual
            and context_matches
            and policy_matches
            else ReplayStatus.MISMATCH
        )
        if status == ReplayStatus.MISMATCH:
            self.observability.replay_mismatch.add(1, {"tenant_id": context.tenant_id})
        return ReplayResult(
            run_id=run_id,
            status=status,
            expected_verdict=expected,
            actual_verdict=actual,
            attestation_hash=current_hash,
            audit_packet_ref=str(snapshot.payload.get("audit_packet_ref", "")),
        )

    def health(self, context: RequestContext) -> HealthReport:
        self._require_context(context)
        adapters: dict[str, AdapterHealth] = {}
        for name, adapter in ((adapter.name, adapter) for adapter in self.registry.get_all()):
            started = time.perf_counter()
            try:
                healthy = bool(adapter.health_check())
                details: dict[str, Any] = {}
                readiness = getattr(adapter, "readiness", None)
                if self.config.runtime_profile.is_production and name == "gatefield" and callable(readiness):
                    details = dict(readiness())
                    healthy = healthy and bool(details.get("healthy")) and bool(details.get("pgvector_ready"))
            except Exception as exc:
                healthy = False
                details = {"error_type": type(exc).__name__}
            adapters[name] = AdapterHealth(
                name=name,
                healthy=healthy,
                latency_ms=(time.perf_counter() - started) * 1000,
                failure_policy=adapter.get_metadata().failure_policy.value,
                details=details,
            )
        database_healthy = self.database.health_check()
        required_names = {"gatefield", "taskstate", "protocols", "memx", "shipyard", "workflow"}
        all_required_healthy = required_names.issubset(adapters) and all(
            adapters[name].healthy for name in required_names
        )
        production_ready = (
            database_healthy
            and all_required_healthy
            and (
                not self.config.runtime_profile.is_production
                or (context.authenticated and self.config.database.is_postgresql and self.config.oidc.enabled)
            )
        )
        return HealthReport(
            ready=production_ready,
            runtime_profile=self.config.runtime_profile,
            adapters=adapters,
            database_healthy=database_healthy,
            production_ready=production_ready,
        )


def create_gate_service(config: AppConfig, registry: AdapterRegistry) -> GateService:
    database = Database(config.database.url.get_secret_value(), echo=config.database.echo)
    if config.runtime_profile in {RuntimeProfile.LOCAL_ADVISORY, RuntimeProfile.CI_CONTRACT}:
        database.create_schema()
    return GateService(config=config, registry=registry, database=database)


__all__ = ["GateService", "create_gate_service"]
