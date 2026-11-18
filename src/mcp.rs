use crate::{GateService, StateAssessment, hash::sha256};
use anyhow::{Context, Result, bail};
use chrono::{DateTime, Utc};
use serde::Deserialize;
use serde_json::{Value, json};

pub const TOOLS: [&str; 6] = [
    "context.recall",
    "gate.evaluate",
    "context.stale_check",
    "state_gate.assess",
    "attention.list",
    "run.replay_context",
];
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Recall {
    task_id: String,
    action: String,
    feature: Option<String>,
    #[serde(default)]
    touched_paths: Vec<String>,
    limit: Option<usize>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Attention {
    #[serde(rename = "queue_scope")]
    _scope: Option<String>,
    reviewer_role: Option<String>,
    status: Option<String>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Replay {
    run_id: String,
    as_of: Option<DateTime<Utc>>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Task {
    task_id: String,
}
fn fields(v: &Value, keys: &[(&str, &str)]) -> Value {
    let mut result = json!({});
    for (key, default) in keys {
        result[*key] = json!(v[key].as_str().unwrap_or(default))
    }
    result
}
impl GateService {
    pub fn tool_names() -> &'static [&'static str] {
        &TOOLS
    }
    /// 認証済みサービスから公開 MCP ツールを呼び出す。
    pub fn call_tool(&mut self, name: &str, mut args: Value) -> Result<Value> {
        self.identity.require_current()?;
        match name {
            "gate.evaluate" => {
                if args["run_id"].is_null() && self.config.runtime_profile.local() {
                    args["run_id"] = json!(format!(
                        "RUN-{}",
                        args["task_id"].as_str().context("task_id が必要です")?
                    ))
                }
                self.evaluate(serde_json::from_value(args)?)
            }
            "state_gate.assess" => {
                let mut req: StateAssessment = serde_json::from_value(args)?;
                if req.diff_hash.len() != 64 && self.config.runtime_profile.local() {
                    req.redacted_diff
                        .get_or_insert_with(|| req.diff_hash.clone());
                    req.diff_hash = sha256(&req.diff_hash);
                }
                self.assess(req)
            }
            "run.replay_context" => {
                let r: Replay = serde_json::from_value(args)?;
                self.replay(&r.run_id, r.as_of)
            }
            "context.recall" => {
                let r: Recall = serde_json::from_value(args)?;
                let v = self.adapters().recall(
                    &r.task_id,
                    &r.action,
                    r.feature.as_deref(),
                    &r.touched_paths,
                )?;
                let docs = |key: &str, priority: &str| {
                    v[key]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .take(r.limit.unwrap_or(10))
                        .map(|v| {
                            let mut d = fields(
                                v,
                                &[
                                    ("doc_id", ""),
                                    ("version", ""),
                                    ("doc_type", "unknown"),
                                    ("title", ""),
                                ],
                            );
                            d["priority"] = json!(priority);
                            d
                        })
                        .collect::<Vec<_>>()
                };
                let required = docs("required_docs", "required");
                let stale = &v["stale_summary"];
                let contracts = v["contract_refs"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|v| {
                        fields(
                            v,
                            &[("contract_id", ""), ("contract_type", ""), ("version", "")],
                        )
                    })
                    .collect::<Vec<_>>();
                Ok(
                    json!({"required_docs":required,"recommended_docs":docs("recommended_docs","recommended"),"contract_refs":contracts,
                    "ack_required":!required.is_empty(),"stale_summary":{"fresh":stale["fresh"]==true,"stale_items":stale.get("stale_items").cloned().unwrap_or(json!([])),"stale_reasons":stale.get("stale_reasons").cloned().unwrap_or(json!([]))}}),
                )
            }
            "context.stale_check" => {
                let r: Task = serde_json::from_value(args)?;
                let s = self.adapters().stale(&r.task_id).unwrap_or_else(
                    |_| json!({"fresh":false,"stale_reasons":["memx adapter unavailable"]}),
                );
                let items = s["stale_items"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|v| {
                        fields(
                            v,
                            &[
                                ("item_type", "unknown"),
                                ("item_id", ""),
                                ("current_version", ""),
                                ("expected_version", ""),
                                ("stale_reason", ""),
                            ],
                        )
                    })
                    .collect::<Vec<_>>();
                Ok(
                    json!({"fresh":s["fresh"]==true,"stale_items":items,"stale_reasons":s.get("stale_reasons").cloned().unwrap_or(json!([])),"last_check_at":Utc::now()}),
                )
            }
            "attention.list" => {
                let r: Attention = serde_json::from_value(args)?;
                let items = self.queue(r.status.as_deref(), r.reviewer_role.as_deref())?;
                let count = |k: &str, v: &str| items.iter().filter(|i| i[k] == v).count();
                let mut severity = json!({});
                for s in ["low", "medium", "high", "critical"] {
                    severity[s] = json!(count("severity", s))
                }
                let pending = count("status", "pending");
                Ok(
                    json!({"items":items,"total_pending":pending,"by_severity":severity,"sla_status":{"global":{"pending_count":pending,"ack_timeout_count":0,"decision_timeout_count":0,"escalated_count":count("status","escalated")}}}),
                )
            }
            _ => bail!("未対応の MCP ツール {name}"),
        }
    }
}
