#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
#  pg_dump → /backups/velure-YYYYmmddTHHMMSSZ.sql.gz
#  Retention: keep N most recent (default 14)
#  Optional: aws s3 cp to ${BACKUP_S3_URI}/  if env present
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

: "${POSTGRES_HOST:?POSTGRES_HOST is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"

RETENTION="${BACKUP_RETENTION_COUNT:-14}"
DEST_DIR="${BACKUP_DIR:-/backups}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="${DEST_DIR}/velure-${TS}.sql.gz"

export PGPASSWORD="${POSTGRES_PASSWORD}"

echo "[$(date -u +%FT%TZ)] backup start → ${FILE}"

# --no-owner / --no-acl keeps the dump portable across roles
pg_dump \
    --host="${POSTGRES_HOST}" \
    --port="${POSTGRES_PORT:-5432}" \
    --username="${POSTGRES_USER}" \
    --dbname="${POSTGRES_DB}" \
    --no-owner --no-acl \
    --format=plain \
    | gzip -9 > "${FILE}"

SIZE="$(du -h "${FILE}" | cut -f1)"
echo "[$(date -u +%FT%TZ)] backup ok size=${SIZE}"

# Retention — delete oldest dumps beyond N
ls -1t "${DEST_DIR}"/velure-*.sql.gz 2>/dev/null | tail -n +$((RETENTION + 1)) | xargs -r rm -f -- || true
echo "[$(date -u +%FT%TZ)] retention applied keep=${RETENTION}"

# Optional offsite copy
if [[ -n "${BACKUP_S3_URI:-}" ]]; then
    echo "[$(date -u +%FT%TZ)] s3 upload → ${BACKUP_S3_URI}/$(basename "${FILE}")"
    aws s3 cp "${FILE}" "${BACKUP_S3_URI}/$(basename "${FILE}")" --only-show-errors
    echo "[$(date -u +%FT%TZ)] s3 upload ok"
fi

echo "[$(date -u +%FT%TZ)] backup complete"
