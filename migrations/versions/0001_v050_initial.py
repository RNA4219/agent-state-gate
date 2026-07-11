"""initial tenant-scoped production schema

Revision ID: 0001_v050
Revises:
Create Date: 2026-07-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_v050"
down_revision = None
branch_labels = None
depends_on = None


def _tenant_table(name: str, *columns: sa.Column) -> None:
    op.create_table(
        name,
        *columns,
        sa.Column("tenant_id", sa.String(length=255), primary_key=True),
    )


def upgrade() -> None:
    _tenant_table(
        "assessments",
        sa.Column("assessment_id", sa.String(length=80), primary_key=True),
        sa.Column("task_id", sa.String(length=512), nullable=False),
        sa.Column("run_id", sa.String(length=512), nullable=False),
        sa.Column("stage", sa.String(length=128), nullable=False),
        sa.Column("final_verdict", sa.String(length=64), nullable=False),
        sa.Column("context_hash", sa.String(length=64), nullable=False),
        sa.Column("diff_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=255), nullable=False),
        sa.Column("threshold_version", sa.String(length=255), nullable=False),
        sa.Column("degraded", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assessments_run", "assessments", ["tenant_id", "run_id"])
    op.create_index("ix_assessments_task", "assessments", ["tenant_id", "task_id"])

    _tenant_table(
        "human_queue_items",
        sa.Column("item_id", sa.String(length=80), primary_key=True),
        sa.Column("assessment_id", sa.String(length=80), nullable=False),
        sa.Column("task_id", sa.String(length=512), nullable=False),
        sa.Column("run_id", sa.String(length=512), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("required_role", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("assigned_to", sa.String(length=255)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_queue_status", "human_queue_items", ["tenant_id", "status", "required_role"])

    _tenant_table(
        "audit_packets",
        sa.Column("packet_id", sa.String(length=80), primary_key=True),
        sa.Column("run_id", sa.String(length=512), nullable=False),
        sa.Column("assessment_id", sa.String(length=80), nullable=False),
        sa.Column("retention_class", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_run", "audit_packets", ["tenant_id", "run_id"])

    _tenant_table(
        "attested_snapshots",
        sa.Column("snapshot_id", sa.String(length=80), primary_key=True),
        sa.Column("run_id", sa.String(length=512), nullable=False),
        sa.Column("assessment_id", sa.String(length=80), nullable=False),
        sa.Column("attestation_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_snapshots_run", "attested_snapshots", ["tenant_id", "run_id"])

    _tenant_table(
        "purge_manifests",
        sa.Column("manifest_id", sa.String(length=80), primary_key=True),
        sa.Column("executed_by", sa.String(length=255), nullable=False),

        sa.Column("cutoff_by_class", sa.JSON(), nullable=False),
        sa.Column("deleted_by_class", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


    _tenant_table(
        "approval_bindings",
        sa.Column("approval_id", sa.String(length=80), primary_key=True),
        sa.Column("diff_hash", sa.String(length=64), nullable=False),
        sa.Column("context_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=255), nullable=False),
        sa.Column("approved_roles", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

def downgrade() -> None:

    op.drop_table("purge_manifests")
    op.drop_table("approval_bindings")
    op.drop_index("ix_snapshots_run", table_name="attested_snapshots")
    op.drop_table("attested_snapshots")
    op.drop_index("ix_audit_run", table_name="audit_packets")
    op.drop_table("audit_packets")
    op.drop_index("ix_queue_status", table_name="human_queue_items")
    op.drop_table("human_queue_items")
    op.drop_index("ix_assessments_task", table_name="assessments")
    op.drop_index("ix_assessments_run", table_name="assessments")
    op.drop_table("assessments")
