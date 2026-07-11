"""Structured logging and OpenTelemetry instruments."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from opentelemetry import metrics, trace


class JSONFormatter(logging.Formatter):
    _reserved = set(logging.makeLogRecord({}).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._reserved and key not in {"message", "asctime"}:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_structured_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("agent_state_gate")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger


class Observability:
    def __init__(self) -> None:
        self.tracer = trace.get_tracer("agent_state_gate", "0.5.0")
        meter = metrics.get_meter("agent_state_gate", "0.5.0")
        self.adapter_latency = meter.create_histogram("agent_state_gate.adapter.latency", unit="ms")
        self.adapter_health = meter.create_counter("agent_state_gate.adapter.health")
        self.verdicts = meter.create_counter("agent_state_gate.verdicts")
        self.degraded = meter.create_counter("agent_state_gate.degraded")
        self.replay_mismatch = meter.create_counter("agent_state_gate.replay.mismatch")
        self.queue_backlog = meter.create_up_down_counter("agent_state_gate.queue.backlog")
        self.overrides = meter.create_counter("agent_state_gate.overrides")

    def record_adapter(self, name: str, latency_ms: float, healthy: bool) -> None:
        attributes = {"adapter": name}
        self.adapter_latency.record(latency_ms, attributes)
        self.adapter_health.add(1, {**attributes, "healthy": healthy})

    def record_verdict(self, verdict: str, degraded: bool, profile: str) -> None:
        attributes = {"verdict": verdict, "runtime_profile": profile}
        self.verdicts.add(1, attributes)
        if degraded:
            self.degraded.add(1, attributes)


__all__ = ["JSONFormatter", "Observability", "configure_structured_logging"]
