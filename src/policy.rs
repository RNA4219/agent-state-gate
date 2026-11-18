use anyhow::{Context, Result, ensure};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Verdict {
    Allow,
    Revise,
    NeedsApproval,
    RequireHuman,
    StaleBlocked,
    Deny,
}
impl Verdict {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Allow => "allow",
            Self::Revise => "revise",
            Self::NeedsApproval => "needs_approval",
            Self::RequireHuman => "require_human",
            Self::StaleBlocked => "stale_blocked",
            Self::Deny => "deny",
        }
    }
    pub fn queued(self) -> bool {
        matches!(
            self,
            Self::RequireHuman | Self::NeedsApproval | Self::StaleBlocked
        )
    }
}
#[derive(Debug, Copy, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Decision {
    Pass,
    Warn,
    Hold,
    Block,
}
impl Decision {
    pub fn name(self) -> &'static str {
        match self {
            Self::Pass => "pass",
            Self::Warn => "warn",
            Self::Hold => "hold",
            Self::Block => "block",
        }
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Factor {
    pub name: String,
    pub value: f64,
    #[serde(default)]
    pub contribution: f64,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Packet {
    #[serde(default = "v2")]
    pub schema_version: String,
    pub decision_id: String,
    #[serde(default)]
    pub run_id: String,
    #[serde(default)]
    pub artifact_id: String,
    pub decision: Decision,
    pub composite_score: f64,
    #[serde(default)]
    pub factors: Vec<Factor>,
    #[serde(default)]
    pub exemplar_refs: Vec<BTreeMap<String, Value>>,
    #[serde(default)]
    pub action: BTreeMap<String, Value>,
    #[serde(default)]
    pub threshold_version: String,
    #[serde(default)]
    pub policy_version: String,
    #[serde(default)]
    pub static_gate_summary: BTreeMap<String, Value>,
    pub created_at: Option<DateTime<Utc>>,
    #[serde(default = "unknown")]
    pub evidence_status: String,
    #[serde(default)]
    pub degraded_components: Vec<String>,
    #[serde(default)]
    pub request_id: String,
    #[serde(default)]
    pub state_vector_ref: String,
    #[serde(default)]
    pub self_correction_count: u64,
    #[serde(default)]
    pub uncertainty_score: f64,
}
fn v2() -> String {
    "2.0.0".into()
}
fn unknown() -> String {
    "unknown".into()
}
impl Packet {
    pub fn parse(mut value: Value) -> Result<Self> {
        if let Some(d) = value["decision"].as_str() {
            value["decision"] = json!(d.to_ascii_lowercase());
        }
        let p: Self = serde_json::from_value(value)?;
        ensure!(
            !p.decision_id.trim().is_empty()
                && (0.0..=1.0).contains(&p.composite_score)
                && (0.0..=1.0).contains(&p.uncertainty_score)
                && p.factors.iter().all(|f| !f.name.is_empty()),
            "DecisionPacket が不正です"
        );
        Ok(p)
    }
    pub fn reference(&self) -> String {
        format!("agent-gatefield:decision:local:{}", self.decision_id)
    }
}
#[derive(Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Evidence {
    #[serde(default)]
    pub required_evidence: Vec<String>,
    #[serde(default)]
    pub collected_evidence: Vec<String>,
    #[serde(default)]
    pub unlinked_evidence: Vec<String>,
    pub evidence_strength: Option<f64>,
}
impl Evidence {
    pub fn strength(&self) -> f64 {
        let required: BTreeSet<_> = self.required_evidence.iter().collect();
        let collected: BTreeSet<_> = self.collected_evidence.iter().collect();
        if required.is_empty() {
            1.0
        } else {
            required.intersection(&collected).count() as f64 / required.len() as f64
        }
    }
    pub fn report(&self) -> Value {
        let mut v = json!(self);
        v["computed_strength"] = json!(self.strength());
        v
    }
    pub fn from_adapter(v: Value) -> Result<Self> {
        ensure!(v.is_object(), "証跡レポートの形式が不正です");
        if v.get("required_evidence").is_some() || v.get("collected_evidence").is_some() {
            let e: Self = serde_json::from_value(v)?;
            ensure!(
                e.evidence_strength
                    .is_none_or(|f| (0.0..=1.0).contains(&f) && (f - e.strength()).abs() <= 1e-9),
                "証跡の集計値が不一致です"
            );
            return Ok(e);
        }
        let refs = |field: &str, keys: &[&str]| -> Result<Vec<String>> {
            let Some(rows) = v.get(field) else {
                return Ok(vec![]);
            };
            Ok(rows
                .as_array()
                .context("証跡には配列が必要です")?
                .iter()
                .filter_map(|item| {
                    keys.iter()
                        .find_map(|k| item[k].as_str())
                        .map(str::to_owned)
                })
                .collect())
        };
        Ok(Self {
            required_evidence: refs("acceptances", &["id"])?,
            collected_evidence: refs("evidences", &["acceptance_id", "id"])?,
            unlinked_evidence: v
                .get("unlinked_evidences")
                .map(|v| serde_json::from_value(v.clone()))
                .transpose()?
                .unwrap_or_default(),
            evidence_strength: None,
        })
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Risk {
    Low,
    Medium,
    High,
    Critical,
}
impl Risk {
    pub fn derive(caps: &[String]) -> Self {
        caps.iter()
            .map(|s| match s.as_str() {
                "production_data_access" | "external_secret" | "rollback_impossible" => {
                    Self::Critical
                }
                "install_deps" | "network_access" | "read_secrets" | "publish_release" => {
                    Self::High
                }
                "write_repo" => Self::Medium,
                _ => Self::Low,
            })
            .max()
            .unwrap_or(Self::Low)
    }
    pub fn approvals(self) -> Vec<&'static str> {
        match self {
            Self::Critical => vec!["project_lead", "security_reviewer", "release_manager"],
            Self::High => vec!["project_lead", "security_reviewer"],
            _ => vec![],
        }
    }
}
pub fn failure(axis: &str, risk: Risk, action: &str) -> Verdict {
    use Verdict::*;
    match axis {
        "taskstate" => Deny,
        "memx" => StaleBlocked,
        "gatefield" if matches!(action, "publish" | "publish_release" | "release") => Deny,
        "gatefield" if risk >= Risk::High => RequireHuman,
        "shipyard" if risk >= Risk::High => Deny,
        "shipyard" => RequireHuman,
        _ => NeedsApproval,
    }
}
// 旧 adapter が返す JSON のフラグを Python v0.5 と同じ規則で解釈する。
fn flag(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}
pub fn transform(p: &Packet, input: &Value, admin: bool) -> Verdict {
    use Verdict::*;
    let obligation = &input["obligation"];
    let approval = &input["approvals"];
    let required = approval["required"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or_default();
    let approved = approval["approved"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or_default();
    let fulfillment = obligation.get("fulfillment_rate").map_or(1.0, |value| {
        value
            .as_f64()
            .or_else(|| value.as_str()?.parse().ok())
            .filter(|f| f.is_finite())
            .unwrap_or(0.0)
    });
    match p.decision {
        Decision::Block => Deny,
        _ if input["stale"]["fresh"] != true => StaleBlocked,
        Decision::Pass
            if input["evidence"]["computed_strength"]
                .as_f64()
                .unwrap_or(0.0)
                < 0.85 =>
        {
            NeedsApproval
        }
        Decision::Pass if fulfillment < 1.0 => {
            if flag(&obligation["has_critical_unfulfilled"]) {
                Deny
            } else if flag(&obligation["has_high_unfulfilled"]) {
                RequireHuman
            } else {
                NeedsApproval
            }
        }
        Decision::Pass => Allow,
        Decision::Warn
            if p.self_correction_count >= 2
                && ((admin && p.uncertainty_score >= 0.15) || !required.is_empty()) =>
        {
            RequireHuman
        }
        Decision::Warn => Revise,
        Decision::Hold if required.iter().any(|r| !approved.contains(r)) => NeedsApproval,
        Decision::Hold if p.uncertainty_score >= 0.25 => RequireHuman,
        Decision::Hold => NeedsApproval,
    }
}
pub fn safety(input: &Value, risk: Risk) -> Vec<&'static str> {
    let sources = [&input["task"], &input["run"]];
    let mut reasons = vec![];
    if sources.iter().any(|s| {
        ["hard_block", "secret_detected", "compliance_violation"]
            .iter()
            .any(|k| flag(&s[k]))
    }) {
        reasons.push("hard safety indicator detected");
    }
    if risk == Risk::Critical
        && sources.iter().any(|s| {
            ["sla_status", "severity"]
                .into_iter()
                .zip(["timeout", "critical"])
                .all(|(k, v)| s[k].as_str().is_some_and(|s| s.eq_ignore_ascii_case(v)))
        })
    {
        reasons.push("critical SLA timeout");
    }
    reasons
}
