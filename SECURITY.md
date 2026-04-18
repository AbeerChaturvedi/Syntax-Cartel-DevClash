# Security model — Project Velure

## Threat model in one paragraph

Velure ingests market data, computes risk scores, and dispatches alerts. The system does **not** route orders or hold customer funds. The threats we defend against are: (a) **unauthorized read** of risk signals before they're public, (b) **tampering with audit trails** so a missed warning can be denied or fabricated, (c) **denial of service** that leaves operators blind during a real crisis, and (d) **credential theft** from compromised hosts. We do *not* defend against an adversary with root on the deploy host — at that point all bets are off and the response is incident, not prevention.

---

## Trust boundaries

```
┌──────────────────────────────────────────────────────────────────┐
│  Internet — UNTRUSTED                                            │
└──────────────────────────────────────────────────────────────────┘
                       │  HTTPS / WSS only
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Caddy (TLS terminator)                                          │
│  · Let's Encrypt cert mgmt                                       │
│  · HSTS, CSP, X-Frame-Options, Referrer-Policy                   │
│  · Strips Server header                                          │
│  · cap_drop ALL + NET_BIND_SERVICE only                          │
└──────────────────────────────────────────────────────────────────┘
                       │  internal docker network (velure_internal)
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Backend (FastAPI)                                               │
│  · X-API-Key gate (REST + WS) on every non-public endpoint       │
│  · Per-IP rate limit (sliding window, default 120 RPM)           │
│  · CORS allowlist enforced at startup (no '*' with API key set)  │
│  · cap_drop ALL, non-root uid 10001, tini PID 1                  │
└──────────────────────────────────────────────────────────────────┘
                       │  asyncpg / Redis password auth
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Postgres + Redis — internal-only, no host port binding          │
│  · Postgres: requires POSTGRES_PASSWORD                          │
│  · Redis: requirepass REDIS_PASSWORD                             │
│  · audit_log is hash-chained                                     │
└──────────────────────────────────────────────────────────────────┘
```

---

## What we enforce

### Authentication
- **REST:** `X-API-Key` header validated by [SecurityMiddleware](backend/utils/middleware.py). Missing/invalid → 401.
- **WebSocket:** the same key, accepted via either `X-API-Key` header (preferred) or `?api_key=…` query param (browser fallback). Bad key → connection closed with policy-violation 1008 *before* allocation.
- **No anonymous access** in production: setting `VELURE_API_KEY=""` is a dev-mode signal and the system flags it in `/health`.
- **Rate limit:** 120 RPM per IP by default. Exceeded → 429 with `Retry-After: 60`. WS upgrades and `/health` are exempt so an outage doesn't lock everyone out.

### Authorization
- **Single-tenant** today. The API key is a bearer — anyone with it has full read + admin (stress-test, replay, checkpoint, alerting test).
- **RBAC is on the roadmap** (PRODUCTION_READINESS §3.5) — per-consumer keys with scopes (`read:stream`, `admin:test_alert`, `admin:replay`). Not yet implemented; do not share the API key beyond a single trusted operator group until that lands.

### Confidentiality
- **TLS everywhere:** Caddy auto-provisions Let's Encrypt certs and enforces HSTS. The TLS overlay strips host port bindings on backend/frontend so they're only reachable through the proxy.
- **Internal services:** Postgres and Redis are bound to the internal docker network only — no host port published. Even on a multi-tenant host, neighbours cannot dial them.
- **Secrets at rest:** read from `.env.prod` (or whichever secret manager mounts to that path). Never baked into images.

### Integrity
- **Audit log is hash-chained.** Every row's `this_hash = sha256(prev_hash || canonical_payload)`. Walk the chain via `GET /api/audit/verify`. Mutation of any row breaks the chain at that row and every row after.
- **Model lineage** persists `(model_version, checkpoint_hash)` so every audit row stamps the *exact* model state that produced it. Re-running an alert is a single deterministic computation.
- **Checkpoint atomicity:** [CheckpointManager](backend/utils/model_persistence.py) writes to a temp dir and `rename()`s to `current/` on success. A crash mid-write leaves the previous good `current/` intact.

### Availability
- **Resource limits** on every service (`deploy.resources.limits`) so a runaway model can't OOM the host.
- **Circuit breakers** for Redis and Postgres. When tripped, the pipeline degrades to in-process fallback rather than crashing.
- **Healthchecks** with bounded `start_period` so the container scheduler doesn't kill a slow-starting model loop.
- **Log rotation:** `json-file` driver capped at 50 MB × 5 per service. No silent disk-fill.

### Container hardening
- All services run as non-root uid `10001`.
- `cap_drop: ALL` on every service. Caddy adds back only `NET_BIND_SERVICE` for ports 80/443. Postgres-backup, Grafana, Prometheus drop everything.
- `security_opt: no-new-privileges:true` everywhere.
- `read_only: true` + `tmpfs` for Redis + frontend (where the runtime allows it).
- Multi-stage Dockerfiles: build deps (gcc, libpq-dev) live only in the builder layer and are not present in runtime images.

---

## What we do *not* enforce yet

These are tracked in [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) §2 and §3:

- **Mutual TLS / mTLS** between services — the internal network is the boundary today.
- **Vault / secret-manager integration** — `.env.prod` is the current model. Acceptable on a hardened host; not acceptable for SOC 2.
- **Alembic migrations** — schema is bootstrap-only via init.d. Operators apply migrations by hand.
- **Per-consumer API keys + scopes** — single shared bearer today.
- **WAF / bot-mitigation rules** — Caddy gives us TLS + headers; layer 7 protection requires a separate WAF.
- **Vulnerability scanning of built images** — wire `trivy` into CI before promoting an image to prod.
- **Postgres CDC for real-time audit replication** — periodic `pg_dump` is the current backup story.

---

## Reporting a vulnerability

Send details to `security@velure.example.com` (or a private channel of your choosing — adjust this file before publishing). Include:

- The vector (URL, request, env conditions)
- Impact (read / write / DoS / RCE / privilege escalation)
- Steps to reproduce
- Whether you've shared the finding elsewhere

We commit to acknowledging within 72 hours and providing a remediation timeline within 7 days for confirmed reports. We will not pursue legal action against good-faith researchers operating within the standard disclosure norms.

---

## Operator hygiene checklist

The most common compromise vector is operator misconfiguration, not exploited code. Before exposing the system:

- [ ] `VELURE_API_KEY` rotated from any value that ever appeared in dev
- [ ] `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `GRAFANA_ADMIN_PASSWORD` are unique and from a CSPRNG (`openssl rand -base64 36`)
- [ ] `CORS_ORIGINS` is an explicit allowlist — verified by curling with `Origin: https://attacker.example` and confirming the response lacks `Access-Control-Allow-Origin`
- [ ] `.env.prod` is `chmod 600` and not in version control
- [ ] TLS certificates are valid (`curl -v https://${DOMAIN_API}` shows the right CN and OCSP staple)
- [ ] `GET /api/audit/verify` returns `intact: true` on a fresh deploy
- [ ] At least one alert sink is wired and `POST /api/alerting/test` succeeds end-to-end
- [ ] Backup volume has space — confirmed by inspecting `postgres_backups` mount
- [ ] Restore drill executed against a scratch DB (see [DEPLOY.md](DEPLOY.md) §4.3) and the row counts match
- [ ] Grafana admin password not the default; anonymous access disabled (verified by checking `/api/org` without cookies returns 401)

If any item is unchecked, **do not expose the system to untrusted networks.**
