use agent_state_gate::{Config, Credentials, Evaluation, GateService, StateAssessment};
use anyhow::Result;
use clap::{Args, Parser, Subcommand, ValueEnum};
use serde_json::{Value, json};
use std::{path::PathBuf, process::ExitCode};

#[derive(Parser)]
#[command(
    name = "agent-state-gate",
    about = "エージェント作業の判定・人間確認・監査",
    version,
    disable_version_flag = true
)]
struct Cli {
    #[arg(short='v',long,action=clap::ArgAction::Version)]
    version: (),
    #[arg(long, global = true, default_value = "config/gate_config.yaml")]
    config: PathBuf,
    #[arg(
        long,
        global = true,
        env = "AGENT_STATE_GATE_TOKEN",
        hide_env_values = true
    )]
    token: Option<String>,
    #[arg(long, global = true, default_value = "local")]
    tenant: String,
    #[arg(long, global = true, default_value = "cli-local")]
    subject: String,
    #[arg(long, global = true, default_value = "developer")]
    roles: String,
    #[arg(short = 'o', long, global = true, value_enum, default_value = "text")]
    output: Output,
    #[command(subcommand)]
    command: Command,
}
#[derive(ValueEnum, Clone, Copy)]
enum Output {
    Json,
    Text,
}
#[derive(Subcommand)]
enum Command {
    /// 統合判定または State-space Gate の評価
    Gate {
        #[command(subcommand)]
        command: Gate,
    },
    /// 人間の確認を待つ項目の管理
    Queue {
        #[command(subcommand)]
        command: Queue,
    },
    /// 保存した判定を再現
    Replay {
        #[arg(long)]
        run: String,
    },
    /// 監査パケットの一覧
    Audit {
        #[arg(long)]
        run: Option<String>,
    },
    /// 接続先とデータベースの稼働確認
    Health,
    /// 保存期間を過ぎた監査パケットの管理
    Maintenance {
        #[command(subcommand)]
        command: Maintenance,
    },
}
#[derive(Subcommand)]
enum Gate {
    Evaluate {
        #[arg(long)]
        task: String,
        #[arg(long)]
        run: String,
        #[arg(long, default_value = "edit_repo")]
        action_type: String,
        #[arg(long)]
        capability: Vec<String>,
        #[arg(long)]
        artifact_ref: Vec<String>,
        #[arg(long)]
        touched_path: Vec<String>,
        #[arg(long)]
        diff_hash: Option<String>,
    },
    StateAssess {
        #[arg(long)]
        run: String,
        #[arg(long)]
        stage: String,
        #[arg(long, required = true)]
        artifact_ref: Vec<String>,
        #[arg(long)]
        diff_hash: String,
        #[arg(long)]
        redacted_diff: String,
    },
}
#[derive(Args)]
struct Reviewer {
    #[arg(long)]
    item: String,
    #[arg(long)]
    reviewer: String,
}
#[derive(Subcommand)]
enum Queue {
    List {
        #[arg(long)]
        status: Option<String>,
        #[arg(long)]
        reviewer_role: Option<String>,
    },
    Take(Reviewer),
    Resolve {
        #[command(flatten)]
        owner: Reviewer,
        #[arg(long)]
        resolution: String,
        #[arg(long, default_value = "")]
        comment: String,
    },
}
#[derive(Subcommand)]
enum Maintenance {
    Purge {
        #[arg(long, default_value = "scheduled retention purge")]
        rationale: String,
    },
}

fn dispatch(cli: Cli) -> Result<(Value, u8)> {
    let cfg = Config::load(&cli.config)?;
    let auth = if cfg.oidc.enabled {
        Credentials::Bearer(cli.token.as_deref().unwrap_or(""))
    } else {
        Credentials::Local {
            tenant: &cli.tenant,
            subject: &cli.subject,
            roles: &cli.roles,
        }
    };
    let mut s = GateService::open(cfg, auth)?;
    Ok(match cli.command {
        Command::Gate {
            command:
                Gate::Evaluate {
                    task,
                    run,
                    action_type,
                    capability,
                    artifact_ref,
                    touched_path,
                    diff_hash,
                },
        } => {
            let r = s.evaluate(Evaluation {
                task_id: task,
                run_id: run,
                action: action_type,
                capabilities: capability,
                artifact_refs: artifact_ref,
                touched_paths: touched_path,
                diff_hash,
                risk_hints: Default::default(),
                semantic_evidence: None,
            })?;
            let code = match r["verdict"].as_str() {
                Some("allow") => 0,
                Some("deny") => 3,
                _ => 2,
            };
            (r, code)
        }
        Command::Gate {
            command:
                Gate::StateAssess {
                    run,
                    stage,
                    artifact_ref,
                    diff_hash,
                    redacted_diff,
                },
        } => {
            let r = s.assess(StateAssessment {
                artifact_refs: artifact_ref,
                diff_hash,
                redacted_diff: Some(redacted_diff),
                semantic_evidence: None,
                run_id: run,
                stage,
            })?;
            let code = if r["recommendation"] == "block" {
                3
            } else if r["human_queue_required"] == true {
                2
            } else {
                0
            };
            (r, code)
        }
        Command::Queue {
            command:
                Queue::List {
                    status,
                    reviewer_role,
                },
        } => {
            let items = s.queue(status.as_deref(), reviewer_role.as_deref())?;
            (json!({"items":items,"count":items.len()}), 0)
        }
        Command::Queue {
            command: Queue::Take(owner),
        } => (s.take(&owner.item, &owner.reviewer)?, 0),
        Command::Queue {
            command:
                Queue::Resolve {
                    owner,
                    resolution,
                    comment,
                },
        } => (
            s.resolve(&owner.item, &owner.reviewer, &resolution, &comment)?,
            0,
        ),
        Command::Audit { run } => (json!({"packets":s.audit(run.as_deref())?}), 0),
        Command::Replay { run } => {
            let r = s.replay(&run, None)?;
            let code = if r["reproducibility_verified"] == true {
                0
            } else {
                2
            };
            (r, code)
        }
        Command::Health => {
            let r = s.health()?;
            let code = u8::from(r["ready"] != true);
            (r, code)
        }
        Command::Maintenance {
            command: Maintenance::Purge { rationale },
        } => (s.purge(&rationale)?, 0),
    })
}
fn main() -> ExitCode {
    let cli = Cli::parse();
    let output = cli.output;
    match dispatch(cli) {
        Ok((v, code)) => {
            match output {
                Output::Json => println!("{}", serde_json::to_string_pretty(&v).unwrap()),
                Output::Text => {
                    if let Some(m) = v.as_object() {
                        for (k, v) in m {
                            if let Some(s) = v.as_str() {
                                println!("{k}: {s}")
                            } else {
                                println!("{k}: {v}")
                            }
                        }
                    }
                }
            }
            ExitCode::from(code)
        }
        Err(e) => {
            eprintln!(
                "{}",
                json!({"error":"RuntimeError","message":e.to_string()})
            );
            ExitCode::FAILURE
        }
    }
}
