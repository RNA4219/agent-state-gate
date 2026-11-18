"""同一の adapter、認証鍵、DB を使って Rust CLI と v0.5 の相互運用を検証する。"""

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa

from agent_state_gate.models import ApprovalBinding
from agent_state_gate.persistence import Database

BINARY = os.getenv("AGENT_STATE_GATE_RUST_BIN")
pytestmark = pytest.mark.skipif(not BINARY, reason="Rust CLI の検証には AGENT_STATE_GATE_RUST_BIN が必要")


@pytest.fixture
def adapters(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True) | {"kid": "gate-test"}
    packet = json.loads((Path(__file__).parents[1] / "fixtures/gatefield_decision_packet_v2.json").read_text())
    packet.update(policy_version="0.5.0", decision="pass", factors=[{"name": "score", "value": 1e-5}])
    state = {"packet": packet, "fresh": True, "stage": "dev"}

    class Handler(BaseHTTPRequestHandler):
        def reply(self, value):
            data = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/v1/docs/stale-check":
                self.reply({"fresh": state["fresh"]})
            elif path.startswith("/v1/tasks/"):
                self.reply({"stage": state["stage"]})
            elif path == "/v1/health":
                self.reply({"pgvector_ready": True})
            elif path == "/jwks":
                self.reply({"keys": [jwk]})
            elif path == "/.well-known/openid-configuration":
                self.reply({"jwks_uri": endpoint + "/jwks"})
            else:
                self.send_error(404)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/v1/evaluate" and body["trace"]["run_id"] == body["run_id"]:
                assert ("artifact" in body) != ("semantic_evidence" in body)
                self.reply(state["packet"])
            else:
                self.send_error(400)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    endpoint = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (tmp_path / ".workflow-cache").mkdir()
        (tmp_path / ".workflow-cache/evidence.json").write_text('{"acceptances":[],"evidences":[]}')
        (tmp_path / "docs/acceptance").mkdir(parents=True)
        for name, data in [("task", {"task_id": "T", "title": "設計 🐦"}), ("run", {"stage": "dev"})]:
            (tmp_path / name).write_text(f"import json\nprint(json.dumps({data!r}))", encoding="utf-8")
        config = {
            "adapters": {
                "gatefield": {"endpoint": endpoint}, "shipyard": {"endpoint": endpoint},
                "memx": {"endpoint": endpoint}, "taskstate": {"command": sys.executable, "working_dir": str(tmp_path)},
                "workflow": {"cookbook_path": str(tmp_path)}, "protocols": {"schemas_path": str(tmp_path)},
            }, "database": {"url": f"sqlite:///{tmp_path / 'gate.db'}"},
        }
        yield config, state, key, endpoint
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def invoke(config_path, *args, python=False, code=0, token=None):
    prefix = [sys.executable, "-m", "agent_state_gate.cli"] if python else [BINARY]
    env = os.environ.copy()
    env.pop("AGENT_STATE_GATE_TOKEN", None)
    if token:
        env["AGENT_STATE_GATE_TOKEN"] = token
    result = subprocess.run(
        [*prefix, "--config", str(config_path), "--output", "json", *args],
        capture_output=True, encoding="utf-8", env={**env, "PYTHONIOENCODING": "utf-8"}, timeout=30,
    )
    assert result.returncode == code, (result.stdout, result.stderr)
    return json.loads(result.stdout if result.stdout else result.stderr)


def test_bidirectional_replay_and_queue(tmp_path, adapters):
    cfg, state, _, _ = adapters
    path = tmp_path / "gate.yaml"
    path.write_text(yaml.safe_dump(cfg))
    for python, run in [(True, "python"), (False, "rust")]:
        result = invoke(path, "gate", "evaluate", "--task", "T", "--run", run, python=python)
        assert result["verdict"] == "allow"
        assert invoke(path, "replay", "--run", run, python=not python)["status"] == "verified"
        assert invoke(path, "audit", "--run", run, python=not python)["packets"][0]["packet_id"] in result["audit_packet_ref"]
        assert invoke(path, "--tenant", "other", "replay", "--run", run, code=2)["status"] == "unavailable"
        assert invoke(path, "--subject", "other", "replay", "--run", run, code=2)["status"] == "mismatch"

    state["fresh"] = False
    result = invoke(path, "gate", "evaluate", "--task", "T", "--run", "stale", code=2)
    assert result["verdict"] == "stale_blocked"
    items = invoke(path, "queue", "list", "--status", "pending")["items"]
    item = items[0]["item_id"]
    assert invoke(path, "queue", "take", "--item", item, "--reviewer", "alice", python=True)["status"] == "taken"
    invoke(path, "queue", "resolve", "--item", item, "--reviewer", "bob", "--resolution", "reject", code=1)
    assert invoke(path, "queue", "resolve", "--item", item, "--reviewer", "alice", "--resolution", "approve")["version"] == 3
    assert invoke(path, "health")["ready"]
    state["packet"]["decision"] = "block"
    assert invoke(path, "gate", "evaluate", "--task", "T", "--run", "blocked", code=3)["verdict"] == "deny"
    args = ["gate", "state-assess", "--run", "r", "--stage", "publish", "--artifact-ref", "a", "--redacted-diff", "概要"]
    assert invoke(path, *args, "--diff-hash", "a"*64, code=3)["recommendation"] == "block"
    invoke(path, *args, "--diff-hash", "x", code=1)
    invoke(path, "maintenance", "purge", code=1)
    assert invoke(path, "--roles", "data_retention_admin", "maintenance", "purge")["deleted_by_class"]["ops"] == 0


def test_oidc_and_postgresql_queue(tmp_path, adapters):
    cfg, state, key, issuer = adapters
    database_url = os.getenv("AGENT_STATE_GATE_DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("移行済みのテスト用 PostgreSQL が必要")
    cfg.update(runtime_profile="production_enforce", database={"url": database_url},
               oidc={"enabled": True, "issuer": issuer, "audience": "state-gate"})
    path = tmp_path / "production.yaml"
    path.write_text(yaml.safe_dump(cfg))
    claims = {"iss": issuer, "aud": "state-gate", "sub": "reviewer", "tenant_id": uuid.uuid4().hex,
              "roles": ["developer"], "exp": int(time.time()) + 300}

    def sign(**overrides):
        return jwt.encode(claims | overrides, key, algorithm="RS256", headers={"kid": "gate-test"})

    token = sign()
    for invalid in (None, sign(aud="other"), sign(exp=0), sign(iss="other"), sign(roles=3)):
        invoke(path, "health", token=invalid, code=1)
    assert invoke(path, "health", token=token)["ready"]
    state["packet"]["decision"] = "hold"
    assert invoke(path, "gate", "evaluate", "--task", "T", "--run", "pg", token=token, code=2)["verdict"] == "needs_approval"
    assert invoke(path, "replay", "--run", "pg", token=token, python=True)["status"] == "verified"
    assert invoke(path, "replay", "--run", "pg", token=token)["status"] == "verified"
    assert invoke(path, "queue", "list", token=sign(tenant_id="other-tenant"))["count"] == 0
    item = invoke(path, "queue", "list", token=token)["items"][0]["item_id"]

    def take(n):
        env = {**os.environ, "AGENT_STATE_GATE_TOKEN": token}
        return subprocess.run([BINARY, "--config", str(path), "queue", "take", "--item", item, "--reviewer", str(n)],
                              capture_output=True, env=env, timeout=30).returncode

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sorted(pool.map(take, range(4))) == [0, 1, 1, 1]


@pytest.mark.parametrize("first_python", [True, False], ids=["python-to-rust", "rust-to-python"])
@pytest.mark.parametrize(("run_stage", "expected_stage"), [("dev", "dev"), (None, "unknown")])
def test_null_shipyard_stage_shares_approval(tmp_path, adapters, first_python, run_stage, expected_stage):
    cfg, state, _, _ = adapters
    state["stage"] = None
    run_json = json.dumps({"stage": run_stage})
    (tmp_path / "run").write_text(f"print({run_json!r})", encoding="utf-8")
    path = tmp_path / "gate.yaml"
    path.write_text(yaml.safe_dump(cfg))
    tenant = "stage-test"
    args = ["--tenant", tenant, "gate", "evaluate", "--task", "T", "--run", "R",
            "--capability", "publish_release", "--diff-hash", "a" * 64]
    db = Database(cfg["database"]["url"])

    def evaluate(python, code):
        result = invoke(path, *args, python=python, code=code)
        return db.get_assessment(tenant, result["assessment_id"])

    try:
        pending = evaluate(first_python, 2)
        assert (pending.stage, pending.final_verdict) == (expected_stage, "needs_approval")
        db.save_approval_binding(ApprovalBinding(
            approval_id="stage-approval", tenant_id=tenant, diff_hash=pending.diff_hash,
            context_hash=pending.context_hash, policy_version=pending.policy_version,
            approved_roles={"project_lead", "security_reviewer"},
        ))
        approved = evaluate(not first_python, 0)
        assert (approved.stage, approved.final_verdict) == (expected_stage, "allow")
        assert approved.context_hash == pending.context_hash

        state["stage"] = "publish"
        changed = evaluate(not first_python, 2)
        assert (changed.stage, changed.final_verdict) == ("publish", "needs_approval")
        assert changed.context_hash != pending.context_hash
    finally:
        db.engine.dispose()


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_evaluate_requires_approval_for_current_diff_and_context(tmp_path, adapters, backend):
    cfg, state, _, _ = adapters
    if backend == "postgresql":
        url = os.getenv("AGENT_STATE_GATE_DATABASE_URL", "")
        if not url.startswith(("postgresql://", "postgresql+psycopg://")):
            pytest.skip("テスト用 PostgreSQL が必要")
        cfg["database"]["url"] = url
    config_file = tmp_path / "binding.yaml"
    config_file.write_text(yaml.safe_dump(cfg))
    tenant = uuid.uuid4().hex
    roles = ["project_lead", "security_reviewer"]
    (tmp_path / "run").write_text(f"import json\nprint(json.dumps({{'stage':'dev', 'approved_roles':{roles!r}}}))")
    db = Database(cfg["database"]["url"])
    diff, changed_diff = "a" * 64, "b" * 64
    first_python = backend == "postgresql"

    def evaluate(python, digest, expected):
        args = ["--tenant", tenant, "gate", "evaluate", "--task", "T", "--run", "R", "--capability", "publish_release"]
        if digest is not None:
            args.extend(["--diff-hash", digest])
        result = invoke(config_file, *args, python=python, code={"allow": 0, "needs_approval": 2, "deny": 3}[expected])
        assert result["verdict"] == expected
        return db.get_assessment(tenant, result["assessment_id"])

    def bind(identifier, assessment, approved, **overrides):
        values = {"approval_id": identifier, "tenant_id": tenant, "diff_hash": assessment.diff_hash,
                  "context_hash": assessment.context_hash, "policy_version": assessment.policy_version,
                  "approved_roles": frozenset(approved)}
        db.save_approval_binding(ApprovalBinding(**(values | overrides)))

    try:
        first = evaluate(first_python, diff, "needs_approval")
        assert first.approval_summary["missing_approvals"] == roles
        bind("cross-tenant", first, roles, tenant_id=tenant + "-other")
        bind("old-policy", first, roles, policy_version="previous")
        bind("expired", first, roles, expires_at=datetime.now(UTC) - timedelta(seconds=5))
        bind("lead", first, roles[:1])
        partial = evaluate(not first_python, diff, "needs_approval")
        assert partial.approval_summary["missing_approvals"] == roles[1:]
        assert partial.context_hash == first.context_hash
        bind("security", first, roles[1:])

        state["packet"].update(decision_id="DEC-2", request_id="REQ-2", created_at="2026-11-18T00:00:00Z")
        (tmp_path / "run").write_text("import json\nprint(json.dumps({'stage':'dev'}))")
        assert evaluate(not first_python, diff, "allow").context_hash == first.context_hash
        second = evaluate(first_python, changed_diff, "needs_approval")
        assert second.context_hash == first.context_hash
        bind("new-diff", second, roles)
        assert evaluate(not first_python, changed_diff, "allow").diff_hash == changed_diff

        (tmp_path / "task").write_text("import json\nprint(json.dumps({'task_id':'T', 'title':'changed'}))")
        third = evaluate(not first_python, changed_diff, "needs_approval")
        assert third.context_hash != second.context_hash
        bind("new-context", third, roles)
        for python in (True, False):
            # 保存時点の未承認判定は、後の承認が追加されても再現できる。
            replay = invoke(config_file, "--tenant", tenant, "replay", "--run", "R", python=python)
            assert replay["status"] == "verified" and replay["actual_verdict"] == "needs_approval"
        assert evaluate(first_python, changed_diff, "allow").context_hash == third.context_hash
        for python in (True, False):
            assert invoke(config_file, "--tenant", tenant, "replay", "--run", "R", python=python)["actual_verdict"] == "allow"

        bind("unknown-diff", third, roles, diff_hash="0" * 64)
        evaluate(first_python, None, "needs_approval")
        evaluate(not first_python, "0" * 64, "needs_approval")
        state["packet"]["decision"] = "block"
        evaluate(first_python, changed_diff, "deny")
    finally:
        db.engine.dispose()
