use crate::GateService;
use anyhow::Result;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
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
