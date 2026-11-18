use crate::{hash::hash, id};
use anyhow::{Context, Result, bail, ensure};
use chrono::{DateTime, Duration, Utc};
use postgres::types::ToSql;
use rusqlite::{params_from_iter, types::Value as SqlValue};
use serde_json::{Value, json};

enum Backend {
    SQLite(rusqlite::Connection),
    Postgres(postgres::Client),
}
pub(crate) struct Store(Backend);
enum Tx<'a> {
    SQLite(rusqlite::Transaction<'a>),
    Postgres(postgres::Transaction<'a>),
}
use Param::{Bool, Json, Text, Time};
enum Param<'a> {
    Text(&'a str),
    Json(&'a Value),
    Time(DateTime<Utc>),
    Expiry(Option<DateTime<Utc>>),
    Bool(bool),
}
impl Param<'_> {
    fn pg(&self) -> &(dyn ToSql + Sync) {
        match self {
            Text(s) => s,
            Json(v) => v,
            Time(t) => t,
            Param::Expiry(t) => t,
            Bool(b) => b,
        }
    }
    fn sqlite(&self) -> SqlValue {
        match self {
            Text(s) => (*s).to_owned().into(),
            Json(v) => v.to_string().into(),
            Param::Expiry(t) => t
                .map(|t| t.format("%Y-%m-%d %H:%M:%S%.6f").to_string())
                .into(),
            Time(t) => t.format("%Y-%m-%d %H:%M:%S%.6f").to_string().into(),
            Bool(b) => i64::from(*b).into(),
        }
    }
}
impl Tx<'_> {
    fn exec(&mut self, sql: &str, p: &[Param]) -> Result<u64> {
        Ok(match self {
            Self::SQLite(t) => t.execute(
                &sql.replace('$', "?"),
                params_from_iter(p.iter().map(Param::sqlite)),
            )? as u64,
            Self::Postgres(t) => t.execute(sql, &p.iter().map(Param::pg).collect::<Vec<_>>())?,
        })
    }
    fn rows(&mut self, sql: &str, p: &[Param]) -> Result<Vec<Vec<String>>> {
        match self {
            Self::SQLite(t) => {
                let mut stmt = t.prepare(&sql.replace('$', "?"))?;
                let cols = stmt.column_count();
                Ok(stmt
                    .query_map(params_from_iter(p.iter().map(Param::sqlite)), |r| {
                        (0..cols).map(|i| r.get(i)).collect()
                    })?
                    .collect::<rusqlite::Result<Vec<_>>>()?)
            }
            Self::Postgres(t) => Ok(t
                .query(sql, &p.iter().map(Param::pg).collect::<Vec<_>>())?
                .iter()
                .map(|row| (0..row.len()).map(|i| row.try_get(i)).collect())
                .collect::<Result<_, postgres::Error>>()?),
        }
    }
    fn commit(self) -> Result<()> {
        match self {
            Self::Postgres(t) => t.commit()?,
            Self::SQLite(t) => t.commit()?,
        }
        Ok(())
    }
}

impl Store {
    pub fn open(url: &str, initialize: bool) -> Result<Self> {
        let schema = include_str!("schema.sql");
        let path = match url {
            "sqlite://" | "sqlite:///" => Some(":memory:"),
            _ => url.strip_prefix("sqlite:///"),
        };
        if let Some(path) = path {
            ensure!(initialize, "このモードでは PostgreSQL が必要です");
            let c = rusqlite::Connection::open(path)?;
            c.busy_timeout(std::time::Duration::from_secs(5))?;
            c.execute_batch(&format!("BEGIN;{schema}COMMIT;"))?;
            return Ok(Self(Backend::SQLite(c)));
        }
        ensure!(
            url.starts_with("postgresql://") || url.starts_with("postgresql+psycopg://"),
            "未対応のデータベースです"
        );
        let tls = postgres_native_tls::MakeTlsConnector::new(native_tls::TlsConnector::new()?);
        let mut c = postgres::Client::connect(
            &url.replacen("postgresql+psycopg://", "postgresql://", 1),
            tls,
        )
        .context("PostgreSQL に接続できません")?;
        if initialize {
            let mut tx = c.transaction()?;
            tx.batch_execute(schema)?;
            tx.commit()?;
        }
        Ok(Self(Backend::Postgres(c)))
    }
    fn transaction<T>(&mut self, write: bool, f: impl FnOnce(&mut Tx) -> Result<T>) -> Result<T> {
        let mut tx = match &mut self.0 {
            Backend::Postgres(c) => Tx::Postgres(c.transaction()?),
            Backend::SQLite(c) => Tx::SQLite(c.transaction_with_behavior(if write {
                rusqlite::TransactionBehavior::Immediate
            } else {
                rusqlite::TransactionBehavior::Deferred
            })?),
        };
        let out = f(&mut tx)?;
        tx.commit()?;
        Ok(out)
    }
    pub fn save_binding(&mut self, tenant: &str, binding: &crate::ApprovalBinding) -> Result<()> {
        let diff = crate::service::valid_hash(&binding.diff_hash)?;
        let context = crate::service::valid_hash(&binding.context_hash)?;
        ensure!(
            !binding.approval_id.is_empty() && !binding.policy_version.is_empty(),
            "approval_id と policy_version が必要です"
        );
        self.transaction(true, |tx| {
            tx.exec(
                UPSERT_BINDING,
                &[
                    Text(&binding.approval_id),
                    Text(tenant),
                    Text(&diff),
                    Text(&context),
                    Text(&binding.policy_version),
                    Json(&json!(binding.approved_roles)),
                    Param::Expiry(binding.expires_at),
                    Time(Utc::now()),
                ],
            )?;
            Ok(())
        })
    }
    pub fn approval_current(
        &mut self,
        tenant: &str,
        approval_id: &str,
        diff: &str,
        context: &str,
        policy: &str,
        now: DateTime<Utc>,
    ) -> Result<bool> {
        self.transaction(false, |tx| {
            Ok(!tx
                .rows(
                    CURRENT_BINDING,
                    &[
                        Text(tenant),
                        Text(approval_id),
                        Text(diff),
                        Text(context),
                        Text(policy),
                        Time(now),
                    ],
                )?
                .is_empty())
        })
    }
    pub fn current_approval_roles(
        &mut self,
        tenant: &str,
        diff: &str,
        context: &str,
        policy: &str,
    ) -> Result<std::collections::BTreeSet<String>> {
        self.transaction(false, |tx| {
            let mut roles = std::collections::BTreeSet::new();
            for row in tx.rows(
                CURRENT_APPROVAL_ROLES,
                &[
                    Text(tenant),
                    Text(diff),
                    Text(context),
                    Text(policy),
                    Time(Utc::now()),
                ],
            )? {
                roles.extend(serde_json::from_str::<Vec<String>>(&row[0])?);
            }
            Ok(roles)
        })
    }
    pub fn healthy(&mut self) -> bool {
        self.transaction(false, |tx| tx.rows("SELECT CAST(1 AS TEXT)", &[]))
            .is_ok()
    }
    pub fn save(
        &mut self,
        a: &Value,
        audit: &Value,
        snapshot: &Value,
        queue: Option<&Value>,
    ) -> Result<()> {
        let get = |k: &str| a[k].as_str().context("Assessment の必須項目がありません");
        let tenant = Text(get("tenant_id")?);
        let run = Text(get("run_id")?);
        let assessment = Text(get("assessment_id")?);
        let now = Utc::now();
        self.transaction(true, |tx| {
            tx.exec(
                INSERT_ASSESSMENT,
                &[
                    Text(get("assessment_id")?),
                    Text(get("tenant_id")?),
                    Text(get("task_id")?),
                    Text(get("run_id")?),
                    Text(get("stage")?),
                    Text(get("final_verdict")?),
                    Text(get("context_hash")?),
                    Text(get("diff_hash")?),
                    Text(get("policy_version")?),
                    Text(get("threshold_version")?),
                    Bool(a["degraded"] == true),
                    Json(a),
                    Time(now),
                ],
            )?;
            tx.exec(
                INSERT_AUDIT,
                &[
                    Text(audit["packet_id"].as_str().context("packet_id")?),
                    Text(get("tenant_id")?),
                    Text(get("run_id")?),
                    Text(get("assessment_id")?),
                    Text(if a["final_verdict"] == "allow" {
                        "ops"
                    } else {
                        "audit"
                    }),
                    Json(audit),
                    Time(now),
                ],
            )?;
            tx.exec(
                INSERT_SNAPSHOT,
                &[
                    Text(&id("SNP-")),
                    tenant,
                    run,
                    assessment,
                    Text(&hash(snapshot)),
                    Json(snapshot),
                    Time(now),
                ],
            )?;
            if let Some(q) = queue {
                tx.exec(
                    INSERT_QUEUE_ITEM,
                    &[
                        Text(q["item_id"].as_str().context("item_id")?),
                        Text(get("tenant_id")?),
                        Text(get("run_id")?),
                        Text(get("task_id")?),
                        Text(get("assessment_id")?),
                        Text(q["severity"].as_str().context("severity")?),
                        Text(q["required_role"].as_str().context("required_role")?),
                        Json(q),
                        Time(now),
                    ],
                )?;
            }
            Ok(())
        })
    }
    pub fn queue(
        &mut self,
        tenant: &str,
        status: Option<&str>,
        role: Option<&str>,
    ) -> Result<Vec<Value>> {
        self.payloads(
            LIST_QUEUE,
            &[
                Text(tenant),
                Text(status.unwrap_or("")),
                Text(role.unwrap_or("")),
            ],
        )
    }
    pub fn audit(&mut self, tenant: &str, run: Option<&str>) -> Result<Vec<Value>> {
        self.payloads(LIST_AUDIT, &[Text(tenant), Text(run.unwrap_or(""))])
    }
    fn payloads(&mut self, sql: &str, p: &[Param]) -> Result<Vec<Value>> {
        self.transaction(false, |tx| {
            tx.rows(sql, p)?
                .into_iter()
                .map(|r| Ok(serde_json::from_str(&r[0])?))
                .collect()
        })
    }
    pub fn update_queue(
        &mut self,
        tenant: &str,
        item: &str,
        reviewer: &str,
        resolution: Option<(&str, &str)>,
    ) -> Result<Value> {
        self.transaction(true, |tx| {
            let sql = QUEUE_STATE;
            let sql = if matches!(tx, Tx::Postgres(_)) {
                format!("{sql} FOR UPDATE")
            } else {
                sql.into()
            };
            let row = tx
                .rows(&sql, &[Text(tenant), Text(item)])?
                .pop()
                .context("キュー項目がありません")?;
            let mut payload: Value = serde_json::from_str(&row[0])?;
            let now = Utc::now();
            let status = match resolution {
                Some((result, comment)) if row[1] == "taken" && row[2] == reviewer => {
                    payload["resolution"] = json!(result);
                    payload["resolution_comment"] = json!(comment);
                    payload["resolved_at"] = json!(now);
                    "resolved"
                }
                None if matches!(row[1].as_str(), "pending" | "escalated") => {
                    payload["assigned_to"] = json!(reviewer);
                    payload["taken_at"] = json!(now);
                    "taken"
                }
                _ => bail!("現在の状態または担当者では操作できません"),
            };
            payload["status"] = json!(status);
            payload["version"] = json!(row[3].parse::<i64>()? + 1);
            tx.exec(
                UPDATE_QUEUE,
                &[
                    Text(status),
                    Text(reviewer),
                    Json(&payload),
                    Time(now),
                    Text(tenant),
                    Text(item),
                ],
            )?;
            Ok(payload)
        })
    }
    pub fn snapshot(
        &mut self,
        tenant: &str,
        run: &str,
        as_of: Option<DateTime<Utc>>,
    ) -> Result<Option<(Value, String, String)>> {
        let mut sql = String::from(FIND_SNAPSHOT);
        let mut p = vec![Text(tenant), Text(run)];
        if let Some(t) = as_of {
            sql.push_str(" AND s.created_at<=$3");
            p.push(Time(t))
        }
        sql.push_str(" ORDER BY s.created_at DESC,s.snapshot_id DESC LIMIT 1");
        self.transaction(false, |tx| {
            tx.rows(&sql, &p)?
                .pop()
                .map(|r| Ok((serde_json::from_str(&r[0])?, r[1].clone(), r[2].clone())))
                .transpose()
        })
    }
    pub fn purge(&mut self, tenant: &str, subject: &str, reason: &str) -> Result<Value> {
        self.transaction(true, |tx| {
            let now = Utc::now();
            let mut counts = json!({});
            let mut cutoffs = json!({});
            for (class, days) in [("audit", 365), ("ops", 90), ("pii-sensitive", 30)] {
                let t = now - Duration::days(days);
                cutoffs[class] = json!(t);
                counts[class] =
                    json!(tx.exec(DELETE_EXPIRED, &[Text(tenant), Text(class), Time(t)])?);
            }
            let manifest = id("PURGE-");
            tx.exec(
                INSERT_MANIFEST,
                &[
                    Text(&manifest),
                    Text(tenant),
                    Text(subject),
                    Text(reason),
                    Json(&cutoffs),
                    Json(&counts),
                    Time(now),
                ],
            )?;
            Ok(json!({"manifest_id":manifest,"deleted_by_class":counts}))
        })
    }
}

const UPSERT_BINDING: &str = "
    INSERT INTO approval_bindings(approval_id, tenant_id, diff_hash, context_hash,
        policy_version, approved_roles, expires_at, created_at)
    VALUES($1, $2, $3, $4, $5, $6, $7, $8)
    ON CONFLICT(approval_id, tenant_id)
    DO UPDATE SET diff_hash=excluded.diff_hash, context_hash=excluded.context_hash,
        policy_version=excluded.policy_version,  approved_roles=excluded.approved_roles,
        expires_at=excluded.expires_at, created_at=excluded.created_at";

const CURRENT_BINDING: &str = "
    SELECT approval_id
    FROM approval_bindings
    WHERE tenant_id=$1 AND approval_id=$2 AND diff_hash=$3 AND context_hash=$4 AND
        policy_version=$5 AND (expires_at IS NULL OR expires_at>$6)";

const CURRENT_APPROVAL_ROLES: &str = "
    SELECT CAST(approved_roles AS TEXT) FROM approval_bindings
    WHERE tenant_id=$1 AND diff_hash=$2 AND context_hash=$3 AND policy_version=$4
      AND (expires_at IS NULL OR expires_at>$5)";

const INSERT_ASSESSMENT: &str = "
    INSERT INTO assessments(assessment_id, tenant_id, task_id, run_id, stage, final_verdict,
        context_hash, diff_hash, policy_version, threshold_version, degraded, payload,
        created_at)
    VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)";

const INSERT_AUDIT: &str = "
    INSERT INTO audit_packets(packet_id, tenant_id, run_id, assessment_id, retention_class,
        payload, created_at)
    VALUES($1, $2, $3, $4, $5, $6, $7)";

const INSERT_SNAPSHOT: &str = "
    INSERT INTO attested_snapshots(snapshot_id, tenant_id, run_id, assessment_id,
        attestation_hash, payload, created_at)
    VALUES($1, $2, $3, $4, $5, $6, $7)";

const INSERT_QUEUE_ITEM: &str = "
    INSERT INTO human_queue_items(item_id, tenant_id, run_id, task_id, assessment_id,
        severity, required_role, status, version, payload, created_at, updated_at)
    VALUES($1, $2, $3, $4, $5, $6, $7, 'pending', 1, $8, $9, $9)";

const LIST_QUEUE: &str = "
    SELECT CAST(payload AS TEXT)
    FROM human_queue_items
    WHERE tenant_id=$1 AND ($2='' OR status=$2) AND ($3='' OR required_role=$3)
    ORDER BY created_at";

const LIST_AUDIT: &str = "
    SELECT CAST(payload AS TEXT)
    FROM audit_packets
    WHERE tenant_id=$1 AND ($2='' OR run_id=$2)
    ORDER BY created_at";

const QUEUE_STATE: &str = "
    SELECT CAST(payload AS TEXT), status, COALESCE(assigned_to, ''), CAST(version AS TEXT)
    FROM human_queue_items
    WHERE tenant_id=$1 AND item_id=$2";

const UPDATE_QUEUE: &str = "
    UPDATE human_queue_items SET status=$1, assigned_to=$2, version=version+1, payload=$3,
        updated_at=$4
    WHERE tenant_id=$5 AND item_id=$6";

const FIND_SNAPSHOT: &str = "
    SELECT CAST(s.payload AS TEXT), s.attestation_hash, COALESCE(a.final_verdict, '')
    FROM attested_snapshots s
    LEFT JOIN assessments a ON a.tenant_id=s.tenant_id AND a.assessment_id=s.assessment_id
    WHERE s.tenant_id=$1 AND s.run_id=$2";

const DELETE_EXPIRED: &str = "
    DELETE
    FROM audit_packets
    WHERE tenant_id=$1 AND retention_class=$2 AND created_at<$3";

const INSERT_MANIFEST: &str = "
    INSERT INTO purge_manifests(manifest_id, tenant_id, executed_by, rationale,
        cutoff_by_class, deleted_by_class, created_at)
    VALUES($1, $2, $3, $4, $5, $6, $7)";
