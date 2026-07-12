"""Tenant-scoped SQLAlchemy persistence for agent-state-gate."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, create_engine, delete, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .models import ApprovalBinding, AssessmentModel
from .typed_ref import parse_ref


class Base(DeclarativeBase):
    pass


class AssessmentRow(Base):
    __tablename__ = "assessments"

    assessment_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(512), index=True)
    run_id: Mapped[str] = mapped_column(String(512), index=True)
    stage: Mapped[str] = mapped_column(String(128))
    final_verdict: Mapped[str] = mapped_column(String(64), index=True)
    context_hash: Mapped[str] = mapped_column(String(64))
    diff_hash: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(255))
    threshold_version: Mapped[str] = mapped_column(String(255))
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class QueueItemRow(Base):
    __tablename__ = "human_queue_items"

    item_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(80), index=True)
    task_id: Mapped[str] = mapped_column(String(512), index=True)
    run_id: Mapped[str] = mapped_column(String(512), index=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    required_role: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuditPacketRow(Base):
    __tablename__ = "audit_packets"

    packet_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(512), index=True)
    assessment_id: Mapped[str] = mapped_column(String(80), index=True)
    retention_class: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SnapshotRow(Base):
    __tablename__ = "attested_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(512), index=True)
    assessment_id: Mapped[str] = mapped_column(String(80), index=True)
    attestation_hash: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PurgeManifestRow(Base):
    __tablename__ = "purge_manifests"

    manifest_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    executed_by: Mapped[str] = mapped_column(String(255))
    cutoff_by_class: Mapped[dict[str, str]] = mapped_column(JSON)
    deleted_by_class: Mapped[dict[str, int]] = mapped_column(JSON)
    rationale: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ApprovalBindingRow(Base):
    __tablename__ = "approval_bindings"

    approval_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    diff_hash: Mapped[str] = mapped_column(String(64), index=True)
    context_hash: Mapped[str] = mapped_column(String(64), index=True)
    policy_version: Mapped[str] = mapped_column(String(255), index=True)
    approved_roles: Mapped[list[str]] = mapped_column(JSON)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Database:
    """Owns the engine and tenant-scoped persistence operations."""

    RETENTION_DAYS = {"audit": 365, "ops": 90, "pii-sensitive": 30}

    def __init__(self, url: str, *, echo: bool = False):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(url, echo=echo, future=True, pool_pre_ping=True, connect_args=connect_args)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def health_check(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def save_assessment(self, assessment: AssessmentModel) -> None:
        payload = assessment.model_dump(mode="json")
        row = AssessmentRow(
            assessment_id=assessment.assessment_id,
            tenant_id=assessment.tenant_id,
            task_id=assessment.task_id,
            run_id=assessment.run_id,
            stage=assessment.stage,
            final_verdict=assessment.final_verdict,
            context_hash=assessment.context_hash,
            diff_hash=assessment.diff_hash,
            policy_version=assessment.policy_version,
            threshold_version=assessment.threshold_version,
            degraded=assessment.degraded,
            payload=payload,
            created_at=assessment.created_at,
        )
        with self.sessions.begin() as session:
            session.merge(row)

    def get_assessment(self, tenant_id: str, assessment_id: str) -> AssessmentModel | None:
        if ":" in assessment_id:
            try:
                parsed = parse_ref(assessment_id)
            except ValueError:
                return None
            if parsed.domain != "agent-state-gate" or parsed.entity_type != "assessment":
                return None
            assessment_id = parsed.entity_id
        with self.sessions() as session:
            row = session.get(AssessmentRow, (assessment_id, tenant_id))
            if row is None:
                return None
            return AssessmentModel.model_validate(row.payload, strict=False)
    def save_approval_binding(self, binding: ApprovalBinding) -> None:
        row = ApprovalBindingRow(
            approval_id=binding.approval_id,
            tenant_id=binding.tenant_id,
            diff_hash=binding.diff_hash,
            context_hash=binding.context_hash,
            policy_version=binding.policy_version,
            approved_roles=sorted(binding.approved_roles),
            expires_at=binding.expires_at,
            created_at=datetime.now(UTC),
        )
        with self.sessions.begin() as session:
            session.merge(row)

    def get_approval_binding(self, tenant_id: str, approval_id: str) -> ApprovalBinding | None:
        with self.sessions() as session:
            row = session.get(ApprovalBindingRow, (approval_id, tenant_id))
            if row is None:
                return None
            return ApprovalBinding(
                approval_id=row.approval_id,
                tenant_id=row.tenant_id,
                diff_hash=row.diff_hash,
                context_hash=row.context_hash,
                policy_version=row.policy_version,
                approved_roles=frozenset(row.approved_roles),
                expires_at=row.expires_at,
            )

    def approval_is_current(
        self,
        tenant_id: str,
        approval_id: str,
        *,
        diff_hash: str,
        context_hash: str,
        policy_version: str,
        now: datetime | None = None,
    ) -> bool:
        binding = self.get_approval_binding(tenant_id, approval_id)
        if binding is None:
            return False
        return binding.is_current(
            tenant_id=tenant_id,
            diff_hash=diff_hash,
            context_hash=context_hash,
            policy_version=policy_version,
            now=now,
        )

    def list_assessments_by_run(self, tenant_id: str, run_id: str) -> list[AssessmentModel]:
        statement = (
            select(AssessmentRow)
            .where(AssessmentRow.tenant_id == tenant_id, AssessmentRow.run_id == run_id)
            .order_by(AssessmentRow.created_at)
        )
        with self.sessions() as session:
            return [AssessmentModel.model_validate(row.payload, strict=False) for row in session.scalars(statement)]

    def save_snapshot(
        self,
        *,
        tenant_id: str,
        run_id: str,
        assessment_id: str,
        attestation_hash: str,
        payload: dict[str, Any],
    ) -> str:
        snapshot_id = f"SNP-{uuid.uuid4().hex}"
        row = SnapshotRow(
            snapshot_id=snapshot_id,
            tenant_id=tenant_id,
            run_id=run_id,
            assessment_id=assessment_id,
            attestation_hash=attestation_hash,
            payload=payload,
            created_at=datetime.now(UTC),
        )
        with self.sessions.begin() as session:
            session.add(row)
        return snapshot_id

    def latest_snapshot(self, tenant_id: str, run_id: str) -> SnapshotRow | None:
        statement = (
            select(SnapshotRow)
            .where(SnapshotRow.tenant_id == tenant_id, SnapshotRow.run_id == run_id)
            .order_by(SnapshotRow.created_at.desc())
            .limit(1)
        )
        with self.sessions() as session:
            return session.scalar(statement)

    def append_audit_packet(
        self,
        *,
        packet_id: str,
        tenant_id: str,
        run_id: str,
        assessment_id: str,
        retention_class: str,
        payload: dict[str, Any],
    ) -> None:
        with self.sessions.begin() as session:
            session.add(
                AuditPacketRow(
                    packet_id=packet_id,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    assessment_id=assessment_id,
                    retention_class=retention_class,
                    payload=payload,
                    created_at=datetime.now(UTC),
                )
            )

    def enqueue_attention(self, *, tenant_id: str, payload: dict[str, Any]) -> str:
        item_id = str(payload.get("item_id") or f"QI-{uuid.uuid4().hex}")
        now = datetime.now(UTC)
        row = QueueItemRow(
            item_id=item_id,
            tenant_id=tenant_id,
            assessment_id=str(payload["assessment_id"]),
            task_id=str(payload["task_id"]),
            run_id=str(payload["run_id"]),
            severity=str(payload["severity"]),
            required_role=str(payload["required_role"]),
            status=str(payload.get("status", "pending")),
            payload={**payload, "item_id": item_id},
            created_at=now,
            updated_at=now,
        )
        with self.sessions.begin() as session:
            session.add(row)
        return item_id

    def list_attention(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        reviewer_role: str | None = None,
    ) -> list[dict[str, Any]]:
        statement = select(QueueItemRow).where(QueueItemRow.tenant_id == tenant_id)
        if status:
            statement = statement.where(QueueItemRow.status == status)
        if reviewer_role:
            statement = statement.where(QueueItemRow.required_role == reviewer_role)
        statement = statement.order_by(QueueItemRow.created_at)
        with self.sessions() as session:
            return [dict(row.payload) for row in session.scalars(statement)]

    def take_attention(self, tenant_id: str, item_id: str, reviewer: str) -> dict[str, Any] | None:
        with self.sessions.begin() as session:
            statement = (
                select(QueueItemRow)
                .where(QueueItemRow.tenant_id == tenant_id, QueueItemRow.item_id == item_id)
                .with_for_update()
            )
            row = session.scalar(statement)
            if row is None or row.status not in {"pending", "escalated"}:
                return None
            row.status = "taken"
            row.assigned_to = reviewer
            row.version += 1
            row.updated_at = datetime.now(UTC)
            row.payload = {
                **row.payload,
                "status": row.status,
                "assigned_to": reviewer,
                "version": row.version,
                "taken_at": row.updated_at.isoformat(),
            }
            return dict(row.payload)

    def resolve_attention(
        self,
        tenant_id: str,
        item_id: str,
        *,
        reviewer: str,
        resolution: str,
        comment: str = "",
    ) -> dict[str, Any] | None:
        with self.sessions.begin() as session:
            statement = (
                select(QueueItemRow)
                .where(QueueItemRow.tenant_id == tenant_id, QueueItemRow.item_id == item_id)
                .with_for_update()
            )
            row = session.scalar(statement)
            if row is None or row.status != "taken" or row.assigned_to != reviewer:
                return None
            row.status = "resolved"
            row.version += 1
            row.updated_at = datetime.now(UTC)
            row.payload = {
                **row.payload,
                "status": "resolved",
                "resolution": resolution,
                "resolution_comment": comment,
                "version": row.version,
                "resolved_at": row.updated_at.isoformat(),
            }
            return dict(row.payload)

    def list_audit_packets(self, tenant_id: str, run_id: str | None = None) -> list[dict[str, Any]]:
        statement = select(AuditPacketRow).where(AuditPacketRow.tenant_id == tenant_id)
        if run_id:
            statement = statement.where(AuditPacketRow.run_id == run_id)
        statement = statement.order_by(AuditPacketRow.created_at)
        with self.sessions() as session:
            return [dict(row.payload) for row in session.scalars(statement)]
    def purge_expired(
        self,
        tenant_id: str,
        *,
        executed_by: str,
        now: datetime | None = None,
        rationale: str = "scheduled retention purge",
    ) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        cutoffs = {name: now - timedelta(days=days) for name, days in self.RETENTION_DAYS.items()}
        deleted: dict[str, int] = {}
        with self.sessions.begin() as session:
            for retention_class, cutoff in cutoffs.items():
                result = session.execute(
                    delete(AuditPacketRow).where(
                        AuditPacketRow.tenant_id == tenant_id,
                        AuditPacketRow.retention_class == retention_class,
                        AuditPacketRow.created_at < cutoff,
                    )
                )
                deleted[retention_class] = int(getattr(result, "rowcount", 0) or 0)
            manifest_id = f"PURGE-{uuid.uuid4().hex}"
            session.add(
                PurgeManifestRow(
                    manifest_id=manifest_id,
                    tenant_id=tenant_id,
                    executed_by=executed_by,
                    cutoff_by_class={name: value.isoformat() for name, value in cutoffs.items()},
                    deleted_by_class=deleted,
                    rationale=rationale,
                    created_at=now,
                )
            )
        return {"manifest_id": manifest_id, "deleted_by_class": deleted}


__all__ = [
    "AssessmentRow",
    "AuditPacketRow",
    "Base",
    "Database",
    "PurgeManifestRow",
    "QueueItemRow",
    "SnapshotRow",
]
