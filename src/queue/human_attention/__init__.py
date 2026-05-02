"""
Human Attention Queue Package

Routes items requiring human review with SLA management and escalation.

Provides backward-compatible imports from human_attention_queue.py.
"""

from .types import (
    QueueStatus,
    ReasonCode,
    Severity,
    Resolution,
    SLAAction,
    SLADefinition,
    OwnershipContext,
    HumanQueueItem,
    DEFAULT_SLA_DEFINITIONS,
    DEFAULT_ESCALATION_CHAIN,
    DEFAULT_REVIEWER_ROLES,
)
from .queue import HumanAttentionQueue
from .routing import route_assessment_to_queue


__all__ = [
    # Enums
    "QueueStatus",
    "ReasonCode",
    "Severity",
    "Resolution",
    "SLAAction",
    # Dataclasses
    "SLADefinition",
    "OwnershipContext",
    "HumanQueueItem",
    # Class
    "HumanAttentionQueue",
    # Functions
    "route_assessment_to_queue",
    # Defaults
    "DEFAULT_SLA_DEFINITIONS",
    "DEFAULT_ESCALATION_CHAIN",
    "DEFAULT_REVIEWER_ROLES",
]