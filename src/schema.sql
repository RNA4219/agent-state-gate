CREATE TABLE IF NOT EXISTS assessments (
    assessment_id VARCHAR(80) NOT NULL, tenant_id VARCHAR(255) NOT NULL, task_id VARCHAR(512) NOT NULL,
    run_id VARCHAR(512) NOT NULL, stage VARCHAR(128) NOT NULL, final_verdict VARCHAR(64) NOT NULL,
    context_hash VARCHAR(64) NOT NULL, diff_hash VARCHAR(64) NOT NULL, policy_version VARCHAR(255) NOT NULL,
    threshold_version VARCHAR(255) NOT NULL, degraded BOOLEAN NOT NULL, payload JSON NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, PRIMARY KEY(assessment_id, tenant_id)
);
CREATE INDEX IF NOT EXISTS ix_assessments_run ON assessments(tenant_id, run_id);
CREATE INDEX IF NOT EXISTS ix_assessments_task ON assessments(tenant_id, task_id);
CREATE TABLE IF NOT EXISTS human_queue_items (
    item_id VARCHAR(80) NOT NULL, tenant_id VARCHAR(255) NOT NULL, assessment_id VARCHAR(80) NOT NULL,
    task_id VARCHAR(512) NOT NULL, run_id VARCHAR(512) NOT NULL, severity VARCHAR(32) NOT NULL,
    required_role VARCHAR(128) NOT NULL, status VARCHAR(32) NOT NULL, assigned_to VARCHAR(255),
    version INTEGER NOT NULL, payload JSON NOT NULL, created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, PRIMARY KEY(item_id, tenant_id)
);
CREATE INDEX IF NOT EXISTS ix_queue_status ON human_queue_items(tenant_id,status,required_role);
CREATE TABLE IF NOT EXISTS audit_packets (
    packet_id VARCHAR(80) NOT NULL, tenant_id VARCHAR(255) NOT NULL, run_id VARCHAR(512) NOT NULL,
    assessment_id VARCHAR(80) NOT NULL, retention_class VARCHAR(32) NOT NULL, payload JSON NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, PRIMARY KEY(packet_id, tenant_id)
);
CREATE INDEX IF NOT EXISTS ix_audit_run ON audit_packets(tenant_id,run_id);
CREATE TABLE IF NOT EXISTS attested_snapshots (
    snapshot_id VARCHAR(80) NOT NULL, tenant_id VARCHAR(255) NOT NULL, run_id VARCHAR(512) NOT NULL,
    assessment_id VARCHAR(80) NOT NULL, attestation_hash VARCHAR(64) NOT NULL, payload JSON NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, PRIMARY KEY(snapshot_id, tenant_id)
);
CREATE INDEX IF NOT EXISTS ix_snapshots_run ON attested_snapshots(tenant_id,run_id);
CREATE TABLE IF NOT EXISTS purge_manifests (
    manifest_id VARCHAR(80) NOT NULL, tenant_id VARCHAR(255) NOT NULL, executed_by VARCHAR(255) NOT NULL,
    cutoff_by_class JSON NOT NULL, deleted_by_class JSON NOT NULL, rationale TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, PRIMARY KEY(manifest_id, tenant_id)
);
CREATE TABLE IF NOT EXISTS approval_bindings (
    approval_id VARCHAR(80) NOT NULL, tenant_id VARCHAR(255) NOT NULL, diff_hash VARCHAR(64) NOT NULL,
    context_hash VARCHAR(64) NOT NULL, policy_version VARCHAR(255) NOT NULL, approved_roles JSON NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE, created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY(approval_id, tenant_id)
);
