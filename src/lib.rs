mod adapters;
mod approval;
mod auth;
pub mod config;
mod db;
mod hash;
mod mcp;
mod observability;
pub mod policy;
mod service;
pub mod typed_ref;
pub use approval::ApprovalBinding;
pub use auth::Credentials;
pub use config::Config;
pub use service::{Evaluation, GateService, StateAssessment};
use uuid::Uuid;
fn id(prefix: &str) -> String {
    format!("{prefix}{}", Uuid::new_v4().simple())
}
