# syntax=docker/dockerfile:1.7
# ──────────────────────────────────────────────────────────────────────
#  Project Velure — Frontend (Next.js 16 standalone, non-root, tini)
# ──────────────────────────────────────────────────────────────────────

# ─── Stage 1: deps — npm ci against package-lock only ─────────────────
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

# ─── Stage 2: builder — produce .next/standalone ──────────────────────
FROM node:22-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ─── Stage 3: runner — slim runtime, non-root, signal-aware ───────────
FROM node:22-alpine AS runner

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# tini = PID 1; wget = lightweight healthcheck (already in alpine)
RUN apk add --no-cache tini wget && \
    addgroup --system --gid 10001 velure && \
    adduser  --system --uid 10001 --ingroup velure --home /app velure

WORKDIR /app

# Copy only the standalone output — much smaller than the full build tree
COPY --from=builder --chown=velure:velure /app/public ./public
COPY --from=builder --chown=velure:velure /app/.next/standalone ./
COPY --from=builder --chown=velure:velure /app/.next/static ./.next/static

USER velure

EXPOSE 3000

HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:3000/ || exit 1

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "server.js"]
