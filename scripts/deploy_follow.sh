#!/usr/bin/env bash
# Deploy the forward copy-trade paper experiment to the droplet.
# Copies code + the experiment data the LIVE run needs (candidate pool, universe, candles
# — NOT the 888MB fills, which RestFillsProvider fetches fresh), then `uv sync`.
#
#   ./scripts/deploy_follow.sh            # sync + install
#   DROPLET=root@host DEST=/root/bablyon ./scripts/deploy_follow.sh
set -euo pipefail

DROPLET="${DROPLET:-root@104.248.116.0}"
KEY="${KEY:-$HOME/.ssh/id_ed25519}"
DEST="${DEST:-/root/bablyon}"
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new"

echo ">>> [1/3] syncing code -> $DROPLET:$DEST"
rsync -az --delete -e "$SSH" \
  --exclude '.venv' --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '/data' --exclude '.pytest_cache' --exclude '.mypy_cache' --exclude '.ruff_cache' \
  ./ "$DROPLET:$DEST/"

echo ">>> [2/3] syncing experiment data (pool + universe + candles, ~17MB)"
$SSH "$DROPLET" "mkdir -p $DEST/data/follow/live"
rsync -az -e "$SSH" \
  data/follow/long_hold_wallets.csv data/follow/alt_universe.txt "$DROPLET:$DEST/data/follow/"
rsync -az --delete -e "$SSH" data/follow/candles "$DROPLET:$DEST/data/follow/"

echo ">>> [3/3] uv sync on droplet"
$SSH "$DROPLET" "cd $DEST && ~/.local/bin/uv sync"

echo ">>> deploy done. Smoke:  $SSH $DROPLET 'cd $DEST && ~/.local/bin/uv run python -m babylon.follow.main --dry-run'"
