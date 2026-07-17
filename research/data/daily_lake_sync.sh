#!/bin/bash
# daily_lake_sync.sh — Reservoir -> incerto-datalake-v1 trailing-edge sync (droplet: /root/daily_lake_sync.sh)
# Cron: 30 6 * * * UTC (after Reservoir's ~1-day-lag publish).
# T-1 and T-2 are FORCED (trailing-edge provisional rule: Reservoir republishes recent days, so the
# last two days must be re-ingested unconditionally); T-3 runs without --force as etag-keyed catchup.
# Logs to /root/daily_lake_sync.log; exits nonzero if any day fails.
set -u
LOG=/root/daily_lake_sync.log
{
  echo "=== daily_lake_sync start $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  set -a; source /root/.lake_env; set +a
  PY=/root/lakeenv/bin/python
  rc=0
  for spec in "1 --force" "2 --force" "3"; do
    set -- $spec
    day=$(date -u -d "$1 days ago" +%Y%m%d)
    echo "--- T-$1 day=$day ${2:-}  $(date -u +%H:%M:%SZ) ---"
    "$PY" /root/lake_reservoir_ingest.py day "$day" ${2:-} || { echo "ERROR: day $day failed"; rc=1; }
  done
  # Promotion leg: the incerto CLI deployment is handled through a separate incerto ticket.
  # TODO (future, do not enable here): /root/incerto_promote.sh
  echo "wcd promotion: no-op (incerto_promote.sh pending incerto-side ticket)"
  echo "=== daily_lake_sync done rc=$rc $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  exit $rc
} >> "$LOG" 2>&1
