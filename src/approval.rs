use crate::{Evaluation, GateService, hash::hash};
use anyhow::Result;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeSet;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ApprovalBinding {
    pub approval_id: String,
    pub diff_hash: String,
    pub context_hash: String,
    pub policy_version: String,
    #[serde(default)]
    pub approved_roles: BTreeSet<String>,
    pub expires_at: Option<DateTime<Utc>>,
}
impl GateService {
    /// 信頼済みの承認記録を、現在のテナントの差分・コンテキストに結び付ける。
    pub fn save_approval_binding(&mut self, binding: &ApprovalBinding) -> Result<()> {
        self.identity.require_current()?;
        self.db.save_binding(&self.identity.tenant, binding)
    }
    pub fn approval_is_current(
        &mut self,
        id: &str,
        diff: &str,
        context: &str,
        policy: &str,
        now: DateTime<Utc>,
    ) -> Result<bool> {
        self.identity.require_current()?;
        self.db
            .approval_current(&self.identity.tenant, id, diff, context, policy, now)
    }
}

/// 承認対象の内容と監査用の実行メタデータを分け、再評価で同じ指紋を得る。
pub(crate) fn context_hash(
    request: &Evaluation,
    context: &Value,
    stage: &str,
    identity: &Value,
) -> String {
    let mut subject = json!(request);
    subject.as_object_mut().unwrap().remove("diff_hash");
    let mut material = context.clone();
    if let Some(run) = material["run"].as_object_mut() {
        run.remove("approved_roles");
    }
    if let Some(stale) = material["stale"].as_object_mut() {
        stale.remove("last_check_at");
    }
    if let Some(packet) = material["decision_packet"].as_object_mut() {
        for field in ["decision_id", "request_id", "created_at"] {
            packet.remove(field);
        }
    }
    hash(
        &json!({"version":1,"request":subject,"context":material,"stage":stage,"identity":identity}),
    )
}
