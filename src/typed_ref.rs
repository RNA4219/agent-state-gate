use anyhow::{Result, bail, ensure};
use std::{fmt, str::FromStr};

/// domain:entity_type:provider:entity_id。旧3区分の参照は local として読む。
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct TypedRef {
    domain: String,
    entity_type: String,
    provider: String,
    entity_id: String,
}
impl TypedRef {
    pub fn new(domain: &str, entity_type: &str, provider: &str, id: &str) -> Result<Self> {
        let domain = domain.trim().to_ascii_lowercase();
        let entity_type = entity_type.trim().to_ascii_lowercase();
        let provider = provider.trim().to_ascii_lowercase();
        ensure!(
            matches!(
                domain.as_str(),
                "agent-taskstate"
                    | "memx"
                    | "tracker"
                    | "agent-gatefield"
                    | "agent-state-gate"
                    | "shipyard-cp"
                    | "workflow-cookbook"
            ),
            "不明な domain"
        );
        ensure!(
            matches!(
                entity_type.as_str(),
                "task"
                    | "run"
                    | "decision"
                    | "context_bundle"
                    | "read_receipt"
                    | "assessment"
                    | "audit_packet"
                    | "evidence"
                    | "artifact"
                    | "doc"
                    | "chunk"
                    | "ack"
                    | "contract"
                    | "issue"
                    | "stage"
                    | "human_queue_item"
            ),
            "不明な entity_type"
        );
        ensure!(
            matches!(
                provider.as_str(),
                "local" | "jira" | "github" | "linear" | "http"
            ),
            "不明な provider"
        );
        ensure!(!id.trim().is_empty(), "entity_id が空です");
        Ok(Self {
            domain,
            entity_type,
            provider,
            entity_id: id.into(),
        })
    }
}
impl FromStr for TypedRef {
    type Err = anyhow::Error;
    fn from_str(s: &str) -> Result<Self> {
        let mut parts = s.splitn(4, ':');
        match (parts.next(), parts.next(), parts.next(), parts.next()) {
            (Some(d), Some(e), Some(p), Some(id)) => Self::new(d, e, p, id),
            (Some(d), Some(e), Some(id), None) => Self::new(d, e, "local", id),
            _ => bail!("参照には3または4区分が必要です"),
        }
    }
}
impl fmt::Display for TypedRef {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}:{}:{}:{}",
            self.domain, self.entity_type, self.provider, self.entity_id
        )
    }
}
