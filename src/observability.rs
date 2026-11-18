use anyhow::Result;
use opentelemetry::{
    KeyValue, global,
    metrics::{Counter, Histogram},
};
use serde_json::json;
use std::time::Instant;

pub(crate) struct Observability {
    latency: Histogram<f64>,
    health: Counter<u64>,
    verdicts: Counter<u64>,
    degraded: Counter<u64>,
    mismatches: Counter<u64>,
}
impl Observability {
    pub fn new() -> Self {
        let meter = global::meter("agent_state_gate");
        Self {
            latency: meter
                .f64_histogram("agent_state_gate.adapter.latency")
                .with_unit("ms")
                .build(),
            health: meter.u64_counter("agent_state_gate.adapter.health").build(),
            verdicts: meter.u64_counter("agent_state_gate.verdicts").build(),
            degraded: meter.u64_counter("agent_state_gate.degraded").build(),
            mismatches: meter
                .u64_counter("agent_state_gate.replay.mismatch")
                .build(),
        }
    }
    pub fn adapter<T>(&self, name: &'static str, call: impl FnOnce() -> Result<T>) -> Result<T> {
        let start = Instant::now();
        let result = call();
        let attr = KeyValue::new("adapter", name);
        self.latency.record(
            start.elapsed().as_secs_f64() * 1000.0,
            std::slice::from_ref(&attr),
        );
        self.health
            .add(1, &[attr, KeyValue::new("healthy", result.is_ok())]);
        if result.is_err() {
            eprintln!(
                "{}",
                json!({"timestamp":chrono::Utc::now(),"level":"WARNING","logger":"agent_state_gate","message":"adapter call failed","adapter":name})
            );
        }
        result
    }
    pub fn verdict(&self, verdict: &'static str, profile: &'static str, degraded: bool) {
        let attrs = [
            KeyValue::new("verdict", verdict),
            KeyValue::new("runtime_profile", profile),
        ];
        self.verdicts.add(1, &attrs);
        if degraded {
            self.degraded.add(1, &attrs)
        }
    }
    pub fn mismatch(&self, tenant: &str) {
        self.mismatches
            .add(1, &[KeyValue::new("tenant_id", tenant.to_owned())]);
    }
}
