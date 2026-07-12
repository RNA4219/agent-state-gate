# Security Policy

## Production boundary

- Production Shadow/Enforce requires PostgreSQL, OIDC JWT verification, and all configured adapters.
- Every request carries a tenant-scoped `RequestContext`; queries and queue operations never cross tenants.
- Raw diffs, tokens, secrets, and evidence bodies are not persisted. Use `diff_hash` and redacted summaries.
- Adapter failures are recorded as degraded and apply the documented fail-safe policy; they never become an unsafe `allow`.

## Reporting

Report suspected vulnerabilities privately to the repository maintainers. Include a minimal reproduction, affected profile, and sanitized logs.

Do not include bearer tokens, private keys, customer data, or unredacted diffs in an issue or pull request.
