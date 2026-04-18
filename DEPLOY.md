# Deploying Project Velure

This is the operational guide. For *what is and isn't production-ready*, read [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) first. This file assumes you've decided to deploy.

---

## 1. Compose layout

The deployment is composed of stacked overlays. Each overlay adds capability without rewriting the base.

| File | Purpose | Required for prod? |
|---|---|---|
| [docker-compose.yml](docker-compose.yml)               | Dev defaults — hot reload, host port binding | dev only |
| [docker-compose.prod.yml](docker-compose.prod.yml)     | Hardened base: secrets, internal network, resource limits | **yes** |
| [docker-compose.tls.yml](docker-compose.tls.yml)       | Caddy reverse proxy with auto-Let's Encrypt | **yes** (closes §2.1) |
| [docker-compose.backup.yml](docker-compose.backup.yml) | Postgres backup sidecar (pg_dump + retention + optional S3) | **yes** (closes §2.3) |
| [docker-compose.observability.yml](docker-compose.observability.yml) | Prometheus + Grafana | strongly recommended |

**Full prod boot:**
```bash
docker compose --env-file .env.prod \
  -f docker-compose.prod.yml \
  -f docker-compose.tls.yml \
  -f docker-compose.backup.yml \
  -f docker-compose.observability.yml \
  up -d --build
```

---

## 2. The `.env.prod` file

Compose refuses to start if any required var is missing (the `${VAR:?...}` syntax in the prod file). This is the full set:

```bash
# ── Postgres ─────────────────────────────────────────────────────────
POSTGRES_DB=velure
POSTGRES_USER=velure
POSTGRES_PASSWORD=<strong random; rotate from any dev value>

# ── Redis ────────────────────────────────────────────────────────────
REDIS_PASSWORD=<strong random>

# ── Backend / app ────────────────────────────────────────────────────
VELURE_API_KEY=<strong random; gates REST + WS>
CORS_ORIGINS=https://app.velure.example.com,https://velure.example.com
PUBLIC_API_URL=https://velure.example.com
PUBLIC_WS_URL=wss://velure.example.com/ws/dashboard

# ── TLS overlay (docker-compose.tls.yml) ─────────────────────────────
DOMAIN_API=velure.example.com
DOMAIN_APP=app.velure.example.com
ACME_EMAIL=ops@velure.example.com

# ── Observability overlay ────────────────────────────────────────────
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=<strong random>
GRAFANA_ROOT_URL=https://grafana.velure.example.com   # if you proxy it

# ── Backup overlay (one of: local-only or local+S3) ──────────────────
BACKUP_INTERVAL_SEC=86400
BACKUP_RETENTION_COUNT=14
# For S3 offsite copy (optional but recommended):
BACKUP_S3_URI=s3://velure-backups/postgres
AWS_ACCESS_KEY_ID=<...>
AWS_SECRET_ACCESS_KEY=<...>
AWS_DEFAULT_REGION=us-east-1

# ── Optional: live data feeds ────────────────────────────────────────
DATA_MODE=simulator           # simulator | finnhub | hybrid | replay
FINNHUB_API_KEY=<...>
POLYGON_API_KEY=<...>

# ── Optional: alert sinks (at least one strongly recommended) ────────
ALERT_SLACK_WEBHOOK=https://hooks.slack.com/services/...
ALERT_PAGERDUTY_KEY=<routing key>
ALERT_DISCORD_WEBHOOK=
ALERT_GENERIC_WEBHOOK=
ALERT_EMAIL_SMTP_HOST=
ALERT_EMAIL_SMTP_PORT=587
ALERT_EMAIL_SMTP_USER=
ALERT_EMAIL_SMTP_PASSWORD=
ALERT_EMAIL_FROM=
ALERT_EMAIL_TO=
ALERT_MIN_SEVERITY=HIGH
```

**Storage:** Do not commit `.env.prod`. Source it from your secret manager at deploy time (Vault, AWS Secrets Manager, Doppler, sealed-secrets). A mounted file on the deploy host is acceptable provided the host is hardened.

---

## 3. First boot — step-by-step

**Pre-flight (do these once):**

1. Provision a host with Docker 24+, Compose v2, ≥ 4 GB RAM, ≥ 20 GB disk.
2. Open ports 80 and 443 on the firewall (Caddy needs them for TLS challenges + serving). Nothing else needs to be public.
3. Point DNS A/AAAA records for `${DOMAIN_API}` and `${DOMAIN_APP}` at the host.
4. Generate strong values for `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `VELURE_API_KEY`, `GRAFANA_ADMIN_PASSWORD`. Suggested: `openssl rand -base64 36`.
5. Populate `.env.prod` from your secret manager.

**Boot:**

```bash
git pull
docker compose --env-file .env.prod \
  -f docker-compose.prod.yml \
  -f docker-compose.tls.yml \
  -f docker-compose.backup.yml \
  -f docker-compose.observability.yml \
  up -d --build
```

**Verify (within ~2 minutes):**

```bash
# All services healthy
docker compose -f docker-compose.prod.yml -f docker-compose.tls.yml \
               -f docker-compose.backup.yml -f docker-compose.observability.yml \
               ps

# Backend reachable through TLS
curl -fsS "https://${DOMAIN_API}/health" | jq

# Audit chain intact (returns intact:true on a fresh DB)
curl -fsS "https://${DOMAIN_API}/api/audit/verify" \
     -H "X-API-Key: ${VELURE_API_KEY}" | jq

# Send a test alert through every configured sink
curl -fsS -X POST "https://${DOMAIN_API}/api/alerting/test?severity=HIGH" \
     -H "X-API-Key: ${VELURE_API_KEY}" | jq

# Grafana login (then change password if you didn't pin it)
open "http://127.0.0.1:3001"
```

---

## 4. Day-2 operations

### 4.1 Updating

```bash
git pull
docker compose --env-file .env.prod -f docker-compose.prod.yml ...other overlays... \
  up -d --build --no-deps backend frontend
```

`--no-deps` keeps Postgres/Redis untouched. Backend has a 60s health start_period, so traffic continues uninterrupted via Caddy until the new container is healthy.

### 4.2 Rollback

```bash
git checkout <previous-good-sha>
docker compose ...same overlays... up -d --build --no-deps backend frontend
```

If a model regression is suspected, the most recent on-disk checkpoint is in `data/checkpoints/previous/` — rename it to `current/` (atomic) and restart the backend.

### 4.3 Backups

The `postgres-backup` sidecar runs `pg_dump | gzip` on the schedule defined by `BACKUP_INTERVAL_SEC`. Files land in the `postgres_backups` volume with a `velure-YYYYMMDDTHHMMSSZ.sql.gz` name pattern. Retention is enforced by file count (`BACKUP_RETENTION_COUNT`).

**Restore drill (do this at least once before relying on it):**

```bash
# 1. Spin up a scratch postgres, list available dumps
docker compose -f docker-compose.prod.yml -f docker-compose.backup.yml \
  exec postgres-backup ls -lh /backups

# 2. Restore the latest dump into a scratch DB
docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U "${POSTGRES_USER}" -c "CREATE DATABASE velure_restore_test;"
docker compose -f docker-compose.prod.yml -f docker-compose.backup.yml \
  exec postgres-backup sh -c \
    "gunzip -c /backups/velure-<TS>.sql.gz | psql -h postgres -U ${POSTGRES_USER} velure_restore_test"

# 3. Spot-check rows
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U "${POSTGRES_USER}" -d velure_restore_test \
       -c "SELECT count(*) FROM fact_market_metrics; SELECT count(*) FROM audit_log;"
```

### 4.4 Monitoring

- **Grafana dashboard:** `http://127.0.0.1:3001 → Velure → Operational Overview`
- **Prometheus alerts:** see [deploy/prometheus/alerts.yml](deploy/prometheus/alerts.yml). Wire an Alertmanager to `alerting.alertmanagers` in [deploy/prometheus/prometheus.yml](deploy/prometheus/prometheus.yml) before relying on these in production.
- **Application alert sinks:** Slack / PagerDuty / etc. — configured via `ALERT_*` env. Verify with `POST /api/alerting/test`.
- **Audit chain:** `GET /api/audit/verify` walks the chain. A scheduled cron-job hitting this endpoint daily detects tampering.

### 4.5 Schema migrations

Right now schema is bootstrap-only via `/docker-entrypoint-initdb.d`. For a long-lived deployment you will eventually need Alembic — see §3.4 in [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md). Until then, hand-apply schema changes with:

```bash
docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U "${POSTGRES_USER}" "${POSTGRES_DB}" < new_migration.sql
```

### 4.6 Load testing

Run before every major release; the harness lives in [tests/load/k6_dashboard_load.js](tests/load/k6_dashboard_load.js). Pass thresholds enforce p95 latency, WS frame cadence, and connect success rate. See [tests/load/README.md](tests/load/README.md).

### 4.7 Checkpoint recovery testing

The integration test at [tests/test_checkpoint_recovery.py](tests/test_checkpoint_recovery.py) exercises the warm-start path. Run it in CI:

```bash
PYTHONPATH=backend pytest -xvs tests/test_checkpoint_recovery.py
```

---

## 5. Reverse proxy notes

Caddy auto-provisions Let's Encrypt certs on first boot. If you already terminate TLS upstream (cloud LB, existing nginx), drop `docker-compose.tls.yml` from the stack and bind backend/frontend to whatever interface your proxy expects. Whatever you choose, the WebSocket path **must** be `wss://` — `VELURE_API_KEY` is sent in headers and it leaks on the first hop if you allow plain HTTP.

---

## 6. Common boot failures

| Symptom | Cause | Fix |
|---|---|---|
| `RuntimeError: Refusing to start: CORS_ORIGINS='*'` | API key set but CORS still wildcarded | Set `CORS_ORIGINS` to an explicit comma-separated list of HTTPS origins |
| `POSTGRES_PASSWORD is required` (compose error) | `.env.prod` missing or var unset | Source `.env.prod` and re-run with `--env-file .env.prod` |
| Caddy logs `tls.issuance.acme: challenge failed` | DNS not pointing at host, or port 80/443 blocked | Verify A record, firewall, that nothing else is on 80/443 |
| `audit_log` insert errors | Migration `04-audit.sql` did not run (existing DB) | `psql ... < backend/db/migrations/04_audit.sql` once |
| `GRAFANA_ADMIN_PASSWORD is required` | Started observability overlay without setting it | Set in `.env.prod`, re-up Grafana |
| Backend keeps restarting, healthcheck fails | Cold model start can take ~45 s; check `docker compose logs backend` for the actual exception | Increase `start_period` in compose if your hardware is slow, or fix the underlying error |

---

## 7. Decommissioning a deployment

```bash
# Final backup before tear-down
docker compose -f docker-compose.prod.yml -f docker-compose.backup.yml \
  exec postgres-backup /usr/local/bin/backup.sh

# Copy backups + checkpoints off the host
docker run --rm -v velure_postgres_backups:/src -v $(pwd)/archive:/dst alpine \
  cp -a /src/. /dst/

# Stop and remove
docker compose ...all overlays... down -v   # -v removes volumes; omit if you want to keep them
```

Keep `audit_log` backups indefinitely if you have any compliance obligation. Consult counsel before deleting.
