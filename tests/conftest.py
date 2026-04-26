"""
pytest fixtures for agent-state-gate tests.
"""

from datetime import UTC, datetime

import pytest

from src.core import (
    ApprovalSummary,
    Assessment,
    AssessmentEngine,
    EvidenceSummary,
    ObligationSummary,
    StaleSummary,
    Verdict,
)
from src.queue import HumanAttentionQueue


@pytest.fixture
def assessment_engine():
    """AssessmentEngine fixture."""
    return AssessmentEngine()


@pytest.fixture
def human_queue():
    """HumanAttentionQueue fixture."""
    return HumanAttentionQueue()


@pytest.fixture
def sample_assessment():
    """Sample Assessment fixture."""
    return Assessment(
        assessment_id="01HASM0001",
        decision_packet_ref="agent-gatefield:decision:local:01HDEC0001",
        task_id="agent-taskstate:task:local:01HTSK0001",
        run_id="agent-taskstate:run:local:01HRUN0001",
        stage="dev",
        context_bundle_ref="agent-taskstate:context_bundle:local:01HBND0001",
        stale_summary=StaleSummary(fresh=True),
        obligation_summary=ObligationSummary(fulfillment_rate=1.0),
        approval_summary=ApprovalSummary(missing_approvals=[]),
        evidence_summary=EvidenceSummary(evidence_strength=1.0),
        final_verdict=Verdict.ALLOW,
        verdict_reason="All checks passed",
        threshold_version="sha256:test-version",
        context_hash="sha256:test-context",
    )


@pytest.fixture
def sample_decision_packet():
    """Sample DecisionPacket fixture."""
    return {
        "schema_version": "1.0.0",
        "decision_id": "01HDEC0001",
        "run_id": "01HRUN0001",
        "artifact_id": "01HART0001",
        "decision": "pass",
        "composite_score": 0.92,
        "factors": [
            {
                "name": "taboo_proximity",
                "value": 0.15,
                "weight": 0.30,
                "contribution": 0.046,
                "threshold": 0.80,
                "threshold_type": "warn",
            }
        ],
        "exemplar_refs": [],
        "action": {"action_type": "continue"},
        "threshold_version": "sha256:threshold-v1",
        "policy_version": "v1",
        "static_gate_summary": {
            "gates_executed": ["lint", "sast"],
            "all_passed": True,
        },
        "created_at": datetime.now(UTC).isoformat(),
    }


@pytest.fixture
def sample_stale_result_fresh():
    """Sample fresh stale check result."""
    return {
        "fresh": True,
        "stale_items": [],
        "stale_reasons": [],
    }


@pytest.fixture
def sample_stale_result_stale():
    """Sample stale stale check result."""
    return {
        "fresh": False,
        "stale_items": [
            {
                "item_type": "doc",
                "item_id": "doc-001",
                "current_version": "v2",
                "expected_version": "v1",
                "stale_reason": "version_changed",
            }
        ],
        "stale_reasons": ["doc_version_changed"],
    }
