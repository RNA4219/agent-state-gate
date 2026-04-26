"""
Unit tests for AuditPacket.

Tests audit packet generation, export, and storage.
"""

from unittest.mock import MagicMock

from src.audit.audit_packet import (
    AuditPacket,
    AuditPacketGenerator,
    AuditPacketStore,
    RetentionClass,
    create_audit_packet,
)
from src.common import utc_now
from src.core.verdict_transformer import Verdict


class TestRetentionClass:
    def test_retention_class_values(self):
        assert RetentionClass.AUDIT.value == "audit"
        assert RetentionClass.OPS.value == "ops"
        assert RetentionClass.PII_SENSITIVE.value == "pii-sensitive"


class TestAuditPacket:
    def test_audit_packet_creation(self):
        packet = AuditPacket(
            packet_id="AUD-001",
            trace_id="trace123",
            span_id="span456",
            assessment_id="ASM-001",
            run_id="RUN-001",
            decision_packet_ref="DEC-001",
            decision_packet_hash="hash123",
            final_verdict="allow",
            verdict_reason="All checks passed",
            context_hash="ctxhash",
            diff_hash="diffhash",
            threshold_version="v1"
        )
        assert packet.packet_id == "AUD-001"
        assert packet.trace_id == "trace123"
        assert packet.final_verdict == "allow"

    def test_audit_packet_with_defaults(self):
        packet = AuditPacket(
            packet_id="AUD-001",
            trace_id="trace123",
            span_id="span456",
            assessment_id="ASM-001",
            run_id="RUN-001",
            decision_packet_ref="",
            decision_packet_hash="",
            final_verdict="allow",
            verdict_reason="test",
            context_hash="",
            diff_hash="",
            threshold_version=""
        )
        assert packet.stale_check_result == {}
        assert packet.causal_trace == []
        assert packet.retention_class == RetentionClass.AUDIT
        assert packet.environment == "local"


class TestAuditPacketGenerator:
    def test_generator_creation(self):
        generator = AuditPacketGenerator()
        assert generator is not None

    def test_generator_with_custom_retention(self):
        generator = AuditPacketGenerator({"audit": 730, "ops": 180})
        assert generator._retention_days["audit"] == 730


class TestAuditPacketGeneratorGenerate:
    def test_generate_with_assessment(self):
        generator = AuditPacketGenerator()
        # Create mock assessment
        assessment = MagicMock()
        assessment.assessment_id = "ASM-001"
        assessment.run_id = "RUN-001"
        assessment.final_verdict = Verdict.ALLOW
        assessment.verdict_reason = "All checks passed"
        assessment.decision_packet_ref = "DEC-001"
        assessment.context_hash = "ctxhash"
        assessment.diff_hash = "diffhash"
        assessment.threshold_version = "v1"
        assessment.causal_trace = []
        assessment.stale_summary = MagicMock()
        assessment.stale_summary.fresh = True
        assessment.stale_summary.stale_items = []
        assessment.obligation_summary = MagicMock()
        assessment.obligation_summary.fulfillment_rate = 1.0
        assessment.approval_summary = MagicMock()
        assessment.approval_summary.missing_approvals = []
        assessment.evidence_summary = MagicMock()
        assessment.evidence_summary.evidence_strength = 1.0

        packet = generator.generate(assessment)
        assert packet.assessment_id == "ASM-001"
        assert packet.final_verdict == "allow"

    def test_generate_with_trace_id(self):
        generator = AuditPacketGenerator()
        assessment = MagicMock()
        assessment.assessment_id = "ASM-001"
        assessment.run_id = "RUN-001"
        assessment.final_verdict = Verdict.ALLOW
        assessment.verdict_reason = "test"
        assessment.decision_packet_ref = ""
        assessment.context_hash = ""
        assessment.diff_hash = ""
        assessment.threshold_version = ""
        assessment.causal_trace = []
        assessment.stale_summary = MagicMock(fresh=True, stale_items=[])
        assessment.obligation_summary = MagicMock(fulfillment_rate=1.0)
        assessment.approval_summary = MagicMock(missing_approvals=[])
        assessment.evidence_summary = MagicMock(evidence_strength=1.0)

        packet = generator.generate(assessment, trace_id="custom_trace")
        assert packet.trace_id == "custom_trace"


class TestAuditPacketGeneratorExport:
    def test_export_jsonl(self):
        generator = AuditPacketGenerator()
        packet = AuditPacket(
            packet_id="AUD-001",
            trace_id="trace123",
            span_id="span456",
            assessment_id="ASM-001",
            run_id="RUN-001",
            decision_packet_ref="",
            decision_packet_hash="",
            final_verdict="allow",
            verdict_reason="test",
            context_hash="",
            diff_hash="",
            threshold_version="",
            created_at=utc_now()
        )

        jsonl = generator.export_jsonl(packet)
        assert "AUD-001" in jsonl
        assert "trace123" in jsonl


class TestAuditPacketGeneratorDetermineRetention:
    def test_deny_returns_audit(self):
        generator = AuditPacketGenerator()
        assessment = MagicMock()
        assessment.final_verdict = Verdict.DENY
        assessment.causal_trace = []

        result = generator._determine_retention_class(assessment)
        assert result == RetentionClass.AUDIT

    def test_require_human_returns_audit(self):
        generator = AuditPacketGenerator()
        assessment = MagicMock()
        assessment.final_verdict = Verdict.REQUIRE_HUMAN
        assessment.causal_trace = []

        result = generator._determine_retention_class(assessment)
        assert result == RetentionClass.AUDIT

    def test_allow_returns_ops(self):
        generator = AuditPacketGenerator()
        assessment = MagicMock()
        assessment.final_verdict = Verdict.ALLOW
        assessment.causal_trace = []

        result = generator._determine_retention_class(assessment)
        assert result == RetentionClass.OPS


class TestAuditPacketStore:
    def test_store_creation(self):
        store = AuditPacketStore()
        assert store is not None

    def test_save_and_get(self):
        store = AuditPacketStore()
        packet = AuditPacket(
            packet_id="AUD-001",
            trace_id="trace123",
            span_id="span456",
            assessment_id="ASM-001",
            run_id="RUN-001",
            decision_packet_ref="",
            decision_packet_hash="",
            final_verdict="allow",
            verdict_reason="test",
            context_hash="",
            diff_hash="",
            threshold_version=""
        )

        ref = store.save(packet)
        assert ref is not None

        retrieved = store.get("AUD-001")
        assert retrieved is not None
        assert retrieved.packet_id == "AUD-001"

    def test_list_by_run(self):
        store = AuditPacketStore()
        packet1 = AuditPacket(
            packet_id="AUD-001",
            trace_id="trace1",
            span_id="span1",
            assessment_id="ASM-001",
            run_id="RUN-001",
            decision_packet_ref="",
            decision_packet_hash="",
            final_verdict="allow",
            verdict_reason="test",
            context_hash="",
            diff_hash="",
            threshold_version=""
        )
        packet2 = AuditPacket(
            packet_id="AUD-002",
            trace_id="trace2",
            span_id="span2",
            assessment_id="ASM-002",
            run_id="RUN-001",
            decision_packet_ref="",
            decision_packet_hash="",
            final_verdict="deny",
            verdict_reason="test",
            context_hash="",
            diff_hash="",
            threshold_version=""
        )
        store.save(packet1)
        store.save(packet2)

        packets = store.list_by_run("RUN-001")
        assert len(packets) == 2

    def test_list_by_assessment(self):
        store = AuditPacketStore()
        packet = AuditPacket(
            packet_id="AUD-001",
            trace_id="trace1",
            span_id="span1",
            assessment_id="ASM-001",
            run_id="RUN-001",
            decision_packet_ref="",
            decision_packet_hash="",
            final_verdict="allow",
            verdict_reason="test",
            context_hash="",
            diff_hash="",
            threshold_version=""
        )
        store.save(packet)

        packets = store.list_by_assessment("ASM-001")
        assert len(packets) == 1

    def test_get_nonexistent(self):
        store = AuditPacketStore()
        result = store.get("AUD-UNKNOWN")
        assert result is None


class TestCreateAuditPacketFunction:
    def test_create_audit_packet_function(self):
        assessment = MagicMock()
        assessment.assessment_id = "ASM-001"
        assessment.run_id = "RUN-001"
        assessment.final_verdict = Verdict.ALLOW
        assessment.verdict_reason = "test"
        assessment.decision_packet_ref = ""
        assessment.context_hash = ""
        assessment.diff_hash = ""
        assessment.threshold_version = ""
        assessment.causal_trace = []
        assessment.stale_summary = MagicMock(fresh=True, stale_items=[])
        assessment.obligation_summary = MagicMock(fulfillment_rate=1.0)
        assessment.approval_summary = MagicMock(missing_approvals=[])
        assessment.evidence_summary = MagicMock(evidence_strength=1.0)

        packet = create_audit_packet(assessment)
        assert packet.assessment_id == "ASM-001"
