# Audit 10 — Cost & netting model  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/10_cost.md`.

## Scope
The gross mid-to-mid edge is ~+15–20 bp/RT; the round-trip cost (`--cost-bps 8`) is what decides
tradeability. If cost is understated or netting is wrong, a "tradeable" edge isn't.

## Read
- `scripts/edge_sweep.py` — `--cost-bps 8.0`, `net = sm - cost`.
- `src/babylon/sizing/` (`edge.py`, `sizer.py`, `kelly.py`), `src/babylon/execution/` (`fill_model.py`, `paper.py`).
- `docs/LIVE_CAPTURE.md` must-fix #3 (cost + netting; "coherent by construction" is FALSE).

## Adversarial hypotheses to test
1. **Is 8 bp the real round-trip cost?** Decompose: maker/taker fee × 2 legs + half-spread × 2 +
   impact. On thin alts (the universe is non-majors!) the spread alone can exceed 8 bp. Is the cost
   a flat 8 bp or per-coin? A flat cost on a thin-alt universe understates cost where edge is
   thinnest → the marginal selected wallet may be net-negative. **Likely real finding.**
2. **Mid vs aggressing-touch.** The score marks at mid; we actually cross the spread (pay the
   touch). Prior audit: "mark at the aggressing touch not mid." Does any reported edge use mid
   while claiming to be net? That's a half-spread overstatement per leg.
3. **Netting per coin.** We net exposures per coin; the per-RT cost model assumes each RT pays full
   round-trip cost. If two RTs in the same coin net, we overcount cost (conservative) OR if we
   assume netting we don't actually achieve, we undercount. Which direction, and is it material?
4. **edge-over-field hides cost (known #3).** Confirm no headline uses `edge_v_field` as the P&L
   number — that cancels the constant cost and is NOT deployable P&L. The deployable number is
   `net`. Check which number the docs/decision quote.
5. **Funding.** Perps pay funding over a hold. With `min_hold_ms = 1h` and some multi-day holds,
   is funding in the cost at all? If omitted, longer holds are overstated.
6. **Cost in the live sizer.** Does `sizing/` apply the same cost the offline edge was netted at?
   A sizer that assumes lower cost over-levers the thin-edge tail.

## RAM
STATIC.
