# Project Velure

A real-time financial crisis early-warning system that streams live market data through a six-model ML ensemble and surfaces systemic risk on a sub-100ms dashboard.

Headline links:

- [Top-level README](./README.md) — install, run, architecture, endpoints
- [Architecture](./ARCHITECTURE.md) — component design & data flow
- [Deployment](./DEPLOY.md) — Render / Fly.io / TLS / observability
- [Security](./SECURITY.md) — threat model & hardening
- [Production readiness](./PRODUCTION_READINESS.md) — gap analysis & rollout
- [Operator playbook](./PLAYBOOK.md) — on-call runbook
- [Contributing](./CONTRIBUTING.md) — dev setup, standards, PR process
- [Changelog](./CHANGELOG.md) — release history
- [License](./LICENSE) — MIT

Sub-projects:

- [Backend (FastAPI)](./backend/) — Python 3.11 service
- [Frontend (Next.js)](./frontend/) — Next.js 16 dashboard
- [Crisis simulation data](./crisis-simulation-data/) — labelled historical fixtures
- [Tests](./tests/) — pytest harness
- [Deployment helpers](./deploy/) — Render / Fly.io / backup

For a guided demo script, see [WALKTHROUGH.md](./WALKTHROUGH.md). For the broader project narrative, see [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md).
