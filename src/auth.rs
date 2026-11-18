use crate::config::Config;
use anyhow::{Context, Result, ensure};
use jsonwebtoken::{DecodingKey, Validation, decode, decode_header, jwk::JwkSet};
use reqwest::blocking::Client;
use serde_json::{Value, json};
use std::{collections::BTreeSet, time::Duration};
use uuid::Uuid;

pub struct Identity {
    pub(crate) tenant: String,
    pub(crate) subject: String,
    pub(crate) roles: BTreeSet<String>,
    pub(crate) trace: String,
    expires_at: Option<i64>,
}
impl Identity {
    pub(crate) fn require_current(&self) -> Result<()> {
        ensure!(
            self.expires_at
                .is_none_or(|expires| chrono::Utc::now().timestamp() < expires),
            "OIDC トークンの有効期限が切れています"
        );
        Ok(())
    }
    pub(crate) fn claims(&self) -> Value {
        json!({"tenant_id":self.tenant,"subject":self.subject,"roles":self.roles})
    }
}
pub enum Credentials<'a> {
    Local {
        tenant: &'a str,
        subject: &'a str,
        roles: &'a str,
    },
    Bearer(&'a str),
}
fn roles(input: &str) -> BTreeSet<String> {
    input
        .split(|c: char| c == ',' || c.is_whitespace())
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .collect()
}
pub(crate) fn authenticate(
    cfg: &Config,
    credentials: Credentials<'_>,
    client: &Client,
) -> Result<Identity> {
    let oidc = &cfg.oidc;
    let (tenant, subject, roles, expires_at) = match credentials {
        Credentials::Local {
            tenant,
            subject,
            roles: r,
        } => {
            ensure!(
                cfg.runtime_profile.local() && !oidc.enabled,
                "OIDC 認証が必要です"
            );
            (tenant.into(), subject.into(), roles(r), None)
        }
        Credentials::Bearer(token) => {
            ensure!(oidc.enabled && !token.is_empty(), "OIDC トークンが必要です");
            let issuer = oidc.issuer.as_deref().context("issuer が必要です")?;
            let audience = oidc.audience.as_deref().context("audience が必要です")?;
            let header = decode_header(token)?;
            let algs = oidc
                .algorithms
                .iter()
                .map(|s| s.parse())
                .collect::<Result<Vec<_>, _>>()?;
            ensure!(algs.contains(&header.alg), "未許可の署名アルゴリズムです");
            let fetch = |url: &str| -> Result<Value> {
                Ok(client
                    .get(url)
                    .timeout(Duration::from_secs(5))
                    .send()?
                    .error_for_status()?
                    .json()?)
            };
            let url = match &oidc.jwks_url {
                Some(s) => s.clone(),
                None => fetch(&format!(
                    "{}/.well-known/openid-configuration",
                    issuer.trim_end_matches('/')
                ))?["jwks_uri"]
                    .as_str()
                    .context("jwks_uri が必要です")?
                    .to_owned(),
            };
            let keys: JwkSet = serde_json::from_value(fetch(&url)?)?;
            let key = keys
                .find(header.kid.as_deref().context("kid が必要です")?)
                .context("署名鍵が見つかりません")?;
            let mut validation = Validation::new(header.alg);
            validation.set_issuer(&[issuer]);
            validation.set_audience(&[audience]);
            validation.validate_nbf = true;
            validation.leeway = 0;
            validation.set_required_spec_claims(&["exp", "iss", "aud"]);
            let claims = decode::<Value>(token, &DecodingKey::from_jwk(key)?, &validation)?.claims;
            let r = &claims[&oidc.roles_claim];
            let r = if let Some(s) = r.as_str() {
                roles(s)
            } else {
                r.as_array()
                    .context("roles の形式が不正です")?
                    .iter()
                    .map(|v| Ok(v.as_str().context("roles には文字列が必要です")?.to_owned()))
                    .collect::<Result<_>>()?
            };
            (
                claims[&oidc.tenant_claim]
                    .as_str()
                    .context("tenant を特定できません")?
                    .into(),
                claims[&oidc.subject_claim]
                    .as_str()
                    .context("subject を特定できません")?
                    .into(),
                r,
                Some(claims["exp"].as_i64().context("exp が不正です")?),
            )
        }
    };
    let (tenant, subject): (String, String) = (tenant, subject);
    ensure!(
        !tenant.trim().is_empty() && !subject.trim().is_empty(),
        "tenant と subject が必要です"
    );
    Ok(Identity {
        tenant,
        subject,
        roles,
        expires_at,
        trace: Uuid::new_v4().simple().to_string(),
    })
}
