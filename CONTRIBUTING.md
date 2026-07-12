# Contributing

1. Use Python 3.11–3.13 and `uv sync --extra dev`.
2. Keep public contracts in `agent_state_gate` and route MCP/CLI behavior through `GateService`.
3. Add unit and integration coverage for configuration, tenant scope, failure policy, replay, and CLI exit codes.
4. Run `uv run ruff check agent_state_gate migrations tests`, `uv run mypy agent_state_gate src`, and `uv run pytest --cov=agent_state_gate --cov-fail-under=90 -q`.
5. Never commit tokens, secrets, raw diffs, generated caches, or internal research material.

## Pull requests

Describe the contract change, migration impact, security impact, and rollback plan. Production profile changes require a shadow evidence update and release checklist entry.

## Commits

Use focused commits and keep generated artifacts out of source control.
