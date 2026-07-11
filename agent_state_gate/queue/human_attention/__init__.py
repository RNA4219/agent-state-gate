"""
Human Attention Queue Package

Routes items requiring human review with SLA management and escalation.

Provides backward-compatible imports from human_attention_queue.py.
"""

from .queue import HumanAttentionQueue
from .routing import route_assessment_to_queue
from .types import (
    DEFAULT_ESCALATION_CHAIN,
    DEFAULT_REVIEWER_ROLES,
    DEFAULT_SLA_DEFINITIONS,
    HumanQueueItem,
    OwnershipContext,
    QueueStatus,
    ReasonCode,
    Resolution,
    Severity,
    SLAAction,
    SLADefinition,
)

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
