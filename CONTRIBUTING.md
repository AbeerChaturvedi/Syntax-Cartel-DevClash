# Contributing to Project Velure

Thanks for your interest in making financial-crisis detection faster, smarter, and more open. This guide explains how to set up a dev environment, the standards we hold PRs to, and how to get a review.

## Code of conduct

Be respectful. Assume good faith. No harassment, no doxxing, no spam. Maintainers reserve the right to close or lock any issue or PR that violates this.

## Project layout

| Path | What lives here |
|------|-----------------|
| `backend/` | FastAPI service (Python 3.11) |
| `frontend/` | Next.js 16 dashboard |
| `deploy/` | Render / Fly.io / TLS / observability manifests |
| `tests/` | pytest harness |
| `crisis-simulation-data/` | Frozen historical fixtures |
| `*.md` at root | Architecture, ops, security, demo scripts — read these before opening large PRs |

## Setting up locally

The full quick start is in [README.md](./README.md). The minimal loop:

```bash
# 1. Backend
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch==2.4.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
export DATA_MODE=simulator
uvicorn main:app --reload --port 8000

# 2. Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

The dashboard will be at <http://localhost:3000>, the API at <http://localhost:8000>.

## Branching & commits

- Branch off `main`.
- One logical change per branch. Squash or rebase noisy WIP history before review.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):

  ```
  feat(ingestion): add Twelve Data WebSocket adapter
  fix(persistence): resolve dim_source provider_name mismatch
  docs(README): add deployment section
  refactor(models): extract ensemble fusion into pure function
  test(backtest): add 2023 SVB labelled-window fixture
  chore(deps): bump fastapi to 0.115.0
  ```

- Reference any tracked issue with `Refs: #123` or `Closes: #123` in the body.

## Coding standards

### Python (`backend/`)

- Python 3.11+. Use modern syntax (`match`, `|` unions, `from __future__ import annotations` only when needed).
- Type hints on every public function. Run `mypy backend/` before pushing if you have it installed locally.
- Format with `ruff format` and lint with `ruff check`. Config lives in `pyproject.toml`.
- Prefer `async` end-to-end inside the request/stream path; CPU-bound work goes through `asyncio.to_thread`.
- Never `print()` from the request path — use the structured logger in `backend/utils/logger.py`.
- New external HTTP calls go through the rate-limited clients in `backend/ingestion/`. Don't roll a new `aiohttp.ClientSession` ad hoc.

### TypeScript / React (`frontend/`)

- Next.js App Router. Read `frontend/AGENTS.md` and `frontend/CLAUDE.md` before introducing structural changes — Next 16 has breaking changes from earlier majors.
- Components are functional, props are typed, no `any` unless you have a comment explaining why.
- ECharts wrappers live in `frontend/src/app/components/`. Keep chart logic out of page files.
- The dashboard streams at 60 fps — measure before adding anything to the render path.

### SQL / Postgres

- Every migration gets a numbered file under `backend/db/migrations/`. Never edit a migration that has shipped.
- Idempotent where possible (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`).
- Schema changes must include a matching update to `backend/db/schema.sql` so a fresh `docker compose up` reproduces the new shape.

### Secrets, API keys, models

- Never commit `.env`, `*.pkl`, `*.pt`, `data/`. These are gitignored.
- New data-feed integrations must read their API key from the environment, never from a constant.

## Testing

| Layer | Command |
|---|---|
| Backend unit + integration | `cd backend && pytest -q` |
| Checkpoint recovery / replay | `cd tests && pytest -q test_checkpoint_recovery.py` |
| Frontend lint | `cd frontend && npm run lint` |
| Frontend type-check | `cd frontend && npx tsc --noEmit` (Next.js produces `.next/types` for `tsc`) |
| Full local stack | `docker compose up --build` then exercise the dashboard manually |

A PR must include tests for new behaviour, and must not regress existing tests.

## Pull request checklist

Before requesting review:

- [ ] Branch is up to date with `origin/main` (`git fetch && git rebase origin/main`).
- [ ] `pytest` is green.
- [ ] `npm run lint` is green.
- [ ] No secrets, model artefacts, or build outputs are staged.
- [ ] Docs updated: `README.md`, `ARCHITECTURE.md`, or the relevant sub-doc.
- [ ] PR description explains **what** and **why**, not just how.
- [ ] Screenshots or screen recordings attached for any UI change.

## Review SLA

Maintainers aim for a first response within two business days. We review PRs in the order they arrive. If your PR is urgent, mention a maintainer in the description.

## Reporting security issues

Please do **not** file public issues for suspected vulnerabilities. Email `security@<your-domain>` instead, or open a GitHub Security Advisory (private). See [SECURITY.md](./SECURITY.md) for the full policy.

## License

By contributing you agree that your contributions are licensed under the project's [MIT License](./LICENSE).