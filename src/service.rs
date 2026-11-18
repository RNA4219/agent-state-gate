use super::{
    adapters::Adapters,
    auth::{self, Credentials, Identity},
    config::{AXES, Config},
    db::Store,
    hash::hash,
    id,
    policy::*,
};
use anyhow::{Context, Result, ensure};
use chrono::{DateTime, Utc};
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    time::Instant,
};

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Evaluation {
    pub task_id: String,
    pub run_id: String,
    pub action: String,
    #[serde(default)]
    pub capabilities: Vec<String>,
    #[serde(default)]
    pub risk_hints: BTreeMap<String, Value>,
    #[serde(default)]
    pub touched_paths: Vec<String>,
    #[serde(default)]
    pub artifact_refs: Vec<String>,
    pub diff_hash: Option<String>,
    pub semantic_evidence: Option<BTreeMap<String, Value>>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StateAssessment {
    pub artifact_refs: Vec<String>,
    pub diff_hash: String,
    pub redacted_diff: Option<String>,
    pub semantic_evidence: Option<BTreeMap<String, Value>>,
    pub run_id: String,
    pub stage: String,
}
pub(crate) fn valid_hash(s: &str) -> Result<String> {
    ensure!(
        s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()),
        "64桁の16進ハッシュが必要です"
    );
    Ok(s.to_ascii_lowercase())
}

pub struct GateService {
    pub(crate) config: Config,
    pub(crate) identity: Identity,
    pub(crate) client: Client,
    pub(crate) db: Store,
    metrics: crate::observability::Observability,
}
struct Outcomes {
    verdict: Verdict,
    reasons: Vec<String>,
    applied: BTreeMap<String, Verdict>,
}
impl Outcomes {
    fn new() -> Self {
        Self {
            verdict: Verdict::Allow,
            reasons: vec![],
            applied: BTreeMap::new(),
        }
    }
    fn record(&mut self, verdict: Verdict, reason: String) {
        self.verdict = self.verdict.max(verdict);
        if !self.reasons.contains(&reason) {
            self.reasons.push(reason)
        }
    }
    fn failed(&mut self, axis: &str, risk: Risk, action: &str) {
        let v = failure(axis, risk, action);
        self.applied.insert(axis.into(), v);
        self.record(v, format!("{axis} unavailable -> {}", v.as_str()));
    }
}
impl GateService {
    pub fn open(config: Config, credentials: Credentials<'_>) -> Result<Self> {
        config.validate()?;
        let client = Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .build()?;
        let identity = auth::authenticate(&config, credentials, &client)?;
        let db = Store::open(&config.database.url, config.runtime_profile.local())?;
        Ok(Self {
            config,
            identity,
            metrics: crate::observability::Observability::new(),
            client,
            db,
        })
    }
    pub(crate) fn adapters(&self) -> Adapters<'_> {
        Adapters {
            cfg: &self.config,
            client: &self.client,
        }
    }
    pub fn evaluate(&mut self, mut req: Evaluation) -> Result<Value> {
        self.identity.require_current()?;
        ensure!(
            [&req.task_id, &req.run_id, &req.action]
                .iter()
                .all(|s| !s.is_empty()),
            "task_id、run_id、action が必要です"
        );
        if let Some(s) = req.diff_hash.as_mut() {
            *s = valid_hash(s)?
        }
        let a = self.adapters();
        let who = &self.identity;
        let action = &req.action;
        let mut outcome = Outcomes::new();
        let task_result = self
            .metrics
            .adapter("taskstate", || a.taskstate("task", "--task", &req.task_id));
        let task_valid = task_result.is_ok();
        let run_result = self
            .metrics
            .adapter("taskstate", || a.taskstate("run", "--run", &req.run_id));
        if !task_valid || run_result.is_err() {
            outcome.failed("taskstate", Risk::Medium, action)
        }
        let task = task_result.unwrap_or_else(|_| json!({"task_id":req.task_id}));
        let run = run_result.unwrap_or_else(|_| json!({"run_id":req.run_id,"stage":"unknown"}));
        let mut bundle = json!({});
        if task_valid
            && let Some(id) = run["context_bundle_id"]
                .as_str()
                .or(run["context_bundle_ref"].as_str())
                .filter(|s| !s.is_empty())
        {
            match self
                .metrics
                .adapter("taskstate", || a.taskstate("context", "--bundle", id))
            {
                Ok(v) => bundle = v,
                Err(_) => outcome.failed("taskstate", Risk::Medium, action),
            }
        }
        let (risk, required) = if self.config.adapters["protocols"].enabled {
            let risk = Risk::derive(&req.capabilities);
            (risk, risk.approvals())
        } else {
            outcome.failed("protocols", Risk::Medium, action);
            (Risk::Medium, vec![])
        };
        let mut input =
            json!({"tenant_id":who.tenant,"task":task,"run":run,"context_bundle":bundle});
        for reason in safety(&input, risk) {
            outcome.record(Verdict::Deny, reason.into())
        }
        input["stale"] = self
            .metrics
            .adapter("memx", || a.stale(&req.task_id))
            .unwrap_or_else(|_| {
                outcome.failed("memx", risk, action);
                json!({"fresh":false,"stale_items":[],"stale_reasons":["memx unavailable"]})
            });
        let evidence = self
            .metrics
            .adapter("workflow", || {
                a.workflow(&req.task_id, run["stage"].as_str())
            })
            .and_then(Evidence::from_adapter)
            .unwrap_or_else(|_| {
                outcome.failed("workflow", risk, action);
                Evidence {
                    required_evidence: vec!["workflow-contract".into()],
                    ..Evidence::default()
                }
            });
        input["evidence"] = evidence.report();
        input["approvals"] = json!({"required":required,"binding_version":1});
        input["obligation"] = task
            .get("obligation_summary")
            .cloned()
            .unwrap_or(json!({"fulfillment_rate":1.0}));
        let artifact_ref = req.artifact_refs.first();
        let mut message = json!({"artifact_id":artifact_ref.cloned().unwrap_or_else(||format!("task:{}",req.task_id)),
            "artifact_ref":artifact_ref.map(String::as_str).unwrap_or(""),"diff_hash":req.diff_hash,"run_id":req.run_id,
            "trace":{"run_id":req.run_id,"trace_id":who.trace,"tenant_id":who.tenant}});
        match &req.semantic_evidence {
            Some(e) => message["semantic_evidence"] = json!(e),
            None => {
                message["artifact"] = json!({"artifact_refs":req.artifact_refs,"touched_paths":req.touched_paths,"action":action})
            }
        }
        let packet = self
            .metrics
            .adapter("gatefield", || a.packet(&message))
            .and_then(Packet::parse);
        let mut trace = vec![];
        let mut packet_ref = String::new();
        let mut policy_version = &self.config.version;
        let mut threshold = "";
        if let Ok(p) = &packet {
            trace.push(json!({"source":"gatefield","decision_id":p.decision_id,"decision":p.decision,"threshold_version":p.threshold_version}));
            packet_ref = p.reference();
            policy_version = &p.policy_version;
            threshold = &p.threshold_version;
        } else {
            outcome.failed("gatefield", risk, action)
        }
        input["decision_packet"] = json!(packet.as_ref().ok());
        let stage_data = self
            .metrics
            .adapter("shipyard", || a.stage(&req.run_id))
            .unwrap_or_else(|_| {
                outcome.failed("shipyard", risk, action);
                Value::Null
            });
        let stage = stage_data["stage"]
            .as_str()
            .or(run["stage"].as_str())
            .unwrap_or("unknown");
        let context_hash = crate::approval::context_hash(&req, &input, stage, &who.claims());
        let approved = match req.diff_hash.as_deref() {
            Some(diff) if !required.is_empty() && diff.bytes().any(|b| b != b'0') => self
                .db
                .current_approval_roles(&who.tenant, diff, &context_hash, policy_version)?,
            _ => BTreeSet::new(),
        };
        let missing: Vec<_> = required
            .iter()
            .copied()
            .filter(|role| !approved.contains(*role))
            .collect();
        input["approvals"]["approved"] = json!(approved);
        if let Ok(p) = &packet {
            let transformed = transform(p, &input, who.roles.contains("admin"));
            outcome.record(
                transformed,
                format!(
                    "gatefield={} -> {}",
                    p.decision.name(),
                    transformed.as_str()
                ),
            );
        }
        if !missing.is_empty() {
            outcome.record(
                Verdict::NeedsApproval,
                format!("current approval required: {}", missing.join(", ")),
            );
        }
        let assessment_id = id("ASM-");
        let audit_id = id("01HAUD");
        let audit_ref = format!("agent-state-gate:audit_packet:local:{audit_id}");
        let axes = outcome.applied.keys().collect::<Vec<_>>();
        let degraded = !axes.is_empty();
        let verdict = outcome.verdict;
        let reason = if outcome.reasons.is_empty() {
            verdict.as_str().replace('_', " ")
        } else {
            outcome.reasons.join("; ")
        };
        let assessment = json!({
            "assessment_id": assessment_id,
            "tenant_id": who.tenant,
            "task_id": req.task_id,
            "run_id": req.run_id,
            "stage": stage,
            "decision_packet_ref": packet_ref,
            "final_verdict": verdict,
            "verdict_reason": reason,
            "context_hash": context_hash,
            "diff_hash": req.diff_hash.clone().unwrap_or_else(|| "0".repeat(64)),
            "policy_version": policy_version,
            "threshold_version": threshold,
            "degraded": degraded,
            "unavailable_axes": axes,
            "failure_policy_applied": outcome.applied,
            "causal_trace": trace,
            "evidence_summary": input["evidence"],
            "approval_summary": {
                "required_approvals": required,
                "approved_roles": approved,
                "missing_approvals": missing
            },
            "created_at": Utc::now()
        });
        let audit = json!({
            "packet_id": audit_id,
            "tenant_id": who.tenant,
            "trace_id": who.trace,
            "assessment": assessment,
            "unavailable_axes": axes,
            "failure_policy_applied": outcome.applied
        });
        let snapshot = json!({
            "request": req,
            "context_payload": input,
            "expected_verdict": verdict,
            "assessment_id": assessment_id,
            "policy_version": policy_version,
            "context_identity_hash": hash(&who.claims()),
            "threshold_version": threshold,
            "failure_policy_applied": outcome.applied,
            "audit_packet_ref": audit_ref
        });
        let queue = verdict.queued().then(|| {
            json!({
                "item_id": id("QI-"),
                "assessment_id": assessment_id,
                "task_id": req.task_id,
                "run_id": req.run_id,
                "severity": risk,
                "required_role": missing.first().or(required.first()).unwrap_or(&"governance_board"),
                "status": "pending",
                "verdict": verdict,
                "reason": reason
            })
        });
        self.db
            .save(&assessment, &audit, &snapshot, queue.as_ref())?;
        self.metrics.verdict(
            verdict.as_str(),
            self.config.runtime_profile.name(),
            degraded,
        );
        eprintln!(
            "{}",
            json!({
                "timestamp":Utc::now(),"level":"INFO","logger":"agent_state_gate","message":"gate evaluation completed",
                "tenant_id":who.tenant,"task_id":req.task_id,"run_id":req.run_id,"verdict":verdict,"degraded":degraded,"unavailable_axes":axes
            })
        );
        Ok(
            json!({"verdict":verdict,"assessment_id":assessment_id,"verdict_reason":reason,"runtime_profile":self.config.runtime_profile,
            "degraded":degraded,"unavailable_axes":axes,"failure_policy_applied":outcome.applied,"policy_version":policy_version,"audit_packet_ref":audit_ref,
            "required_evidence":evidence.required_evidence,"required_approvals":required,"causal_trace":trace}),
        )
    }
    pub fn assess(&self, req: StateAssessment) -> Result<Value> {
        self.identity.require_current()?;
        ensure!(
            !req.artifact_refs.is_empty() && !req.run_id.is_empty() && !req.stage.is_empty(),
            "artifact_ref、run_id、stage が必要です"
        );
        let mut msg = json!({"artifact_id":req.artifact_refs[0],"artifact_ref":req.artifact_refs[0],"diff_hash":valid_hash(&req.diff_hash)?,
            "run_id":req.run_id,"trace":{"run_id":req.run_id,"trace_id":self.identity.trace,"stage":req.stage}});
        ensure!(
            req.semantic_evidence.is_some() != req.redacted_diff.is_some(),
            "redacted_diff と semantic_evidence のどちらか一方を指定してください"
        );
        if let Some(v) = req.semantic_evidence {
            msg["semantic_evidence"] = json!(v)
        } else {
            msg["artifact"] = json!(req.redacted_diff)
        }
        let mut result = json!({"assessment_id":id("ASM-"),"decision_packet_ref":"","scores":{},"recommendation":"hold_for_review","human_queue_required":true,
            "exemplar_refs":[],"threshold_version":"","degraded":true,"unavailable_axes":["gatefield"]});
        let raw = match self
            .metrics
            .adapter("gatefield", || self.adapters().packet(&msg))
        {
            Ok(v) => v,
            Err(_) => {
                if matches!(req.stage.as_str(), "publish" | "release") {
                    result["recommendation"] = json!("block")
                }
                return Ok(result);
            }
        };
        if let Ok(p) = Packet::parse(raw) {
            result["recommendation"] = json!(match p.decision {
                Decision::Pass => "continue",
                Decision::Warn => "self_correct",
                Decision::Hold => "hold_for_review",
                Decision::Block => "block",
            });
            result["human_queue_required"] = json!(
                p.decision == Decision::Hold
                    || (p.decision == Decision::Warn && p.self_correction_count >= 2)
            );
            result["decision_packet_ref"] = json!(p.reference());
            result["threshold_version"] = json!(p.threshold_version);
            result["scores"] = json!(
                p.factors
                    .iter()
                    .map(|f| (&f.name, f.value))
                    .collect::<BTreeMap<_, _>>()
            );
            result["exemplar_refs"] = json!(
                p.exemplar_refs
                    .iter()
                    .map(|v| v.get("doc_id").and_then(Value::as_str).unwrap_or(""))
                    .collect::<Vec<_>>()
            );
            result["degraded"] = json!(false);
            result["unavailable_axes"] = json!([]);
        }
        Ok(result)
    }
    pub fn replay(&mut self, run: &str, at: Option<DateTime<Utc>>) -> Result<Value> {
        self.identity.require_current()?;
        let mut result = json!({"run_id":run,"status":"unavailable","expected_verdict":null,"actual_verdict":null,"attestation_hash":null,
            "audit_packet_ref":"","details":{},"reproducibility_verified":false});
        let Some((s, attestation, recorded)) = self.db.snapshot(&self.identity.tenant, run, at)?
        else {
            result["details"] = json!({"reason":if at.is_some(){"no snapshot at requested time"}else{"snapshot not found"}});
            return Ok(result);
        };
        let current = hash(&s);
        result["attestation_hash"] = json!(current);
        if recorded.is_empty() {
            result["details"] = json!({"reason":"assessment not found"});
            return Ok(result);
        }
        let input = &s["context_payload"];
        let actual = (|| -> Result<Verdict> {
            let mut verdict = Verdict::Allow;
            if !input["decision_packet"].is_null() {
                let p = Packet::parse(input["decision_packet"].clone())?;
                let mut verified = input.clone();
                let mut e = verified["evidence"].clone();
                e.as_object_mut()
                    .context("証跡の形式が不正です")?
                    .remove("computed_strength");
                let evidence: Evidence = serde_json::from_value(e)?;
                verified["evidence"] = evidence.report();
                verdict = transform(&p, &verified, self.identity.roles.contains("admin"));
            }
            let approvals = &input["approvals"];
            if approvals["binding_version"] == 1 {
                let required: BTreeSet<String> =
                    serde_json::from_value(approvals["required"].clone())?;
                let approved: BTreeSet<String> =
                    serde_json::from_value(approvals["approved"].clone())?;
                if !required.is_subset(&approved) {
                    verdict = verdict.max(Verdict::NeedsApproval);
                }
            }
            let failures: BTreeMap<String, Verdict> =
                serde_json::from_value(s["failure_policy_applied"].clone())?;
            let caps: Vec<String> = serde_json::from_value(s["request"]["capabilities"].clone())?;
            let risk = if failures.contains_key("protocols") {
                Risk::Medium
            } else {
                Risk::derive(&caps)
            };
            if !safety(input, risk).is_empty() {
                verdict = Verdict::Deny
            }
            Ok(failures.values().copied().fold(verdict, Verdict::max))
        })();
        let identity_hash = hash(&self.identity.claims());
        let matched = actual
            .as_ref()
            .is_ok_and(|v| s["expected_verdict"] == v.as_str() && recorded == v.as_str())
            && current == attestation
            && s["context_identity_hash"]
                .as_str()
                .is_none_or(|v| v == identity_hash)
            && s["policy_version"]
                .as_str()
                .is_none_or(|v| v == self.config.version);
        if !matched {
            self.metrics.mismatch(&self.identity.tenant);
        }
        result["actual_verdict"] = json!(actual.ok());
        result["expected_verdict"] = s["expected_verdict"].clone();
        result["audit_packet_ref"] = s["audit_packet_ref"].clone();
        result["status"] = json!(if matched { "verified" } else { "mismatch" });
        result["reproducibility_verified"] = json!(matched);
        Ok(result)
    }
    pub fn queue(&mut self, status: Option<&str>, role: Option<&str>) -> Result<Vec<Value>> {
        self.identity.require_current()?;
        self.db.queue(&self.identity.tenant, status, role)
    }
    pub fn take(&mut self, item: &str, reviewer: &str) -> Result<Value> {
        self.identity.require_current()?;
        self.db
            .update_queue(&self.identity.tenant, item, reviewer, None)
    }
    pub fn resolve(
        &mut self,
        item: &str,
        reviewer: &str,
        resolution: &str,
        comment: &str,
    ) -> Result<Value> {
        self.identity.require_current()?;
        self.db.update_queue(
            &self.identity.tenant,
            item,
            reviewer,
            Some((resolution, comment)),
        )
    }
    pub fn audit(&mut self, run: Option<&str>) -> Result<Vec<Value>> {
        self.identity.require_current()?;
        self.db.audit(&self.identity.tenant, run)
    }
    pub fn purge(&mut self, reason: &str) -> Result<Value> {
        self.identity.require_current()?;
        ensure!(
            ["governance_board", "data_retention_admin"]
                .iter()
                .any(|r| self.identity.roles.contains(*r)),
            "削除には保持期間管理の権限が必要です"
        );
        self.db
            .purge(&self.identity.tenant, &self.identity.subject, reason)
    }
    pub fn health(&mut self) -> Result<Value> {
        self.identity.require_current()?;
        let mut reports = json!({});
        let mut ready = true;
        for name in AXES {
            let cfg = &self.config.adapters[name];
            if !cfg.enabled {
                ready = false;
                continue;
            }
            let started = Instant::now();
            let (ok, details) = self
                .adapters()
                .health(name)
                .unwrap_or((false, json!({"error_type":"AdapterUnavailableError"})));
            reports[name] = json!({"name":name,"healthy":ok,"latency_ms":started.elapsed().as_secs_f64()*1000.0,"failure_policy":cfg.failure_policy,"details":details});
            ready &= ok;
        }
        let database = self.db.healthy();
        ready &= database;
        Ok(
            json!({"ready":ready,"runtime_profile":self.config.runtime_profile,"adapters":reports,"database_healthy":database,"production_ready":ready,"checked_at":Utc::now()}),
        )
    }
}
