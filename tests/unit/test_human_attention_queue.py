"""
Tests for human_attention_queue module.

Tests queue operations, SLA enforcement, and escalation.
Reference: AC-004_human_queue_routing.json, AC-005_sla_enforcement.json
"""

from datetime import UTC, datetime, timedelta

from src.core import ApprovalSummary, Assessment, EvidenceSummary, ObligationSummary, StaleSummary, Verdict
from src.queue.human_attention import (
    HumanAttentionQueue,
    OwnershipContext,
    QueueStatus,
    ReasonCode,
    Resolution,
    Severity,
    SLADefinition,
    route_assessment_to_queue,
)


class TestSLADefinition:
    """Tests for SLADefinition."""

    def test_get_ack_deadline_with_minutes(self):
        """Get ack deadline with minutes."""
        sla = SLADefinition(ack_minutes=15)
        created_at = datetime.now(UTC)
        deadline = sla.get_ack_deadline(created_at)

        assert deadline == created_at + timedelta(minutes=15)

    def test_get_decision_deadline_with_hours(self):
        """Get decision deadline with hours."""
        sla = SLADefinition(decision_hours=24)
        created_at = datetime.now(UTC)
        deadline = sla.get_decision_deadline(created_at)

        assert deadline == created_at + timedelta(hours=24)

    def test_backlog_sla_no_deadline(self):
        """Backlog SLA has no deadline."""
        sla = SLADefinition(backlog=True)
        created_at = datetime.now(UTC)

        assert sla.get_ack_deadline(created_at) is None
        assert sla.get_decision_deadline(created_at) is None


class TestHumanAttentionQueue:
    """Tests for HumanAttentionQueue."""

    def test_add_item(self):
        """Add item to queue."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=["project_lead"]),
            evidence_summary=EvidenceSummary(evidence_strength=0.7),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="Missing approvals",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.APPROVAL_MISSING,
            severity=Severity.MEDIUM,
            required_role="project_lead",
            task_owner="owner-001",
        )

        assert item.status == QueueStatus.PENDING
        assert item.reason_code == ReasonCode.APPROVAL_MISSING

    def test_take_item(self):
        """Take item by reviewer."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.REQUIRE_HUMAN,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.HIGH_RISK,
            severity=Severity.HIGH,
            required_role="security_reviewer",
            task_owner="owner-001",
        )

        taken = queue.take_item(item.item_id, "reviewer-001")

        assert taken is not None
        assert taken.status == QueueStatus.TAKEN
        assert taken.assigned_to == "reviewer-001"

    def test_resolve_item(self):
        """Resolve queue item."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.APPROVAL_MISSING,
            severity=Severity.MEDIUM,
            required_role="project_lead",
            task_owner="owner-001",
        )

        queue.take_item(item.item_id, "reviewer-001")
        resolved = queue.resolve_item(item.item_id, Resolution.APPROVED, "Risk acceptable")

        assert resolved is not None
        assert resolved.status == QueueStatus.RESOLVED
        assert resolved.resolution == Resolution.APPROVED

    def test_escalate_item(self):
        """Escalate item to next level."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.REQUIRE_HUMAN,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.TABOO,
            severity=Severity.HIGH,
            required_role="security_reviewer",
            task_owner="owner-001",
        )

        escalated = queue.escalate_item(item.item_id, "No response")

        assert escalated is not None
        assert escalated.status == QueueStatus.ESCALATED
        assert escalated.escalation_level == 1


class TestSLAEnforcement:
    """Tests for SLA enforcement."""

    def test_enforce_sla_ack_timeout(self):
        """SLA enforcement detects ack timeout."""
        queue = HumanAttentionQueue()

        # Create critical item with short SLA
        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.DENY,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.HIGH_RISK,
            severity=Severity.CRITICAL,
            required_role="governance_board",
            task_owner="owner-001",
        )

        # Simulate time passing (ack timeout for critical is 15 min)
        now = item.created_at + timedelta(minutes=20)
        updated = queue.enforce_sla(now)

        # Should escalate due to ack timeout
        assert len(updated) > 0
        assert updated[0].status == QueueStatus.ESCALATED

    def test_enforce_sla_auto_block_critical(self):
        """SLA enforcement auto-blocks critical timeout."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.DENY,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.HIGH_RISK,
            severity=Severity.CRITICAL,
            required_role="governance_board",
            task_owner="owner-001",
        )

        # Take item
        queue.take_item(item.item_id, "reviewer-001")

        # Simulate decision timeout (60 min for critical)
        now = item.created_at + timedelta(minutes=70)
        updated = queue.enforce_sla(now)

        # Should auto-block
        assert len(updated) > 0
        assert updated[0].resolution == Resolution.REJECTED


class TestQueueRouting:
    """Tests for queue routing."""

    def test_route_by_severity(self):
        """Route based on severity."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.REQUIRE_HUMAN,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.TABOO,
            severity=Severity.CRITICAL,
            required_role="security_reviewer",
            task_owner="owner-001",
        )

        reviewer = queue.route_to_reviewer(item)

        # Critical items route to governance_board
        assert reviewer == "governance_board"

    def test_route_high_severity(self):
        """Route high severity items."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.REQUIRE_HUMAN,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.HIGH_RISK,
            severity=Severity.HIGH,
            required_role="domain_reviewer",
            task_owner="owner-001",
        )

        reviewer = queue.route_to_reviewer(item)
        # HIGH severity with HIGH_RISK reason returns project_lead via architecture reviewer
        assert reviewer in ["project_lead", "domain_reviewer"]

    def test_route_high_severity_taboo(self):
        """Route high severity taboo items."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.REQUIRE_HUMAN,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.TABOO,
            severity=Severity.HIGH,
            required_role="security_reviewer",
            task_owner="owner-001",
        )

        reviewer = queue.route_to_reviewer(item)
        # HIGH severity with TABOO reason returns security_reviewer
        assert reviewer in ["security_reviewer", "project_lead"]

    def test_route_medium_severity(self):
        """Route medium severity items - returns required_role when owner matches."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="test",
        )

        # Create ownership context where owner_role matches required_role
        ownership_ctx = OwnershipContext(
            owner_id="owner-001",
            owner_role="peer_reviewer",
            permission_scope=["read"],
            approval_authority_level=1
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.APPROVAL_MISSING,
            severity=Severity.MEDIUM,
            required_role="peer_reviewer",
            task_owner="owner-001",
            ownership_context=ownership_ctx,
        )

        reviewer = queue.route_to_reviewer(item)
        # MEDIUM severity returns the item's required_role when no cross-owner review needed
        assert reviewer == "peer_reviewer"

    def test_get_pending_items(self):
        """Get pending items."""
        queue = HumanAttentionQueue()

        for i in range(3):
            assessment = Assessment(
                assessment_id=f"01HASM{i:04d}",
                decision_packet_ref="",
                task_id="task-001",
                run_id=f"run-{i}",
                stage="dev",
                context_bundle_ref="",
                stale_summary=StaleSummary(fresh=True),
                obligation_summary=ObligationSummary(fulfillment_rate=1.0),
                approval_summary=ApprovalSummary(missing_approvals=[]),
                evidence_summary=EvidenceSummary(evidence_strength=1.0),
                final_verdict=Verdict.NEEDS_APPROVAL,
                verdict_reason="test",
            )
            queue.add_item(
                assessment=assessment,
                reason_code=ReasonCode.APPROVAL_MISSING,
                severity=Severity.MEDIUM,
                required_role="project_lead",
                task_owner="owner-001",
            )

        pending = queue.get_pending_items()
        assert len(pending) == 3


class TestSLAEnforcementHigh:
    """Tests for SLA enforcement with high severity."""

    def test_enforce_sla_high_timeout(self):
        """SLA enforcement for high severity timeout."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.REQUIRE_HUMAN,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.HIGH_RISK,
            severity=Severity.HIGH,
            required_role="domain_reviewer",
            task_owner="owner-001",
        )

        # Take the item
        queue.take_item(item.item_id, "reviewer-001")

        # Simulate decision timeout for high (4 hours)
        now = item.created_at + timedelta(hours=5)
        updated = queue.enforce_sla(now)

        assert len(updated) > 0


class TestSLAChainExceeded:
    """Tests for escalation chain exceeded."""

    def test_escalation_chain_exceeded(self):
        """Escalation chain exceeded triggers governance board."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.DENY,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.TABOO,
            severity=Severity.CRITICAL,
            required_role="governance_board",
            task_owner="owner-001",
        )

        # Escalate multiple times
        queue.escalate_item(item.item_id, "first escalation")
        queue.escalate_item(item.item_id, "second escalation")
        queue.escalate_item(item.item_id, "third escalation")

        # Check escalation level
        updated = queue.get_item(item.item_id)
        assert updated.escalation_level >= 3


class TestQueueWaiver:
    """Tests for waiver handling."""

    def test_add_waiver_to_item(self):
        """Add waiver to queue item."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.APPROVAL_MISSING,
            severity=Severity.LOW,
            required_role="peer_reviewer",
            task_owner="owner-001",
        )

        # Waiver fields can be set directly on the item
        item.waiver_id = "WAIVER-001"
        item.waiver_status = "approved"
        assert item.waiver_id == "WAIVER-001"
        assert item.waiver_status == "approved"


class TestQueueRejectResolution:
    """Tests for rejection resolution."""

    def test_resolve_item_rejected(self):
        """Resolve item with rejection."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.APPROVAL_MISSING,
            severity=Severity.MEDIUM,
            required_role="project_lead",
            task_owner="owner-001",
        )

        queue.take_item(item.item_id, "reviewer-001")
        resolved = queue.resolve_item(item.item_id, Resolution.REJECTED, "Risk too high")

        assert resolved is not None
        assert resolved.status == QueueStatus.RESOLVED
        assert resolved.resolution == Resolution.REJECTED


class TestQueueRevokedResolution:
    """Tests for revoked resolution."""

    def test_resolve_item_revoked(self):
        """Resolve item with revocation."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.APPROVAL_MISSING,
            severity=Severity.MEDIUM,
            required_role="project_lead",
            task_owner="owner-001",
        )

        queue.take_item(item.item_id, "reviewer-001")
        resolved = queue.resolve_item(item.item_id, Resolution.REVOKED, "Approval withdrawn")

        assert resolved is not None
        assert resolved.resolution == Resolution.REVOKED


class TestRouteAssessmentToQueue:
    """Tests for route_assessment_to_queue function."""

    def test_allow_verdict_not_routed(self):
        """ALLOW verdict not routed to queue."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.ALLOW,
            verdict_reason="All passed",
        )

        from src.queue.human_attention import route_assessment_to_queue
        result = route_assessment_to_queue(assessment, queue, "owner-001")
        assert result is None

    def test_deny_verdict_routed(self):
        """DENY verdict routed to queue."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0002",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.DENY,
            verdict_reason="Critical violation",
        )

        from src.queue.human_attention import route_assessment_to_queue
        result = route_assessment_to_queue(assessment, queue, "owner-001")
        assert result is not None
        assert result.severity == Severity.CRITICAL

    def test_stale_blocked_verdict_routed(self):
        """STALE_BLOCKED verdict routed to queue."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0003",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.STALE_BLOCKED,
            verdict_reason="Stale docs detected",
        )

        from src.queue.human_attention import route_assessment_to_queue
        result = route_assessment_to_queue(assessment, queue, "owner-001")
        assert result is not None
        assert result.severity == Severity.HIGH

    def test_require_human_with_taboo_routed(self):
        """REQUIRE_human with taboo routed to security."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0004",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.REQUIRE_HUMAN,
            verdict_reason="Taboo proximity threshold exceeded",
        )

        from src.queue.human_attention import route_assessment_to_queue
        result = route_assessment_to_queue(assessment, queue, "owner-001")
        assert result is not None
        assert result.reason_code == ReasonCode.TABOO

    def test_require_human_with_uncertainty_routed(self):
        """REQUIRE_human with uncertainty routed."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0005",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.REQUIRE_HUMAN,
            verdict_reason="High uncertainty in decision",
        )

        from src.queue.human_attention import route_assessment_to_queue
        result = route_assessment_to_queue(assessment, queue, "owner-001")
        assert result is not None
        assert result.reason_code == ReasonCode.UNCERTAINTY_HIGH

    def test_require_human_with_obligation_routed(self):
        """REQUIRE_human with obligation routed."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0006",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.REQUIRE_HUMAN,
            verdict_reason="Obligation unfulfilled",
        )

        from src.queue.human_attention import route_assessment_to_queue
        result = route_assessment_to_queue(assessment, queue, "owner-001")
        assert result is not None
        assert result.reason_code == ReasonCode.OBLIGATION_UNFULFILLED

    def test_needs_approval_with_missing_approvals_routed(self):
        """NEEDS_APPROVAL with missing approvals routed."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0007",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=["security_reviewer"]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="Missing approvals",
        )

        from src.queue.human_attention import route_assessment_to_queue
        result = route_assessment_to_queue(assessment, queue, "owner-001")
        assert result is not None
        assert result.reason_code == ReasonCode.APPROVAL_MISSING

    def test_needs_approval_with_evidence_gap_routed(self):
        """NEEDS_APPROVAL with evidence gap routed."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0008",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=0.5),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="Evidence gap",
        )

        from src.queue.human_attention import route_assessment_to_queue
        result = route_assessment_to_queue(assessment, queue, "owner-001")
        assert result is not None
        assert result.reason_code == ReasonCode.EVIDENCE_GAP

    def test_revise_verdict_routed(self):
        """REVISE verdict routed to owner."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0009",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.REVISE,
            verdict_reason="Self-correction needed",
        )

        from src.queue.human_attention import route_assessment_to_queue
        result = route_assessment_to_queue(assessment, queue, "owner-001")
        assert result is not None
        assert result.severity == Severity.LOW


class TestQueueAdditionalMethods:
    """Tests for additional queue methods."""

    def test_get_item_not_found(self):
        """Get item returns None for unknown ID."""
        queue = HumanAttentionQueue()
        result = queue.get_item("UNKNOWN-ID")
        assert result is None

    def test_take_item_not_found(self):
        """Take item returns None for unknown ID."""
        queue = HumanAttentionQueue()
        result = queue.take_item("UNKNOWN-ID", "reviewer-001")
        assert result is None

    def test_take_item_already_taken(self):
        """Take item returns None if already taken."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.APPROVAL_MISSING,
            severity=Severity.MEDIUM,
            required_role="project_lead",
            task_owner="owner-001",
        )

        queue.take_item(item.item_id, "reviewer-001")
        # Second take should fail
        result = queue.take_item(item.item_id, "reviewer-002")
        assert result is None

    def test_take_item_resolved(self):
        """Take item returns None if already resolved."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.APPROVAL_MISSING,
            severity=Severity.MEDIUM,
            required_role="project_lead",
            task_owner="owner-001",
        )

        queue.take_item(item.item_id, "reviewer-001")
        queue.resolve_item(item.item_id, Resolution.APPROVED)
        # Take on resolved item should fail
        result = queue.take_item(item.item_id, "reviewer-002")
        assert result is None

    def test_resolve_item_not_found(self):
        """Resolve item returns None for unknown ID."""
        queue = HumanAttentionQueue()
        result = queue.resolve_item("UNKNOWN-ID", Resolution.APPROVED)
        assert result is None

    def test_resolve_item_not_taken(self):
        """Resolve item returns None if not taken."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="test",
        )

        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.APPROVAL_MISSING,
            severity=Severity.MEDIUM,
            required_role="project_lead",
            task_owner="owner-001",
        )

        # Resolve without taking should fail
        result = queue.resolve_item(item.item_id, Resolution.APPROVED)
        assert result is None

    def test_escalate_item_not_found(self):
        """Escalate item returns None for unknown ID."""
        queue = HumanAttentionQueue()
        result = queue.escalate_item("UNKNOWN-ID", "test reason")
        assert result is None

    def test_get_items_by_task(self):
        """Get items by task ID."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="test",
        )

        queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.APPROVAL_MISSING,
            severity=Severity.MEDIUM,
            required_role="project_lead",
            task_owner="owner-001",
        )

        items = queue.get_items_by_task("task-001")
        assert len(items) == 1

        items_empty = queue.get_items_by_task("task-002")
        assert len(items_empty) == 0


class TestQueueListMethods:
    """Tests for list methods."""

    def test_get_items_by_reviewer(self):
        """Get items by reviewer role."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="test",
        )
        queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.APPROVAL_MISSING,
            severity=Severity.MEDIUM,
            required_role="project_lead",
            task_owner="owner-001",
        )

        items = queue.get_items_by_reviewer("project_lead")
        assert len(items) == 1

    def test_get_items_by_task(self):
        """Get items by task."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="test",
        )
        queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.APPROVAL_MISSING,
            severity=Severity.MEDIUM,
            required_role="project_lead",
            task_owner="owner-001",
        )

        items = queue.get_items_by_task("task-001")
        assert len(items) == 1

    def test_get_item(self):
        """Get item by ID."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="test",
        )
        item = queue.add_item(
            assessment=assessment,
            reason_code=ReasonCode.APPROVAL_MISSING,
            severity=Severity.MEDIUM,
            required_role="project_lead",
            task_owner="owner-001",
        )

        retrieved = queue.get_item(item.item_id)
        assert retrieved is not None
        assert retrieved.item_id == item.item_id

    def test_allow_not_routed(self):
        """ALLOW verdict not routed."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.ALLOW,
            verdict_reason="All passed",
        )

        item = route_assessment_to_queue(assessment, queue, "owner-001")

        assert item is None

    def test_needs_approval_routed(self):
        """NEEDS_APPROVAL verdict routed to queue."""
        queue = HumanAttentionQueue()

        assessment = Assessment(
            assessment_id="01HASM0001",
            decision_packet_ref="",
            task_id="task-001",
            run_id="run-001",
            stage="dev",
            context_bundle_ref="",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=["project_lead"]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            final_verdict=Verdict.NEEDS_APPROVAL,
            verdict_reason="Missing approvals",
        )

        item = route_assessment_to_queue(assessment, queue, "owner-001")

        assert item is not None
        assert item.reason_code == ReasonCode.APPROVAL_MISSING


class TestOwnershipContext:
    """Tests for OwnershipContext."""

    def test_ownership_context_creation(self):
        """Create ownership context."""
        ctx = OwnershipContext(
            owner_id="owner-001",
            owner_role="developer",
            permission_scope=["read", "write"],
            data_classification_access=["internal"],
            service_scope=["service-a"],
            approval_authority_level=2,
        )

        assert ctx.owner_id == "owner-001"
        assert ctx.approval_authority_level == 2
