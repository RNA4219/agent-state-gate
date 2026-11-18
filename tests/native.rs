use agent_state_gate::{
    ApprovalBinding, Config, Credentials, GateService,
    policy::{Packet, Verdict, transform},
    typed_ref::TypedRef,
};
use chrono::{Duration, Utc};
use serde_json::{Value, json};
use std::thread;

fn open(url: &str, tenant: &str, endpoint: Option<&str>) -> GateService {
    let mut cfg = json!({"database":{"url":url},"adapters":{}});
    for name in agent_state_gate::config::AXES {
        cfg["adapters"][name] = json!({"enabled":false});
    }
    if let Some(url) = endpoint {
        cfg["adapters"]["memx"] = json!({"enabled":true,"endpoint":url});
        cfg["adapters"]["gatefield"] = json!({"enabled":true,"endpoint":url});
    }
    GateService::open(
        Config::from_yaml(&cfg.to_string()).unwrap(),
        Credentials::Local {
            tenant,
            subject: "dev",
            roles: "developer",
        },
    )
    .unwrap()
}
fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/gatefield_decision_packet_v2.json")).unwrap()
}
#[test]
fn decision_boundaries() {
    use Verdict::*;
    let mut raw = fixture();
    let mut input = json!({"stale":{"fresh":true},"evidence":{"computed_strength":0.85},"approvals":{"required":[],"approved":[]}});
    let apply =
        |r: &Value, v: &Value, admin| transform(&Packet::parse(r.clone()).unwrap(), v, admin);
    raw["decision"] = json!("pass");
    assert_eq!(apply(&raw, &input, false), Allow);
    input["evidence"]["computed_strength"] = json!(0.84999);
    assert_eq!(apply(&raw, &input, false), NeedsApproval);
    input["evidence"]["computed_strength"] = json!(1.0);
    input["obligation"] = json!({"fulfillment_rate":0.4,"has_high_unfulfilled":true});
    assert_eq!(apply(&raw, &input, false), RequireHuman);
    input["obligation"]["has_critical_unfulfilled"] = json!(true);
    assert_eq!(apply(&raw, &input, false), Deny);
    raw["decision"] = json!("warn");
    raw["uncertainty_score"] = json!(0.15);
    assert_eq!(apply(&raw, &input, true), Revise);
    raw["self_correction_count"] = json!(2);
    assert_eq!(apply(&raw, &input, true), RequireHuman);
    raw["decision"] = json!("hold");
    raw["uncertainty_score"] = json!(0.25);
    assert_eq!(apply(&raw, &input, false), RequireHuman);
    input["approvals"]["required"] = json!(["reviewer"]);
    assert_eq!(apply(&raw, &input, false), NeedsApproval);
    input["stale"]["fresh"] = json!(false);
    assert_eq!(apply(&raw, &input, false), StaleBlocked);
    raw["decision"] = json!("block");
    assert_eq!(apply(&raw, &input, false), Deny);
}
#[test]
fn mcp_contracts() {
    let server = tiny_http::Server::http("127.0.0.1:0").unwrap();
    let endpoint = format!("http://{}", server.server_addr());
    let thread = thread::spawn(move || {
        for _ in 0..3 {
            let req = server
                .recv_timeout(std::time::Duration::from_secs(10))
                .unwrap()
                .unwrap();
            let data = match req.url() {
                "/v1/docs/resolve" => {
                    json!({"required_docs":[{"doc_id":"D"},{"doc_id":"E"}],"contract_refs":[{"contract_id":"C"}],"stale_summary":{"fresh":true}})
                }
                "/v1/docs/stale-check?task_id=T" => {
                    json!({"fresh":false,"stale_items":[{"item_id":"D"}],"stale_reasons":["changed"]})
                }
                "/v1/evaluate" => fixture(),
                url => panic!("想定外の URL {url}"),
            };
            req.respond(tiny_http::Response::from_string(data.to_string()))
                .unwrap();
        }
    });
    let mut s = open("sqlite:///:memory:", "tenant", Some(&endpoint));
    assert_eq!(GateService::tool_names().len(), 6);
    let recall = s
        .call_tool(
            "context.recall",
            json!({"task_id":"T","action":"edit","limit":1}),
        )
        .unwrap();
    assert_eq!(recall["required_docs"].as_array().unwrap().len(), 1);
    assert_eq!(recall["ack_required"], true);
    let stale = s
        .call_tool("context.stale_check", json!({"task_id":"T"}))
        .unwrap();
    assert_eq!(stale["stale_items"][0]["item_id"], "D");
    let assess=s.call_tool("state_gate.assess",json!({"run_id":"r","stage":"dev","artifact_refs":["a"],"diff_hash":"a".repeat(64),"semantic_evidence":{}})).unwrap();
    assert_eq!(assess["recommendation"], "hold_for_review");
    assert_eq!(assess["degraded"], false);
    thread.join().unwrap();
    let mut s = open("sqlite:///:memory:", "tenant", None);
    let evaluated = s
        .call_tool(
            "gate.evaluate",
            json!({"task_id":"T","action":"publish_release"}),
        )
        .unwrap();
    assert_eq!(evaluated["verdict"], "deny");
    assert_eq!(evaluated["failure_policy_applied"]["gatefield"], "deny");
    let replay = s
        .call_tool("run.replay_context", json!({"run_id":"RUN-T"}))
        .unwrap();
    assert_eq!(replay["status"], "verified");
    let items = s.call_tool("attention.list", json!({})).unwrap();
    assert_eq!(items["total_pending"], 0);
    assert!(s.call_tool("approval.create", json!({})).is_err());
    assert!(
        s.call_tool(
            "gate.evaluate",
            json!({"task_id":"T","action":"edit","tenant_id":"another"})
        )
        .is_err()
    );
}
#[test]
fn persistence_is_atomic_and_replay_checks_integrity() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("gate.db");
    let url = format!("sqlite:///{}", path.display());
    let mut gate = open(&url, "one", None);
    let db = rusqlite::Connection::open(path).unwrap();
    db.execute_batch("CREATE TRIGGER simulate_failure BEFORE INSERT ON attested_snapshots BEGIN SELECT RAISE(ABORT,'test'); END;").unwrap();
    let req = json!({"task_id":"T","action":"edit","run_id":"R"});
    assert!(gate.call_tool("gate.evaluate", req.clone()).is_err());
    assert!(gate.audit(None).unwrap().is_empty());
    assert_eq!(
        db.query_row("SELECT count(*) FROM assessments", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        0
    );
    db.execute_batch("DROP TRIGGER simulate_failure;").unwrap();
    gate.call_tool("gate.evaluate", req).unwrap();
    let past = gate
        .replay("R", Some(Utc::now() - Duration::hours(1)))
        .unwrap();
    assert_eq!(past["status"], "unavailable");
    db.execute(
        "UPDATE attested_snapshots SET attestation_hash='broken'",
        [],
    )
    .unwrap();
    assert_eq!(gate.replay("R", None).unwrap()["status"], "mismatch");
    assert_eq!(
        open(&url, "two", None).replay("R", None).unwrap()["status"],
        "unavailable"
    );
}
#[test]
fn binding_is_scoped_and_expires() {
    let temp = tempfile::tempdir().unwrap();
    let url = format!("sqlite:///{}", temp.path().join("bindings.db").display());
    let mut gate = open(&url, "one", None);
    let mut b = ApprovalBinding {
        approval_id: "AP".into(),
        policy_version: "v1".into(),
        diff_hash: "a".repeat(64),
        context_hash: "b".repeat(64),
        approved_roles: Default::default(),
        expires_at: None,
    };
    gate.save_approval_binding(&b).unwrap();
    let now = Utc::now();
    let current = |s: &mut GateService| {
        s.approval_is_current("AP", &"a".repeat(64), &"b".repeat(64), "v1", now)
            .unwrap()
    };
    assert!(current(&mut gate));
    assert!(!current(&mut open(&url, "two", None)));
    assert!(
        !gate
            .approval_is_current("AP", &b.diff_hash, &"1".repeat(64), "v1", now)
            .unwrap()
    );
    b.expires_at = Some(now - Duration::seconds(1));
    gate.save_approval_binding(&b).unwrap();
    assert!(!current(&mut gate));
}
#[test]
fn config_and_reference_contracts() {
    assert!(Config::from_yaml("runtime_profile: production_shadow").is_err());
    assert!(Config::from_yaml("adapters: {gatefield: {command: wrong}}").is_err());
    assert!(
        Config::from_yaml("environment: ci\nadapters: {gatefield: {timeout_seconds: 3}}").is_ok()
    );
    assert_eq!(
        "TRACKER:Issue:AbC".parse::<TypedRef>().unwrap().to_string(),
        "tracker:issue:local:AbC"
    );
    assert_eq!(
        "tracker:issue:github:a:b"
            .parse::<TypedRef>()
            .unwrap()
            .to_string(),
        "tracker:issue:github:a:b"
    );
}
