"""PostgreSQL/pgvector runtime acceptance executed by CI."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from agent_state_gate.models import AssessmentModel
from agent_state_gate.persistence import Database


def _database_url() -> str:
    url = os.getenv("AGENT_STATE_GATE_DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL runtime test requires AGENT_STATE_GATE_DATABASE_URL")
    return url


def test_postgresql_migration_pgvector_tenant_and_atomic_queue() -> None:
    database = Database(_database_url())
    tenant_id = f"ci-{uuid.uuid4().hex}"
    other_tenant = f"ci-{uuid.uuid4().hex}"
    assessment_id = f"ASM-{uuid.uuid4().hex}"

    with database.engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        assert connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001_v050"

    assessment = AssessmentModel(
        assessment_id=assessment_id,
        tenant_id=tenant_id,
        task_id="TASK-CI",
        run_id="RUN-CI",
        stage="verify",
        decision_packet_ref="agent-gatefield:decision:local:DEC-CI",
        final_verdict="require_human",
        verdict_reason="CI PostgreSQL runtime contract",
        context_hash="1" * 64,
        diff_hash="2" * 64,
        policy_version="0.5.0",
        threshold_version="ci",
    )
    database.save_assessment(assessment)
    assert database.get_assessment(tenant_id, assessment_id) == assessment
    assert database.get_assessment(other_tenant, assessment_id) is None

    item_id = database.enqueue_attention(
        tenant_id=tenant_id,
        payload={
            "assessment_id": assessment_id,
            "task_id": "TASK-CI",
            "run_id": "RUN-CI",
            "severity": "high",
            "required_role": "domain_reviewer",
        },
    )

    def take(index: int) -> dict[str, object] | None:
        return database.take_attention(tenant_id, item_id, f"reviewer-{index}")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(take, range(8)))
    assert sum(result is not None for result in results) == 1
    assert database.take_attention(other_tenant, item_id, "intruder") is None
    database.engine.dispose()
