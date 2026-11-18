"""同一の adapter、認証鍵、DB を使って Rust CLI と v0.5 の相互運用を検証する。"""

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa

BINARY = os.getenv("AGENT_STATE_GATE_RUST_BIN")
pytestmark = pytest.mark.skipif(not BINARY, reason="Rust CLI の検証には AGENT_STATE_GATE_RUST_BIN が必要")


@pytest.fixture
def adapters(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True) | {"kid": "gate-test"}
    packet = json.loads((Path(__file__).parents[1] / "fixtures/gatefield_decision_packet_v2.json").read_text())
    packet.update(policy_version="0.5.0", decision="pass", factors=[{"name": "score", "value": 1e-5}])
    state = {"packet": packet, "fresh": True}

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
                self.reply({"stage": "dev"})
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
