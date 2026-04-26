"""
Tests for verdict_transformer module.

Tests resolve_verdict logic with Decision Table rules.
Reference: BLUEPRINT.md Section 6, AC-003_verdict_transformation.json
"""

from src.core.verdict_transformer import (
    ApprovalSummary,
    Decision,
    EvidenceSummary,
    ObligationSummary,
    StaleSummary,
    Verdict,
    VerdictTransformer,
    get_verdict_priority,
    resolve_verdict,
)


class TestResolveVerdict:
    """Tests for resolve_verdict function."""

    def test_block_always_returns_deny(self):
        """block decision → deny (Priority 1: Hard override)."""
        verdict = resolve_verdict(
            decision="block",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
        )
        assert verdict == Verdict.DENY

    def test_stale_returns_stale_blocked(self):
        """stale → stale_blocked (Priority 2: Stale detection)."""
        verdict = resolve_verdict(
            decision="pass",
            stale_summary=StaleSummary(fresh=False, stale_reasons=["doc_version_changed"]),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
        )
        assert verdict == Verdict.STALE_BLOCKED

    def test_pass_all_conditions_met_returns_allow(self):
        """pass + all conditions met → allow."""
        verdict = resolve_verdict(
            decision="pass",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
        )
        assert verdict == Verdict.ALLOW

    def test_pass_evidence_insufficient_returns_needs_approval(self):
        """pass + evidence < 0.85 → needs_approval."""
        verdict = resolve_verdict(
            decision="pass",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=0.7),
        )
        assert verdict == Verdict.NEEDS_APPROVAL

    def test_pass_obligation_critical_unfulfilled_returns_deny(self):
        """pass + critical obligation unfulfilled → deny."""
        verdict = resolve_verdict(
            decision="pass",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(
                fulfillment_rate=0.5,
                has_critical_unfulfilled=True
            ),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
        )
        assert verdict == Verdict.DENY

    def test_pass_obligation_high_unfulfilled_returns_require_human(self):
        """pass + high obligation unfulfilled → require_human."""
        verdict = resolve_verdict(
            decision="pass",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(
                fulfillment_rate=0.8,
                has_high_unfulfilled=True
            ),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
        )
        assert verdict == Verdict.REQUIRE_HUMAN

    def test_pass_obligation_medium_unfulfilled_returns_needs_approval(self):
        """pass + medium obligation unfulfilled → needs_approval."""
        verdict = resolve_verdict(
            decision="pass",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(
                fulfillment_rate=0.8,
                has_critical_unfulfilled=False,
                has_high_unfulfilled=False
            ),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
        )
        assert verdict == Verdict.NEEDS_APPROVAL


class TestResolveVerdictWarn:
    """Tests for warn decision branching."""

    def test_warn_self_correction_possible_returns_revise(self):
        """warn + self_correction_count < 2 → revise."""
        verdict = resolve_verdict(
            decision="warn",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            self_correction_count=1,
        )
        assert verdict == Verdict.REVISE

    def test_warn_admin_high_uncertainty_returns_require_human(self):
        """warn + admin + uncertainty >= 0.15 → require_human."""
        verdict = resolve_verdict(
            decision="warn",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            permission_level="admin",
            uncertainty_score=0.20,
            self_correction_count=2,
        )
        assert verdict == Verdict.REQUIRE_HUMAN

    def test_warn_required_approvals_returns_require_human(self):
        """warn + required_approvals → require_human."""
        verdict = resolve_verdict(
            decision="warn",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(required_approvals=["security_reviewer"]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            self_correction_count=2,
        )
        assert verdict == Verdict.REQUIRE_HUMAN


class TestResolveVerdictHold:
    """Tests for hold decision branching."""

    def test_hold_missing_approvals_returns_needs_approval(self):
        """hold + missing_approvals → needs_approval."""
        verdict = resolve_verdict(
            decision="hold",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=["project_lead"]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
        )
        assert verdict == Verdict.NEEDS_APPROVAL

    def test_hold_high_uncertainty_returns_require_human(self):
        """hold + uncertainty >= 0.25 → require_human."""
        verdict = resolve_verdict(
            decision="hold",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            uncertainty_score=0.30,
        )
        assert verdict == Verdict.REQUIRE_HUMAN

    def test_hold_sla_timeout_returns_deny(self):
        """hold + sla_timeout → deny."""
        verdict = resolve_verdict(
            decision="hold",
            stale_summary=StaleSummary(fresh=True),
            obligation_summary=ObligationSummary(fulfillment_rate=1.0),
            approval_summary=ApprovalSummary(missing_approvals=[]),
            evidence_summary=EvidenceSummary(evidence_strength=1.0),
            sla_status="timeout",
        )
        assert verdict == Verdict.DENY


class TestVerdictPriority:
    """Tests for verdict priority ordering."""

    def test_deny_is_highest_priority(self):
        """DENY has highest priority (6)."""
        assert get_verdict_priority(Verdict.DENY) == 6

    def test_allow_is_lowest_priority(self):
        """ALLOW has lowest priority (1)."""
        assert get_verdict_priority(Verdict.ALLOW) == 1

    def test_priority_ordering(self):
        """Priority ordering: deny > stale_blocked > require_human > needs_approval > revise > allow."""
        priorities = [
            get_verdict_priority(Verdict.DENY),
            get_verdict_priority(Verdict.STALE_BLOCKED),
            get_verdict_priority(Verdict.REQUIRE_HUMAN),
            get_verdict_priority(Verdict.NEEDS_APPROVAL),
            get_verdict_priority(Verdict.REVISE),
            get_verdict_priority(Verdict.ALLOW),
        ]
        assert priorities == sorted(priorities, reverse=True)


class TestVerdictTransformer:
    """Tests for VerdictTransformer class."""

    def test_transform_creates_context(self):
        """transform creates TransformContext."""
        transformer = VerdictTransformer()

        decision_packet = {
            "decision": "pass",
            "composite_score": 0.9,
            "factors": [],
        }
        stale_result = {"fresh": True, "stale_items": []}
        obligation_result = {"fulfillment_rate": 1.0}
        approval_result = {"missing_approvals": [], "required_approvals": []}
        evidence_result = {"evidence_strength": 1.0}

        context = transformer.transform(
            decision_packet=decision_packet,
            stale_result=stale_result,
            obligation_result=obligation_result,
            approval_result=approval_result,
            evidence_result=evidence_result,
        )

        assert context.final_verdict == Verdict.ALLOW
        assert context.decision == Decision.PASS

    def test_transform_with_stale(self):
        """transform handles stale correctly."""
        transformer = VerdictTransformer()

        decision_packet = {"decision": "pass", "composite_score": 0.9}
        stale_result = {"fresh": False, "stale_reasons": ["doc_version_changed"]}
        obligation_result = {"fulfillment_rate": 1.0}
        approval_result = {"missing_approvals": []}
        evidence_result = {"evidence_strength": 1.0}

        context = transformer.transform(
            decision_packet=decision_packet,
            stale_result=stale_result,
            obligation_result=obligation_result,
            approval_result=approval_result,
            evidence_result=evidence_result,
        )

        assert context.final_verdict == Verdict.STALE_BLOCKED


class TestVerdictEnum:
    """Tests for Verdict enum."""

    def test_verdict_values(self):
        """Verdict enum has correct values."""
        assert Verdict.ALLOW.value == "allow"
        assert Verdict.DENY.value == "deny"
        assert Verdict.STALE_BLOCKED.value == "stale_blocked"
        assert Verdict.NEEDS_APPROVAL.value == "needs_approval"
        assert Verdict.REQUIRE_HUMAN.value == "require_human"
        assert Verdict.REVISE.value == "revise"


class TestDecisionEnum:
    """Tests for Decision enum."""

    def test_decision_values(self):
        """Decision enum has correct values."""
        assert Decision.PASS.value == "pass"
        assert Decision.WARN.value == "warn"
        assert Decision.HOLD.value == "hold"
        assert Decision.BLOCK.value == "block"
