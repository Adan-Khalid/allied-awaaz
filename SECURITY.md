# Security policy

Allied Awaaz is a hackathon proof of concept. It is **not** production banking software, and the
payment gateway is simulated.

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's
[private vulnerability reporting](../../security/advisories/new) for this repository instead, with
steps to reproduce and the impact you expect.

## Scope

In scope: request signing and replay protection, MQTT message verification on the terminal, agent
tool boundaries (no money movement, no arbitrary queries), staff role gates and the audit log. The
design is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Default secrets in `.env.example` and `config.h.example` are placeholders and must be changed before
any shared deployment.
