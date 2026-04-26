"""
Common utilities for agent-state-gate.

Shared imports, ID generation, timestamp helpers, and hash utilities.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    """Get current UTC timestamp."""
    return datetime.now(UTC)


def generate_id(prefix: str = "01H") -> str:
    """
    Generate unique ID with prefix.

    Args:
        prefix: ID prefix (default "01H").

    Returns:
        Unique ID string.
    """
    return f"{prefix}{uuid.uuid4().hex[:8].upper()}"


def generate_assessment_id() -> str:
    """Generate assessment ID."""
    return generate_id("01HASM")


def generate_audit_packet_id() -> str:
    """Generate audit packet ID."""
    return generate_id("01HAUD")


def generate_queue_item_id() -> str:
    """Generate human queue item ID."""
    return generate_id("01HQI")


def generate_evidence_id() -> str:
    """Generate evidence ID."""
    return generate_id("01HEV")


def generate_trace_id() -> str:
    """Generate OTel trace ID (32 hex chars)."""
    return uuid.uuid4().hex + uuid.uuid4().hex[:16]


def generate_span_id() -> str:
    """Generate OTel span ID (16 hex chars)."""
    return uuid.uuid4().hex[:16]


def hash_dict(data: dict[str, Any]) -> str:
    """
    SHA256 hash of dict (sorted keys).

    Args:
        data: Dict to hash.

    Returns:
        SHA256 hex digest.
    """
    json_str = json.dumps(data, sort_keys=True)
    return hashlib.sha256(json_str.encode()).hexdigest()


def hash_content(content: str) -> str:
    """
    SHA256 hash of string content.

    Args:
        content: String to hash.

    Returns:
        SHA256 hex digest.
    """
    return hashlib.sha256(content.encode()).hexdigest()


def iso_timestamp(dt: datetime | None = None) -> str:
    """
    ISO format timestamp.

    Args:
        dt: datetime object (default: now).

    Returns:
        ISO format string.
    """
    if dt is None:
        dt = utc_now()
    return dt.isoformat()


def parse_iso_timestamp(ts: str) -> datetime:
    """
    Parse ISO timestamp string.

    Args:
        ts: ISO format string.

    Returns:
        datetime object.
    """
    return datetime.fromisoformat(ts)


__version__ = "0.4.2"

# Common constants
SCHEMA_VERSION = "1.0.0"
DEFAULT_TIMEOUT_MS = 5000
DEFAULT_ENVIRONMENT = "local"


# Severity levels (shared across modules)
SEVERITY_LEVELS = ["critical", "high", "medium", "low"]

# Verdict priority mapping
VERDICT_PRIORITIES = {
    "deny": 6,
    "stale_blocked": 5,
    "require_human": 4,
    "needs_approval": 3,
    "revise": 2,
    "allow": 1,
}
