#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
#  Loop forever: backup → sleep BACKUP_INTERVAL_SEC → repeat
#  Default 24h. Set BACKUP_INTERVAL_SEC=3600 for hourly during testing.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

INTERVAL="${BACKUP_INTERVAL_SEC:-86400}"

# Run an immediate backup on container start so the volume isn't empty
# during the first cycle. Failures don't kill the loop — log and retry.
while true; do
    if /usr/local/bin/backup.sh; then
        :
    else
        echo "[$(date -u +%FT%TZ)] backup failed exit=$?  — retrying after interval"
    fi
    echo "[$(date -u +%FT%TZ)] sleeping ${INTERVAL}s until next backup"
    sleep "${INTERVAL}"
done
