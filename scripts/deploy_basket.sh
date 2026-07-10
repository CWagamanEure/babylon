#!/usr/bin/env bash
# Deploy the rolling-WF basket paper follower to the droplet (option A: batch pipeline stays
# local; the droplet only runs the follower). Also the MONTHLY REFRESH path: after re-running
# `python -m research.data.rolling_wf live` locally, run this script again — it ships the new
# basket and restarts the service (open tranches keep their clocks via the checkpoint).
#
#   ./scripts/deploy_basket.sh
#   DROPLET=root@host DEST=/root/bablyon ./scripts/deploy_basket.sh
set -euo pipefail

DROPLET="${DROPLET:-root@167.71.29.107}"
DEST="${DEST:-/root/bablyon}"
SSH="ssh -o StrictHostKeyChecking=accept-new"
BASKET="data/derived/rolling_wf/live_basket.parquet"

[ -f "$BASKET" ] || { echo "missing $BASKET — run: python -m research.data.rolling_wf live"; exit 1; }

echo ">>> [1/5] syncing code -> $DROPLET:$DEST"
rsync -az --delete -e "$SSH" \
  --exclude '.venv' --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '/data' --exclude '/.tmp' --exclude '/scratch_conv' \
  --exclude '.pytest_cache' --exclude '.mypy_cache' --exclude '.ruff_cache' \
  ./ "$DROPLET:$DEST/"

echo ">>> [2/5] shipping the frozen basket"
$SSH "$DROPLET" "mkdir -p $DEST/data/derived/rolling_wf $DEST/data/follow/basket_live"
rsync -az -e "$SSH" "$BASKET" "$DROPLET:$DEST/data/derived/rolling_wf/"

echo ">>> [3/5] uv sync on droplet (installs uv if missing)"
$SSH "$DROPLET" "command -v ~/.local/bin/uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh"
$SSH "$DROPLET" "cd $DEST && ~/.local/bin/uv sync --no-dev"

echo ">>> [4/5] installing systemd unit"
rsync -az -e "$SSH" deploy/babylon-basket.service "$DROPLET:/etc/systemd/system/"
$SSH "$DROPLET" "systemctl daemon-reload && systemctl enable babylon-basket"

echo ">>> [5/5] smoke (dry-run) then (re)start"
$SSH "$DROPLET" "cd $DEST && .venv/bin/python -m babylon.follow.basket_main --dry-run --state-dir data/follow/basket_live"
$SSH "$DROPLET" "systemctl restart babylon-basket && sleep 5 && systemctl is-active babylon-basket"

echo ">>> deployed. Watch:  $SSH $DROPLET 'tail -f $DEST/data/follow/basket_live.log'"
