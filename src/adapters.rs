use crate::config::{Adapter, Config};
use anyhow::{Context, Result, bail, ensure};
use reqwest::{
    Url,
    blocking::{Client, RequestBuilder, Response},
};
use serde_json::{Value, json};
use std::{
    env, fs,
    io::{Seek, SeekFrom},
    path::Path,
    process::{Command, Stdio},
    time::Duration,
};
use wait_timeout::ChildExt;

fn run(program: &str, args: &[&str], dir: Option<&Path>, timeout: u64) -> Result<std::fs::File> {
    let mut file = tempfile::tempfile()?;
    let mut command = Command::new(program);
    if let Some(dir) = dir {
        command.current_dir(dir);
    }
    let mut child = command
        .args(args)
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .stdout(file.try_clone()?)
        .spawn()?;
    if let Some(status) = child.wait_timeout(Duration::from_millis(timeout))? {
        ensure!(status.success(), "adapter CLI が失敗しました");
    } else {
        let _ = child.kill();
        child.wait()?;
        bail!("adapter CLI がタイムアウトしました")
    }
    file.seek(SeekFrom::Start(0))?;
    Ok(file)
}
fn object(v: Value) -> Result<Value> {
    ensure!(
        v.is_object(),
        "adapter の応答には JSON オブジェクトが必要です"
    );
    Ok(v)
}
pub(crate) struct Adapters<'a> {
    pub cfg: &'a Config,
    pub client: &'a Client,
}
impl Adapters<'_> {
    fn get(&self, name: &str) -> Result<&Adapter> {
        self.cfg
            .adapters
            .get(name)
            .filter(|a| a.enabled)
            .context("adapter が無効です")
    }
    fn request(&self, name: &str, segments: &[&str], post: bool) -> Result<RequestBuilder> {
        let a = self.get(name)?;
        let mut url = Url::parse(a.endpoint.as_deref().context("endpoint が必要です")?)?;
        url.path_segments_mut()
            .map_err(|_| anyhow::anyhow!("endpoint の形式が不正です"))?
            .pop_if_empty()
            .extend(segments.iter().copied());
        let mut r = if post {
            self.client.post(url)
        } else {
            self.client.get(url)
        };
        if name == "gatefield" {
            if let Some(key) = env::var("AGENT_GATEFIELD_API_KEY")
                .ok()
                .or_else(|| a.api_key.clone())
            {
                r = r.header("X-API-Key", key)
            }
        } else if name == "memx"
            && let Some(key) = &a.api_key
        {
            r = r.header("X-API-Key", key)
        } else if name == "shipyard"
            && let Some(token) = &a.jwt_token
        {
            r = r.bearer_auth(token)
        }
        Ok(r.timeout(Duration::from_millis(a.timeout_ms)))
    }
    fn json(&self, r: RequestBuilder) -> Result<Value> {
        object(r.send()?.error_for_status()?.json()?)
    }
    pub fn taskstate(&self, kind: &str, flag: &str, id: &str) -> Result<Value> {
        let a = self.get("taskstate")?;
        object(serde_json::from_reader(run(
            a.command.as_deref().context("command が必要です")?,
            &[kind, "show", flag, id],
            a.working_dir.as_deref().map(Path::new),
            a.timeout_ms,
        )?)?)
    }
    fn memx_http(a: &Adapter) -> bool {
        a.use_http.unwrap_or(true) && a.endpoint.as_deref().is_some_and(|s| !s.is_empty())
    }
    fn memx_cli(&self, args: &[&str]) -> Result<Value> {
        let a = self.get("memx")?;
        object(serde_json::from_reader(run(
            a.command.as_deref().context("memx command が必要です")?,
            args,
            None,
            a.timeout_ms,
        )?)?)
    }
    pub fn stale(&self, task: &str) -> Result<Value> {
        let v = if Self::memx_http(self.get("memx")?) {
            self.json(
                self.request("memx", &["v1", "docs", "stale-check"], false)?
                    .query(&[("task_id", task)]),
            )?
        } else {
            self.memx_cli(&["docs:stale-check", "--task", task])?
        };
        ensure!(v["fresh"].is_boolean(), "fresh が不正です");
        Ok(v)
    }
    pub fn recall(
        &self,
        task: &str,
        action: &str,
        feature: Option<&str>,
        paths: &[String],
    ) -> Result<Value> {
        if Self::memx_http(self.get("memx")?) {
            let mut data = json!({"task_id":task,"action":action});
            if let Some(f) = feature {
                data["feature"] = json!(f)
            }
            if !paths.is_empty() {
                data["touched_paths"] = json!(paths)
            }
            self.json(
                self.request("memx", &["v1", "docs", "resolve"], true)?
                    .json(&data),
            )
        } else {
            let mut args = vec!["docs:resolve", "--task", task, "--action", action];
            if let Some(f) = feature {
                args.extend(["--feature", f]);
            }
            let encoded = serde_json::to_string(paths)?;
            if !paths.is_empty() {
                args.extend(["--paths", &encoded]);
            }
            self.memx_cli(&args)
        }
    }
    pub fn workflow(&self, task: &str, stage: Option<&str>) -> Result<Value> {
        let a = self.get("workflow")?;
        let root = Path::new(a.cookbook_path.as_deref().unwrap_or("../workflow-cookbook"));
        let script = "tools/ci/generate_evidence_report.py";
        if root.join(script).is_file() {
            let mut args = vec![script, "--task", task];
            if let Some(s) = stage {
                args.extend(["--stage", s])
            }
            if let Ok(v) = run("python", &args, Some(root), a.timeout_ms)
                .and_then(|f| object(serde_json::from_reader(f)?))
            {
                return Ok(v);
            }
        }
        let data: Value =
            serde_json::from_reader(fs::File::open(root.join(".workflow-cache/evidence.json"))?)?;
        ensure!(data.is_object(), "証跡キャッシュの形式が不正です");
        let mut result = json!({"acceptances":[],"evidences":[],"unlinked_evidences":[]});
        for k in ["acceptances", "unlinked_evidences"] {
            if let Some(v) = data.get(k) {
                result[k] = v.clone()
            }
        }
        if let Some(rows) = data.get("evidences") {
            result["evidences"] = json!(
                rows.as_array()
                    .context("evidences の形式が不正です")?
                    .iter()
                    .filter(|v| v["task_id"] == task)
                    .collect::<Vec<_>>()
            );
        }
        Ok(result)
    }
    pub fn packet(&self, input: &Value) -> Result<Value> {
        self.json(
            self.request("gatefield", &["v1", "evaluate"], true)?
                .json(input),
        )
    }
    pub fn stage(&self, run: &str) -> Result<Value> {
        self.json(self.request("shipyard", &["v1", "tasks", run], false)?)
    }
    fn http_health(&self, name: &str) -> Result<Response> {
        Ok(self
            .request(name, &["v1", "health"], false)?
            .timeout(Duration::from_secs(2))
            .send()?)
    }
    pub fn health(&self, name: &str) -> Result<(bool, Value)> {
        let a = self.get(name)?;
        let mut details = json!({});
        let healthy = match name {
            "gatefield" if self.cfg.runtime_profile.production() => {
                let r = self.http_health(name)?;
                let success = r.status() == 200;
                let v: Value = r.json()?;
                let backend = v.get("backend").cloned().unwrap_or(json!({}));
                let pg = [&v, &backend]
                    .iter()
                    .any(|v| v["pgvector_ready"] == true || v["pgvector"] == true);
                details = json!({"healthy":success,"pgvector_ready":pg,"backend":backend});
                success && pg
            }
            "protocols" => Path::new(
                a.schemas_path
                    .as_deref()
                    .unwrap_or("../agent-protocols/schemas"),
            )
            .is_dir(),
            "workflow" => Path::new(a.cookbook_path.as_deref().unwrap_or("../workflow-cookbook"))
                .join("docs/acceptance")
                .is_dir(),
            "taskstate" => run(
                a.command.as_deref().context("command が必要です")?,
                &["task", "list", "--limit", "1"],
                a.working_dir.as_deref().map(Path::new),
                2000,
            )
            .is_ok(),
            "memx" if !Self::memx_http(a) => run(
                a.command.as_deref().context("command が必要です")?,
                &["--help"],
                None,
                2000,
            )
            .is_ok(),
            _ => self.http_health(name)?.status() == 200,
        };
        Ok((healthy, details))
    }
}
