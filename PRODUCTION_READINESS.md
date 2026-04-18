# Project Velure — Production Readiness Gap Analysis

**Status:** Honest assessment, not marketing.
**Scope:** What is shippable today, what blocks real-money deployment, what is deferred.
**Audience:** Whoever signs off on running this against live capital or production data feeds.
**Last revised:** v4 — deployment hardening pass (TLS, backup, observability, audit chain, load test, recovery test).

---

## 0. Architectural snapshot

```
┌────────────┐    WSS     ┌──────────────┐    SQL/TS    ┌──────────────┐
│ Browser UI │◀──────────▶│  FastAPI     │─────────────▶│ TimescaleDB  │
│ (Next 16)  │            │  + Ensemble  │              │ (pg16+ext)   │
└────────────┘            │  + Dispatcher│◀────cache────│   Redis      │
        ▲                 └──────┬───────┘              └──────────────┘
        │                        │
   reverse proxy            Slack / Discord / PagerDuty / Webhook / SMTP
   (TLS terminator)
```

Backend = single Python process. Models (xLSTM, GNN, RL ensemble) run in-process.
Frontend = Next.js 16 standalone runner. No SSR data fetch from DB; all live data flows over the WS channel.

---

## 1. What is production-ready *today*

| Area | State | Evidence |
|---|---|---|
| Container hardening | ✅ | Multi-stage Dockerfiles, non-root uid 10001, `tini` PID 1, `cap_drop ALL`, `no-new-privileges`, read-only rootfs + tmpfs where applicable. ([backend/Dockerfile](backend/Dockerfile), [frontend/Dockerfile](frontend/Dockerfile)) |
| Secret-driven config | ✅ | `${VAR:?...}` required-env syntax in [docker-compose.prod.yml](docker-compose.prod.yml) — compose refuses to start if creds missing. No defaults in prod. |
| Network isolation | ✅ | `velure_internal` bridge; Postgres + Redis are NOT exposed on the host network. Backend/Frontend are bound to `127.0.0.1`. |
| Resource fences | ✅ | `deploy.resources.limits` for every service. A runaway model cannot OOM the host. |
| Log rotation | ✅ | `json-file` driver, 50 MB × 5 per service. No silent disk-fill. |
| Healthchecks | ✅ | All four services define `HEALTHCHECK` with realistic `start_period`. Backend gates on Postgres + Redis being healthy. |
| TimescaleDB extension | ✅ | `timescale/timescaledb:latest-pg16` image; `schema_timescale.sql` mounted into init dir. `USE_TIMESCALE=1` is set in compose. |
| Display stability | ✅ | EMA smoothing (α=0.04) + 1-min rolling median + 2 s flush cadence on both server and client. No more per-tick flicker. |
| Alert delivery | ✅ | Five sinks wired (Slack / Discord / PagerDuty / Generic webhook / SMTP). Dedup key + send-and-forget concurrency. ([backend/utils/alerting.py](backend/utils/alerting.py)) |
| Rate limiting + API key gate | ✅ | `SecurityMiddleware` enforces `VELURE_API_KEY` and per-IP RPM on REST. ([backend/utils/middleware.py:55](backend/utils/middleware.py#L55)) |
| WebSocket auth | ✅ **v4** | WS `/ws/dashboard` validates `X-API-Key` (or `?api_key=…`) *before* connection registration. Bad key → 1008 close, no resource allocation. ([backend/main.py](backend/main.py)) |
| CORS lockdown at startup | ✅ **v4** | Backend refuses to boot if `CORS_ORIGINS='*'` and `VELURE_API_KEY` is set. Defence in depth against ops misconfiguration. |
| Graceful shutdown | ✅ | `tini` forwards SIGTERM → uvicorn drains in-flight WS frames. |
| CPU-only inference | ✅ | torch CPU wheels in builder stage — image is ~1.7 GB lighter and runs on commodity nodes. |
| TLS termination | ✅ **v4** | Caddy reverse proxy ([deploy/caddy/Caddyfile](deploy/caddy/Caddyfile)) with auto-Let's Encrypt, HSTS, CSP, h2/h3. Engaged via [docker-compose.tls.yml](docker-compose.tls.yml). When this overlay is active, backend/frontend ports are not host-exposed. |
| Postgres backup | ✅ **v4** | [docker-compose.backup.yml](docker-compose.backup.yml) sidecar runs `pg_dump | gzip` on schedule with retention; optional S3 offsite copy if AWS env present. Restore drill documented in [DEPLOY.md §4.3](DEPLOY.md). |
| Observability stack | ✅ **v4** | Prometheus + Grafana overlay ([docker-compose.observability.yml](docker-compose.observability.yml)) with provisioned datasource, the `Velure — Operational Overview` dashboard, and 6 alert rules covering pipeline-down / latency / circuit breakers / db error budget / silent-alerter / WS drop. |
| Sustained load proof | ✅ **v4** | k6 harness ([tests/load/k6_dashboard_load.js](tests/load/k6_dashboard_load.js)) exercises REST pollers, 200 concurrent WS clients, and burst API for ~5.5 min total. Hard thresholds fail the run if breached. |
| Checkpoint recovery test | ✅ **v4** | [tests/test_checkpoint_recovery.py](tests/test_checkpoint_recovery.py) — round-trip + atomic promotion + version-mismatch refusal + corrupt-temp-dir non-pollution + state-survives-restart. |
| Tamper-evident audit trail | ✅ **v4** | `audit_log` table is hash-chained (`this_hash = sha256(prev_hash || canonical)`). Every dispatched alert auto-recorded via `alert_dispatcher.set_audit_sink`. `GET /api/audit/verify` walks the chain and reports the first broken row. |
| Model lineage | ✅ **v4** | `model_lineage` table records `(model_version, checkpoint_hash, components, weights, activated_at)`. Every audit row stamps the active version. `GET /api/lineage` lists history. |
| Operator deploy guide | ✅ **v4** | [DEPLOY.md](DEPLOY.md) — compose layout, full `.env.prod` reference, first boot, day-2, restore drill, troubleshooting matrix. |
| Threat model + checklist | ✅ **v4** | [SECURITY.md](SECURITY.md) — trust boundaries, what we enforce vs don't, operator hygiene checklist. |

---

## 2. Blocking gaps — status

§2.1, §2.3, §2.4, §2.5 were **closed in v4**. They are now in §1 above. The remaining v4 blocker:

### 2.1 ~~TLS termination~~ — **closed v4**
Caddy overlay ships, auto-Let's Encrypt + HSTS + CSP. Engage via [docker-compose.tls.yml](docker-compose.tls.yml).

### 2.2 Real secret storage *(still open)*
- **Current:** `.env.prod` file on disk, read by `docker compose --env-file`.
- **Required:** A secret manager — Vault, AWS Secrets Manager, GCP Secret Manager, Doppler, or sealed-secrets if k8s. Rotate `VELURE_API_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`, and all `ALERT_*` credentials on schedule.
- **Why still blocking for regulated deployments:** A `.env.prod` on the host is a single `cat` away from a full system compromise. Backups capture it. SOC 2 + ISO 27001 reviewers will flag it.
- **Acceptable interim:** A hardened deploy host with the file at `chmod 600`, root-owned, no shared shell access, encrypted disk, audited access logs. This is the realistic path for self-hosted MVP deployments.

### 2.3 ~~No backup strategy for Postgres~~ — **closed v4**
Sidecar runs `pg_dump | gzip` on schedule with retention; optional S3 offsite copy. See [docker-compose.backup.yml](docker-compose.backup.yml). **Restore drill documented but must be executed once on the target environment before this counts as actually safe** — see [DEPLOY.md §4.3](DEPLOY.md).

### 2.4 ~~No load test against the real ingestion path~~ — **closed v4**
k6 harness at [tests/load/k6_dashboard_load.js](tests/load/k6_dashboard_load.js). Pass thresholds enforce p95 latency, WS frame cadence, REST error budget, connect success rate. Run before every release on the production-equivalent stack and attach the JSON summary to the deploy ticket.

### 2.5 ~~Model checkpoint recovery has no integration test~~ — **closed v4**
pytest at [tests/test_checkpoint_recovery.py](tests/test_checkpoint_recovery.py). Six scenarios including the headline "state survives a simulated restart" assertion. Wire into CI.

---

## 3. Important gaps — status

### 3.1 ~~Observability~~ — **closed v4**
Prometheus + Grafana overlay with provisioned datasource, dashboard, and 6 alert rules. See [docker-compose.observability.yml](docker-compose.observability.yml). Alertmanager is **not yet wired** — set its URL in [deploy/prometheus/prometheus.yml](deploy/prometheus/prometheus.yml) `alerting.alertmanagers` before relying on the rules.

### 3.2 Kubernetes manifests *(still open, intentionally deferred)*
- **Current:** [deploy/k8s/](deploy/k8s/) is empty.
- **Status:** Single-host Docker Compose is fine for an MVP. Multi-AZ HA needs k8s (or Nomad / ECS). Defer until traffic + uptime SLO actually demands it.
- **When to revisit:** First time you need rolling deploys without downtime, or you outgrow a single VM.

### 3.3 TimescaleDB tuning *(still open)*
- **Current:** Out-of-the-box image, no `timescaledb-tune` run, default `shared_buffers` / `work_mem`.
- **Action:** On first prod deploy, run `timescaledb-tune --quiet --yes` against `postgresql.conf`, then set continuous-aggregate refresh policies and a retention policy on the tick hypertable (e.g. raw ticks 7 d, 1-min agg 90 d, 1-h agg ∞).

### 3.4 Database migration discipline *(still open)*
- **Current:** `schema.sql` + `seed.sql` + `schema_timescale.sql` + `04_audit.sql` run only on first boot via `/docker-entrypoint-initdb.d/`. Subsequent schema changes have no migration path.
- **Action:** Adopt Alembic (Python-native, integrates with SQLAlchemy) or sqitch. Bake a `migrate` step into the backend entrypoint or run it as a one-shot init container.
- **Interim:** [DEPLOY.md §4.5](DEPLOY.md) documents the manual `psql … < migration.sql` path.

### 3.5 RBAC for the API key *(still open)*
- **Current:** `VELURE_API_KEY` is a single shared bearer — full read + admin in one token.
- **Action:** Issue per-consumer keys with scopes (`read:stream`, `admin:test_alert`, `admin:replay`). Store hashed keys in Postgres, not env. Add a `key_id` claim to logs so abuse is traceable.

### 3.6 ~~CORS hardening verification~~ — **closed v4**
Startup assertion in [backend/main.py](backend/main.py) refuses to boot if `CORS_ORIGINS='*'` and `VELURE_API_KEY` is set.

### 3.7 ~~WebSocket auth on connect~~ — **closed v4**
WS endpoint validates the API key from header or query param before registering with the connection manager. Bad key closes 1008 immediately.

### 3.8 Image vulnerability scanning *(new — open)*
- **Action:** Wire Trivy (or Grype) into CI. Block image promotion on HIGH+ CVEs. Pin and update the base images quarterly.

---

## 4. Compliance / regulatory considerations

This system *advises* on financial risk. It is not (yet) an order router. Even so:

- **Audit log:** ✅ **closed v4** — every dispatched alert is persisted to a hash-chained `audit_log` table with model_version stamping. Walk integrity via `GET /api/audit/verify`. Schedule a daily cron-job hitting that endpoint and alert on `intact: false`.
- **Model lineage:** ✅ **closed v4** — `model_lineage` table records every (version, checkpoint_hash, weights, activation_at) combination. Audit rows reference `model_version`, joining via `v_alert_audit` view.
- **Training-data window in lineage:** still open — the registry records the model state at deploy time, not the data window the LSTM was trained on. Fix when the LSTM gets a true offline training pipeline (currently it warms online).
- **Right-to-explain:** The factor-attribution UI satisfies a spirit-of-MiFID-II explainability requirement. Document this in the user-facing terms.
- **PII:** None today — we ingest only market data. If user accounts are added, GDPR DPIA + data-residency review become mandatory.
- **Disclaimer:** UI must carry a "for informational purposes only, not investment advice" notice in any jurisdiction where the system is read by retail users. Currently absent.

---

## 5. Operational runbooks

| Runbook | Status | Source of truth |
|---|---|---|
| **Cold start** — VM-up to traffic-serving | ✅ written | [DEPLOY.md §3](DEPLOY.md) |
| **Updating + rollback** | ✅ written | [DEPLOY.md §4.1–4.2](DEPLOY.md) |
| **Backup + restore drill** | ✅ written | [DEPLOY.md §4.3](DEPLOY.md) — restore must be exercised once on the target env before this counts |
| **Audit chain verification** | ✅ written | [DEPLOY.md §4.4](DEPLOY.md) + `GET /api/audit/verify` |
| **Manual schema migration** | ✅ written | [DEPLOY.md §4.5](DEPLOY.md) |
| **Load test rerun** | ✅ written | [tests/load/README.md](tests/load/README.md) |
| **Operator hygiene checklist** | ✅ written | [SECURITY.md](SECURITY.md) |
| **Common boot failures** | ✅ written | [DEPLOY.md §6](DEPLOY.md) |
| **Decommissioning** | ✅ written | [DEPLOY.md §7](DEPLOY.md) |
| **On-call rotation + escalation policy** | open | Operator-org-specific. Write it before exposing to untrusted networks. |
| **Postgres failover** | open | Depends on HA strategy chosen (single-host has no failover; for HA, see §3.2) |
| **Model rollback** | partial | Mechanism exists (rename `previous/` → `current/`); acceptance criteria for "is the rollback model still good?" not yet written. |
| **Replay-against-known-crisis acceptance criteria** | open | Engine exists; the *pass/fail thresholds* (lead time, ROC AUC) are not yet codified. |
| **Incident response — alerts went silent** | open | Sink-down vs dispatcher-hung vs model-loop-crashed triage tree. |

---

## 6. Deployment checklist (one-time, before first prod boot)

```
□ TLS-terminating reverse proxy provisioned with valid cert
□ .env.prod populated from secret manager, not committed
□ POSTGRES_PASSWORD, REDIS_PASSWORD, VELURE_API_KEY rotated from any dev value
□ CORS_ORIGINS set to exact prod domains, no wildcards
□ PUBLIC_WS_URL uses wss://, PUBLIC_API_URL uses https://
□ At least one ALERT_* sink configured AND test_alert verified end-to-end
□ Postgres backup job configured and a restore tested into a scratch instance
□ Disk monitoring + alerting on /var/lib/docker volume
□ Log aggregation pointed at the json-file rotated logs (or switch to a syslog/fluentd driver)
□ Healthcheck status surfaced to whatever uptime monitor you trust
□ Replay-against-known-crisis acceptance test passed
□ Runbook reviewed by whoever will carry the pager
```

---

## 7. Bottom line *(v4)*

**Ready for:** Internal trials, controlled paper-trading, demo to design partners, design-partner pilots, hackathon judging, **and a self-hosted production deployment to a hardened single-VM environment** with the §6 checklist completed.

**Still gated for regulated / multi-tenant deployments by:**
1. **§2.2 Real secret storage** — `.env.prod` is acceptable for self-hosted MVP; SOC 2 / ISO 27001 reviewers will require Vault or equivalent.
2. **§3.2 K8s manifests** — defer until you outgrow a single VM. Document the trigger (uptime SLO breach, traffic > X) so the decision isn't ad hoc.
3. **§3.4 Alembic migrations** — operationally fine for now, structurally fragile beyond the next 2–3 schema changes.
4. **§3.5 RBAC** — the single shared bearer is fine for one operator team; the moment a second tenant or auditor needs read-only access, this becomes blocking.

**What v4 actually shipped (closed gaps):**
- TLS reverse proxy with auto-cert (Caddy)
- Postgres backup sidecar with retention and optional S3
- Prometheus + Grafana with provisioned dashboard and alert rules
- k6 sustained load test with hard pass thresholds
- Checkpoint-recovery integration test (6 scenarios)
- Hash-chained audit log + model lineage + verification endpoint
- WebSocket auth gate
- CORS startup assertion
- Operator [DEPLOY.md](DEPLOY.md) and [SECURITY.md](SECURITY.md)

The architecture is sound, the container surface is hardened, the audit trail is tamper-evident, and the deployment is one `docker compose up -d` away. **Remaining work is incremental scaling concerns, not structural gaps.**
