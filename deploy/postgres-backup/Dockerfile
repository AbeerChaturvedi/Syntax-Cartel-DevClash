# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────
#  Project Velure — Postgres backup sidecar
#
#  pg_dump → gzip → /backups (volume) on a cron schedule with retention.
#  Optional S3 upload via awscli if AWS_* env vars are set.
# ─────────────────────────────────────────────────────────────────────

FROM postgres:16-alpine

RUN apk add --no-cache \
        bash \
        coreutils \
        findutils \
        tini \
        gzip \
        aws-cli \
    && addgroup -S -g 10001 backup \
    && adduser  -S -u 10001 -G backup -h /backups backup \
    && mkdir -p /backups \
    && chown -R backup:backup /backups

COPY backup.sh /usr/local/bin/backup.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/entrypoint.sh

USER backup
WORKDIR /backups

ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/entrypoint.sh"]
