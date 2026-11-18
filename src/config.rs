use anyhow::{Context, Result, bail, ensure};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{collections::BTreeMap, env, fs, path::Path};

pub const AXES: [&str; 6] = [
    "gatefield",
    "taskstate",
    "protocols",
    "memx",
    "shipyard",
    "workflow",
];

#[derive(Clone, Copy, PartialEq, Eq, serde::Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Profile {
    LocalAdvisory,
    CiContract,
    StagingEnforce,
    ProductionShadow,
    ProductionEnforce,
}
impl Profile {
    pub fn name(self) -> &'static str {
        match self {
            Self::LocalAdvisory => "local_advisory",
            Self::CiContract => "ci_contract",
            Self::StagingEnforce => "staging_enforce",
            Self::ProductionShadow => "production_shadow",
            Self::ProductionEnforce => "production_enforce",
        }
    }
    pub fn local(self) -> bool {
        matches!(self, Self::LocalAdvisory | Self::CiContract)
    }
    pub fn production(self) -> bool {
        matches!(self, Self::ProductionShadow | Self::ProductionEnforce)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub version: String,
    pub runtime_profile: Profile,
    pub database: DatabaseConfig,
    pub oidc: Oidc,
    pub adapters: BTreeMap<String, Adapter>,
    #[serde(default)]
    pub verdict: BTreeMap<String, Value>,
    #[serde(default)]
    pub human_queue: BTreeMap<String, Value>,
    #[serde(default)]
    pub audit: BTreeMap<String, Value>,
    #[serde(default)]
    pub security: BTreeMap<String, Value>,
    #[serde(default)]
    pub mcp: BTreeMap<String, Value>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DatabaseConfig {
    pub url: String,
    #[serde(default)]
    pub echo: bool,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Oidc {
    pub enabled: bool,
    pub issuer: Option<String>,
    pub audience: Option<String>,
    pub jwks_url: Option<String>,
    pub algorithms: Vec<String>,
    pub subject_claim: String,
    pub tenant_claim: String,
    pub roles_claim: String,
    pub jwks_cache_seconds: u64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Adapter {
    pub enabled: bool,
    pub timeout_ms: u64,
    pub failure_policy: String,
    pub endpoint: Option<String>,
    pub api_key: Option<String>,
    pub jwt_token: Option<String>,
    pub command: Option<String>,
    pub working_dir: Option<String>,
    pub cookbook_path: Option<String>,
    pub schemas_path: Option<String>,
    pub use_http: Option<bool>,
}
fn defaults() -> Value {
    let mut v = json!({"version":"0.5.0","runtime_profile":"local_advisory",
        "database":{"url":"sqlite:///agent-state-gate.db","echo":false},
        "oidc":{"enabled":false,"algorithms":["RS256"],"subject_claim":"sub","tenant_claim":"tenant_id","roles_claim":"roles","jwks_cache_seconds":300},
        "adapters":{}});
    for (name, timeout, policy, mut extra) in [
        (
            "gatefield",
            5000,
            "fail-closed",
            json!({"endpoint":"http://localhost:8080"}),
        ),
        (
            "shipyard",
            5000,
            "fail-closed",
            json!({"endpoint":"http://localhost:3000"}),
        ),
        ("memx", 3000, "stale-blocked", json!({"use_http":true})),
        (
            "taskstate",
            3000,
            "fail-closed",
            json!({"command":"agent-taskstate"}),
        ),
        (
            "workflow",
            2000,
            "needs-approval",
            json!({"cookbook_path":"../workflow-cookbook"}),
        ),
        (
            "protocols",
            5000,
            "needs-approval",
            json!({"schemas_path":"../agent-protocols/schemas"}),
        ),
    ] {
        extra["enabled"] = json!(true);
        extra["timeout_ms"] = json!(timeout);
        extra["failure_policy"] = json!(policy);
        v["adapters"][name] = extra;
    }
    v
}
fn expand(v: &mut Value) -> Result<()> {
    match v {
        Value::String(s) => {
            if let Some(expr) = s.strip_prefix("${").and_then(|s| s.strip_suffix('}')) {
                let (name, default) = expr
                    .split_once(":-")
                    .map_or((expr, None), |(k, d)| (k, Some(d)));
                if !name.is_empty()
                    && name.bytes().enumerate().all(|(i, b)| {
                        b == b'_' || b.is_ascii_alphabetic() || (i > 0 && b.is_ascii_digit())
                    })
                {
                    *s = env::var(name)
                        .ok()
                        .or_else(|| default.map(str::to_owned))
                        .with_context(|| format!("環境変数 {name} が必要です"))?;
                }
            }
        }
        Value::Array(a) => {
            for item in a {
                expand(item)?;
            }
        }
        Value::Object(m) => {
            for item in m.values_mut() {
                expand(item)?;
            }
        }
        _ => (),
    }
    Ok(())
}
fn merge(base: &mut Value, custom: Value) {
    if let (Some(b), Some(c)) = (base.as_object_mut(), custom.as_object()) {
        for (k, v) in c {
            merge(b.entry(k).or_insert(Value::Null), v.clone());
        }
    } else {
        *base = custom;
    }
}
impl Config {
    pub fn load(path: &Path) -> Result<Self> {
        Self::from_yaml(&fs::read_to_string(path).context("設定ファイルを読み込めません")?)
    }
    pub fn from_yaml(input: &str) -> Result<Self> {
        let mut raw: Value = serde_yaml::from_str(input)?;
        if raw.is_null() {
            raw = json!({})
        }
        expand(&mut raw)?;
        let root = raw
            .as_object_mut()
            .context("設定にはマッピングが必要です")?;
        if let Some(old) = root.remove("environment")
            && !root.contains_key("runtime_profile")
        {
            root.insert(
                "runtime_profile".into(),
                json!(match old.as_str() {
                    Some("local") => "local_advisory",
                    Some("ci") => "ci_contract",
                    Some("staging") => "staging_enforce",
                    Some("production") => "production_enforce",
                    _ => bail!("不明な environment"),
                }),
            );
        }
        if let Some(adapters) = root.get_mut("adapters") {
            for (name, item) in adapters
                .as_object_mut()
                .context("adapters の形式が不正です")?
            {
                ensure!(AXES.contains(&name.as_str()), "不明な adapter {name}");
                let obj = item
                    .as_object_mut()
                    .context("adapter 設定の形式が不正です")?;
                for (old, new) in [
                    ("base_url", "endpoint"),
                    ("cli_path", "command"),
                    ("schemas_dir", "schemas_path"),
                    ("schema_path", "schemas_path"),
                    ("docs_path", "cookbook_path"),
                    ("timeout_seconds", "timeout_ms"),
                ] {
                    if let Some(mut v) = obj.remove(old) {
                        ensure!(!obj.contains_key(new), "{old} と {new} が重複しています");
                        if old == "timeout_seconds" {
                            v = json!(
                                v.as_u64()
                                    .and_then(|x| x.checked_mul(1000))
                                    .context("timeout_seconds が不正です")?
                            );
                        }
                        obj.insert(new.into(), v);
                    }
                }
                for key in obj.keys() {
                    let valid = match key.as_str() {
                        "enabled" | "timeout_ms" | "failure_policy" => true,
                        "endpoint" | "api_key" => {
                            matches!(name.as_str(), "gatefield" | "shipyard" | "memx")
                        }
                        "command" => matches!(name.as_str(), "taskstate" | "memx"),
                        "working_dir" => name == "taskstate",
                        "schemas_path" => name == "protocols",
                        "cookbook_path" => name == "workflow",
                        "jwt_token" => name == "shipyard",
                        "use_http" => name == "memx",
                        _ => false,
                    };
                    ensure!(valid, "{name} の不明な設定 {key}");
                }
            }
        }
        let mut data = defaults();
        merge(&mut data, raw);
        let cfg: Self = serde_json::from_value(data)?;
        cfg.validate()?;
        Ok(cfg)
    }
    pub(crate) fn validate(&self) -> Result<()> {
        let cfg = self;
        ensure!(
            cfg.adapters.len() == AXES.len() && AXES.iter().all(|a| cfg.adapters.contains_key(*a)),
            "adapter 一覧が不完全です"
        );
        for adapter in cfg.adapters.values() {
            ensure!(
                (1..=300000).contains(&adapter.timeout_ms),
                "timeout_ms が範囲外です"
            );
            ensure!(
                matches!(
                    adapter.failure_policy.as_str(),
                    "fail-open" | "fail-closed" | "needs-approval" | "stale-blocked"
                ),
                "failure_policy が不正です"
            );
        }
        ensure!(
            (1..=86400).contains(&cfg.oidc.jwks_cache_seconds),
            "JWKS の有効期間が範囲外です"
        );
        if !cfg.runtime_profile.local() {
            ensure!(
                cfg.database.url.starts_with("postgresql://")
                    || cfg.database.url.starts_with("postgresql+psycopg://"),
                "このプロファイルには PostgreSQL が必要です"
            );
            ensure!(
                cfg.oidc.enabled
                    && cfg.oidc.issuer.as_deref().is_some_and(|s| !s.is_empty())
                    && cfg.oidc.audience.as_deref().is_some_and(|s| !s.is_empty()),
                "OIDC の設定が必要です"
            );
            ensure!(
                cfg.adapters.values().all(|a| a.enabled),
                "すべての adapter を有効にしてください"
            );
        }
        Ok(())
    }
}
