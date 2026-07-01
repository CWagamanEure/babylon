# Deployed harvest+gate adversarial audit (round 2) — live-integration focus

The code under audit is `src/babylon/follow/` = EXACTLY what's deployed on the droplet (rsynced,
running the live paper experiment). Round-1 audited components in isolation and missed TWO live
bugs that made it trade nothing: (a) `min_tranche` floor ($20) capped out every $3-15 tranche;
(b) watcher cursor=0 replayed weeks-old opens as fresh. This round hunts the SILENT-FAILURE class
at the wiring seams.

## GROUND RULES (all agents)
- RAM-SAFE: NO monthly parquets, NO whole-pool loads, NO scripts/ or scratch_conv/, NO jobs on the
  droplet (it runs the live service). Only TARGETED `.venv/bin/python -m pytest tests/test_X.py` +
  read source. A prior run OOM'd the box.
- Blast-radius severity: HIGHEST = silently trades NOTHING / trades the WRONG thing / mis-measures
  the edge / fabricates a GO. LOWER = crash or power-loss.
- Report: severity-ranked. Each: `file:line`, one-sentence defect, CONCRETE failure scenario
  (inputs → wrong behavior), CONFIRMED vs PLAUSIBLE. End: is this component sound? Findings, not prose.
- Do NOT edit code.

## Agents
- B1 live wiring (live.py build/run/reroll, seed_cursors fresh-vs-resume, caps, checkpoint/resume)
- B2 watcher poll/detect (cursor advance, dedup, miss/double-emit, startPos, rate-limit interaction)
- B3 ledger caps + lifecycle (harvest.py rationing, expiry, stuck/leaked tranches, exit sizing)
- B4 runner executor loop (harvest_runner.py delivery dedup, cash, unfilled orders, restart)
- B5 selection + chunked roll (scheduler/roll_worker/selection parity, eligibility, seam guard, scan)
- B6 gate soundness (gate_feed/experiment two-condition GO, realized-net leg, empty guards)
- B7 strategy fidelity end-to-end (does live == validated operating point; biggest threat to validity)
