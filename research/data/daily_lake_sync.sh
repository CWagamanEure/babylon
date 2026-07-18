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
  # Promotion leg (activated 2026-07-18) — persist yesterday's wallet-coin-day partition into the
  # incerto Postgres serving layer via the audited incerto-hl-promote CLI (TICKET-0063 wrapper).
  # The ROSTER promotion (scores + cohorts, done on the 1st by hl_promote_daily.sh's monthly leg)
  # is SUPERVISED: a human runs the monthly scoring locally, reviews pool/null-fit, then promotes.
  # So the automated leg does the DAILY wcd only and stands down on the 1st (fail-loud avoided).
  # Idempotent (ON CONFLICT upsert): a re-promoted day is a no-op. Promotion failure alerts (rc=1)
  # but never rolls back the lake sync above.
  echo "--- wcd promotion  $(date -u +%H:%M:%SZ) ---"
  if [ "$(date -u +%d)" = "01" ]; then
    echo "wcd promotion: 1st of month — roster promotion is SUPERVISED; run monthly scoring locally then promote. auto-leg skipped."
  else
    (
      set -a; . /root/incerto.env; set +a
      export HL_CODE_COMMIT="${LAKE_CODE_COMMIT:-unknown}"
      bash /root/incerto/scripts/hl_promote_daily.sh   # no args = commit; --dry-run = dry
    ) || { echo "ERROR: wcd promotion failed"; rc=1; }
  fi
  echo "=== daily_lake_sync done rc=$rc $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  exit $rc
} >> "$LOG" 2>&1
