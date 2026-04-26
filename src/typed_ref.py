"""
typed_ref Canonical Format Module

Implements 4-segment canonical typed reference format as defined in
adapter_contract.md Section "typed_ref Canonical Format".

Format: <domain>:<entity_type>:<provider>:<entity_id>

Reference: memx-resolver interfaces.md lines 197-245
Reference: agent-taskstate src/typed_ref.py
"""

from dataclasses import dataclass

# KNOWN_DOMAINS for agent-state-gate (extends agent-taskstate domains)
KNOWN_DOMAINS: set[str] = {
    "agent-taskstate",
    "memx",
    "tracker",
    "agent-gatefield",
    "agent-state-gate",
    "shipyard-cp",
    "workflow-cookbook",
}

KNOWN_ENTITY_TYPES: set[str] = {
    "task",
    "run",
    "decision",
    "context_bundle",
    "read_receipt",
    "assessment",
    "audit_packet",
    "evidence",
    "artifact",
    "doc",
    "chunk",
    "ack",
    "contract",
    "issue",
    "stage",
    "human_queue_item",
}

KNOWN_PROVIDERS: set[str] = {
    "local",
    "jira",
    "github",
    "linear",
    "http",
}


@dataclass
class TypedRef:
    """
    Typed reference with 4-segment canonical format.

    Segments:
    - domain: System area (memx, agent-taskstate, tracker, agent-gatefield, etc.)
    - entity_type: Entity type (evidence, task, decision, run, etc.)
    - provider: Data source (local, jira, github, etc.)
    - entity_id: Unique identifier (UUID or system-specific ID)
    """
    domain: str
    entity_type: str
    provider: str
    entity_id: str

    def __post_init__(self):
        """Validate and normalize segments."""
        self.domain = self.domain.lower()
        self.entity_type = self.entity_type.lower()
        self.provider = self.provider.lower()
        # entity_id preserves case (e.g., PROJ-123, owner/repo#123)

        if self.domain not in KNOWN_DOMAINS:
            raise ValueError(f"Unknown domain: {self.domain}")
        if self.entity_type not in KNOWN_ENTITY_TYPES:
            raise ValueError(f"Unknown entity_type: {self.entity_type}")
        if self.provider not in KNOWN_PROVIDERS:
            raise ValueError(f"Unknown provider: {self.provider}")

    def __str__(self) -> str:
        """Return canonical 4-segment format."""
        return f"{self.domain}:{self.entity_type}:{self.provider}:{self.entity_id}"

    def __repr__(self) -> str:
        return f"TypedRef({self.__str__()})"

    def __hash__(self) -> int:
        return hash(self.__str__())

    def __eq__(self, other) -> bool:
        if isinstance(other, TypedRef):
            return self.__str__() == other.__str__()
        if isinstance(other, str):
            return self.__str__() == other
        return False


def parse_ref(ref_str: str) -> TypedRef:
    """
    Parse a typed reference string into TypedRef.

    Supports:
    - 4-segment canonical: domain:entity_type:provider:entity_id
    - 3-segment legacy: domain:entity_type:entity_id (provider=local)

    Args:
        ref_str: Typed reference string.

    Returns:
        TypedRef instance.

    Raises:
        ValueError: If ref format is invalid.
    """
    segments = ref_str.split(":")

    if len(segments) == 4:
        # Canonical 4-segment format
        return TypedRef(
            domain=segments[0],
            entity_type=segments[1],
            provider=segments[2],
            entity_id=segments[3]
        )

    if len(segments) == 3:
        # Legacy 3-segment format (provider=local)
        return TypedRef(
            domain=segments[0],
            entity_type=segments[1],
            provider="local",
            entity_id=segments[2]
        )

    raise ValueError(
        f"Invalid typed_ref format: '{ref_str}'. "
        f"Expected 3 or 4 segments, got {len(segments)}"
    )


def canonicalize_ref(ref_str: str) -> str:
    """
    Convert any typed_ref format to canonical 4-segment string.

    Args:
        ref_str: Typed reference string (3 or 4 segments).

    Returns:
        Canonical 4-segment string.
    """
    ref = parse_ref(ref_str)
    return str(ref)


def format_ref(
    domain: str,
    entity_type: str,
    provider: str = "local",
    entity_id: str = ""
) -> str:
    """
    Format typed_ref components into canonical string.

    Args:
        domain: System area.
        entity_type: Entity type.
        provider: Data source (default: local).
        entity_id: Unique identifier.

    Returns:
        Canonical 4-segment string.
    """
    ref = TypedRef(domain, entity_type, provider, entity_id)
    return str(ref)


def is_valid_ref(ref_str: str) -> bool:
    """
    Check if a string is a valid typed_ref.

    Args:
        ref_str: String to validate.

    Returns:
        True if valid typed_ref format.
    """
    try:
        parse_ref(ref_str)
        return True
    except ValueError:
        return False


def ref_matches_domain(ref_str: str, domain: str) -> bool:
    """
    Check if a typed_ref matches a specific domain.

    Args:
        ref_str: Typed reference string.
        domain: Domain to match.

    Returns:
        True if ref domain matches.
    """
    try:
        ref = parse_ref(ref_str)
        return ref.domain == domain.lower()
    except ValueError:
        return False


def ref_matches_type(ref_str: str, entity_type: str) -> bool:
    """
    Check if a typed_ref matches a specific entity type.

    Args:
        ref_str: Typed reference string.
        entity_type: Entity type to match.

    Returns:
        True if ref entity_type matches.
    """
    try:
        ref = parse_ref(ref_str)
        return ref.entity_type == entity_type.lower()
    except ValueError:
        return False


# --- Common typed_ref generators for agent-state-gate entities ---

def assessment_ref(assessment_id: str) -> str:
    """Generate assessment typed_ref."""
    return format_ref("agent-state-gate", "assessment", "local", assessment_id)


def audit_packet_ref(packet_id: str) -> str:
    """Generate audit_packet typed_ref."""
    return format_ref("agent-state-gate", "audit_packet", "local", packet_id)


def human_queue_item_ref(item_id: str) -> str:
    """Generate human_queue_item typed_ref."""
    return format_ref("agent-state-gate", "human_queue_item", "local", item_id)


def task_ref(task_id: str) -> str:
    """Generate task typed_ref (agent-taskstate domain)."""
    return format_ref("agent-taskstate", "task", "local", task_id)


def run_ref(run_id: str) -> str:
    """Generate run typed_ref (agent-taskstate domain)."""
    return format_ref("agent-taskstate", "run", "local", run_id)


def decision_ref(decision_id: str) -> str:
    """Generate decision typed_ref (agent-gatefield domain)."""
    return format_ref("agent-gatefield", "decision", "local", decision_id)


def evidence_ref(evidence_id: str) -> str:
    """Generate evidence typed_ref (memx domain)."""
    return format_ref("memx", "evidence", "local", evidence_id)


def doc_ref(doc_id: str) -> str:
    """Generate doc typed_ref (memx domain)."""
    return format_ref("memx", "doc", "local", doc_id)
