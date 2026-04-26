"""
Tests for typed_ref module.

Tests 4-segment canonical format, parsing, and format utilities.
Reference: AC-006_typed_ref_canonical.json golden fixture
"""

import pytest

from src.typed_ref import (
    KNOWN_DOMAINS,
    KNOWN_ENTITY_TYPES,
    KNOWN_PROVIDERS,
    TypedRef,
    assessment_ref,
    audit_packet_ref,
    canonicalize_ref,
    decision_ref,
    doc_ref,
    evidence_ref,
    format_ref,
    human_queue_item_ref,
    is_valid_ref,
    parse_ref,
    ref_matches_domain,
    ref_matches_type,
    run_ref,
    task_ref,
)


class TestTypedRefParsing:
    """Tests for typed_ref parsing."""

    def test_parse_4_segment_canonical(self):
        """Parse canonical 4-segment format."""
        ref_str = "agent-taskstate:task:local:01HTSK0001"
        ref = parse_ref(ref_str)

        assert ref.domain == "agent-taskstate"
        assert ref.entity_type == "task"
        assert ref.provider == "local"
        assert ref.entity_id == "01HTSK0001"

    def test_parse_3_segment_legacy(self):
        """Parse legacy 3-segment format (provider=local)."""
        ref_str = "agent-taskstate:task:01HTSK0001"
        ref = parse_ref(ref_str)

        assert ref.domain == "agent-taskstate"
        assert ref.entity_type == "task"
        assert ref.provider == "local"  # Default
        assert ref.entity_id == "01HTSK0001"

    def test_parse_invalid_format_raises(self):
        """Invalid format raises ValueError."""
        with pytest.raises(ValueError):
            parse_ref("invalid-ref")

        with pytest.raises(ValueError):
            parse_ref("too:many:segments:here:extra")

    def test_parse_unknown_domain_raises(self):
        """Unknown domain raises ValueError."""
        with pytest.raises(ValueError):
            parse_ref("unknown-domain:task:local:01HTEST")

    def test_parse_unknown_entity_type_raises(self):
        """Unknown entity_type raises ValueError."""
        with pytest.raises(ValueError):
            parse_ref("agent-taskstate:unknown-type:local:01HTEST")


class TestTypedRefCanonicalization:
    """Tests for canonicalization."""

    def test_canonicalize_3_segment(self):
        """Canonicalize 3-segment to 4-segment."""
        ref_str = "memx:evidence:01HEV0001"
        canonical = canonicalize_ref(ref_str)

        assert canonical == "memx:evidence:local:01HEV0001"

    def test_canonicalize_4_segment_unchanged(self):
        """4-segment format unchanged."""
        ref_str = "agent-gatefield:decision:local:01HDEC0001"
        canonical = canonicalize_ref(ref_str)

        assert canonical == ref_str


class TestTypedRefFormatting:
    """Tests for formatting."""

    def test_format_ref_default_provider(self):
        """Format with default provider=local."""
        ref_str = format_ref("agent-taskstate", "run", entity_id="01HRUN0001")

        assert ref_str == "agent-taskstate:run:local:01HRUN0001"

    def test_format_ref_custom_provider(self):
        """Format with custom provider."""
        ref_str = format_ref("tracker", "issue", "github", "owner/repo#123")

        assert ref_str == "tracker:issue:github:owner/repo#123"

    def test_format_ref_lowercase_domain(self):
        """Domain normalized to lowercase."""
        ref_str = format_ref("AGENT-TASKSTATE", "task", entity_id="01HTEST")

        assert "agent-taskstate" in ref_str


class TestTypedRefValidation:
    """Tests for validation."""

    def test_is_valid_ref_valid_4_segment(self):
        """Valid 4-segment ref returns True."""
        assert is_valid_ref("agent-taskstate:task:local:01HTSK0001")

    def test_is_valid_ref_valid_3_segment(self):
        """Valid 3-segment ref returns True."""
        assert is_valid_ref("agent-taskstate:task:01HTSK0001")

    def test_is_valid_ref_invalid_returns_false(self):
        """Invalid ref returns False."""
        assert not is_valid_ref("invalid-ref")
        assert not is_valid_ref("unknown:task:local:01HTEST")


class TestTypedRefMatching:
    """Tests for domain/type matching."""

    def test_ref_matches_domain_true(self):
        """Matching domain returns True."""
        assert ref_matches_domain("agent-taskstate:task:local:01HTEST", "agent-taskstate")

    def test_ref_matches_domain_false(self):
        """Non-matching domain returns False."""
        assert not ref_matches_domain("memx:evidence:local:01HTEST", "agent-taskstate")

    def test_ref_matches_type_true(self):
        """Matching entity_type returns True."""
        assert ref_matches_type("agent-taskstate:task:local:01HTEST", "task")

    def test_ref_matches_type_false(self):
        """Non-matching entity_type returns False."""
        assert not ref_matches_type("agent-taskstate:run:local:01HTEST", "task")


class TestTypedRefConvenienceFunctions:
    """Tests for convenience ref generators."""

    def test_assessment_ref(self):
        """assessment_ref generates correct format."""
        ref = assessment_ref("01HASM0001")
        assert ref == "agent-state-gate:assessment:local:01HASM0001"

    def test_task_ref(self):
        """task_ref generates correct format."""
        ref = task_ref("01HTSK0001")
        assert ref == "agent-taskstate:task:local:01HTSK0001"

    def test_run_ref(self):
        """run_ref generates correct format."""
        ref = run_ref("01HRUN0001")
        assert ref == "agent-taskstate:run:local:01HRUN0001"

    def test_decision_ref(self):
        """decision_ref generates correct format."""
        ref = decision_ref("01HDEC0001")
        assert ref == "agent-gatefield:decision:local:01HDEC0001"


class TestTypedRefEquality:
    """Tests for equality and hashing."""

    def test_typed_ref_str_equality(self):
        """TypedRef equals its string representation."""
        ref = TypedRef("agent-taskstate", "task", "local", "01HTSK0001")
        assert ref == "agent-taskstate:task:local:01HTSK0001"

    def test_typed_ref_ref_equality(self):
        """TypedRef equals another TypedRef with same values."""
        ref1 = TypedRef("agent-taskstate", "task", "local", "01HTSK0001")
        ref2 = TypedRef("agent-taskstate", "task", "local", "01HTSK0001")
        assert ref1 == ref2

    def test_typed_ref_hash_consistent(self):
        """Hash is consistent for equal refs."""
        ref1 = TypedRef("agent-taskstate", "task", "local", "01HTSK0001")
        ref2 = TypedRef("agent-taskstate", "task", "local", "01HTSK0001")
        assert hash(ref1) == hash(ref2)


class TestKnownConstants:
    """Tests for KNOWN constants."""

    def test_known_domains_includes_required(self):
        """KNOWN_DOMAINS includes required domains."""
        required = {"agent-taskstate", "memx", "tracker", "agent-gatefield", "agent-state-gate"}
        assert required.issubset(KNOWN_DOMAINS)


class TestTypedRefConvenienceFunctionsExtra:
    """Tests for extra convenience ref generators."""

    def test_audit_packet_ref(self):
        """audit_packet_ref generates correct format."""
        ref = audit_packet_ref("01HAUD0001")
        assert ref == "agent-state-gate:audit_packet:local:01HAUD0001"

    def test_human_queue_item_ref(self):
        """human_queue_item_ref generates correct format."""
        ref = human_queue_item_ref("01HQI0001")
        assert ref == "agent-state-gate:human_queue_item:local:01HQI0001"

    def test_evidence_ref(self):
        """evidence_ref generates correct format."""
        ref = evidence_ref("01HEV0001")
        assert ref == "memx:evidence:local:01HEV0001"

    def test_doc_ref(self):
        """doc_ref generates correct format."""
        ref = doc_ref("01HDOC0001")
        assert ref == "memx:doc:local:01HDOC0001"


class TestTypedRefMatchingInvalid:
    """Tests for matching with invalid refs."""

    def test_ref_matches_domain_invalid_returns_false(self):
        """Invalid ref returns False for domain matching."""
        assert not ref_matches_domain("invalid-ref", "agent-taskstate")

    def test_ref_matches_type_invalid_returns_false(self):
        """Invalid ref returns False for type matching."""
        assert not ref_matches_type("invalid-ref", "task")


class TestTypedRefUnknownProvider:
    """Tests for unknown provider."""

    def test_unknown_provider_raises(self):
        """Unknown provider raises ValueError."""
        with pytest.raises(ValueError, match="Unknown provider"):
            TypedRef("agent-taskstate", "task", "unknown-provider", "01HTEST")


class TestTypedRefEqualityNonMatching:
    """Tests for equality with non-matching types."""

    def test_typed_ref_not_equal_other_object(self):
        """TypedRef not equal to other object types."""
        ref = TypedRef("agent-taskstate", "task", "local", "01HTEST")
        assert ref != {"domain": "agent-taskstate"}
        assert ref != 123


class TestTypedRefRepr:
    """Tests for TypedRef repr."""

    def test_typed_ref_repr(self):
        """TypedRef repr shows canonical format."""
        ref = TypedRef("agent-taskstate", "task", "local", "01HTEST")
        assert repr(ref) == "TypedRef(agent-taskstate:task:local:01HTEST)"

    def test_known_entity_types_includes_required(self):
        """KNOWN_ENTITY_TYPES includes required types."""
        required = {"task", "run", "decision", "assessment", "evidence"}
        assert required.issubset(KNOWN_ENTITY_TYPES)

    def test_known_providers_includes_required(self):
        """KNOWN_PROVIDERS includes required providers."""
        required = {"local", "github", "jira"}
        assert required.issubset(KNOWN_PROVIDERS)
