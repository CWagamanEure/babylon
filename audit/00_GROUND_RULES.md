# Adversarial Quant Audit — GROUND RULES (read this FIRST, every agent)

You are one of ~20 independent adversarial auditors of the Babylon copy-trade /
followable-edge system. Your job is to **break the numbers**: find the place where a
believable-but-wrong result, a silent bias, or an engineering bug corrupts the edge
estimate, the selection, or the GO/NO-GO decision. Assume the authors were competent and
already fixed the obvious things — your value is in the second-order mistake they missed.

Read this whole file before doing anything. Then read your assigned task file in
`audit/tasks/NN_*.md`. Write your findings to `audit/findings/NN_<slug>.md`.

---

## 1. RESOURCE SAFETY — non-negotiable (this is why the last run crashed the machine)

The host is an **8 GB RAM Mac** (the droplet is smaller). A prior attempt launched 20 agents
that each eager-loaded a ~1 GB monthly parquet → the box ran out of RAM and crashed. Do not
repeat this. The rules:

1. **NEVER read or load the monthly fills files.** These are the OOM bombs:
   - `other_repo_notes/fills_Feb.parquet` … `fills_Jun.parquet` — **0.5–1 GB each.**
   - `other_repo_notes/superset_wallets.csv` is fine (small). The `.parquet` monthlies are
     BANNED. You do **not** need them — everything is available pre-split.
   Do not `pl.read_parquet`, `scan_parquet`, `head`, `cat`, or `Read` these files. Do not
   even open them to "just check the schema" — the schema is documented in
   `other_repo_notes/README.txt`.

2. **If a probe needs fill data, use the pre-split per-wallet files:**
   `data/follow/fills_his/<wallet>.parquet` — ~32 KB each, 2431 of them. Load **at most ~20
   wallets, one at a time**, and release each before the next.

3. **polars discipline:** always streaming. `pl.scan_parquet(...).collect(engine="streaming")`,
   never an eager `pl.read_parquet` on anything bigger than a single wallet file. Export
   `POLARS_MAX_THREADS=2` before any Python that touches polars. (See the
   `polars non-streaming .collect() OOM` and `partition_by tuple-key` pitfalls.)

4. **Concurrency cap.** Your task file is tagged **[STATIC]** or **[DYNAMIC]**:
   - **[STATIC]** = code/logic review only, *no code execution* → near-zero host RAM. Many
     of these may run in parallel safely.
   - **[DYNAMIC]** = you may run a bounded Python/pytest probe. **At most 2 DYNAMIC agents may
     run at once** (1 is safer). The coordinator enforces this by launching DYNAMIC tasks in
     small serial waves — do not spawn sibling agents yourself.

5. **No full test suite.** Never run bare `pytest`. If your scope needs a test, run only your
   one file: `POLARS_MAX_THREADS=2 .venv/bin/pytest tests/test_<yours>.py -x -q -p no:cacheprovider`.

6. **No services.** Do not start the live runner, the capture service, websockets, or any
   `run_in_background` process. This is a read-and-reason audit, not a live test.

7. **Check before you run.** Before any Python, run `vm_stat | head -5` and, if free+inactive
   pages are low, do NOT run it — fall back to static reasoning and say so in your report.

8. **Bounded output.** Print small summaries (shapes, a few rows, scalars). Never dump a whole
   DataFrame or a multi-MB log to stdout.

**Default to reasoning over execution.** Most findings in a quant audit come from reading the
code and constructing a failure scenario on paper, not from running it. Only run a probe when
a specific claim genuinely cannot be settled by reading.

> Concretely safe probe shell:
> ```bash
> POLARS_MAX_THREADS=2 timeout 120 .venv/bin/python - <<'PY'
> import polars as pl
> w = "0x000007b83bf80adcc02897528403c640991a6544"
> df = pl.scan_parquet(f"data/follow/fills_his/{w}.parquet").collect(engine="streaming")
> print(df.shape, df.columns)
> PY
> ```

---

## 2. WHAT YOU ARE AUDITING — orienting facts

This system measures whether a **followable copy-trade edge** exists on Hyperliquid and, if
so, selects wallets to mirror in a live paper experiment. The audit-critical structure:

- **Blast radius bounds severity.** The **GO/NO-GO gate** (`measure → decide`, hash-chained,
  read-once, min-n recomputed) is what declares an edge real. **Selection** (which wallets to
  follow) only affects *power*. So:
  - A bug that can make the gate emit a **false GO** = **CRITICAL** (fabricates an edge).
  - A bug that only degrades selection = **HIGH at most** (loses power → biases toward
    INCONCLUSIVE, not a false positive). Say which bucket your finding lands in.
- The **historical edge estimate** (`scripts/edge_sweep.py`, `convergence_*.py`,
  `other_repo_notes/README.txt`) is the offline claim that the edge is ~+15–20 bp/RT
  net-relevant. If that number is inflated by a bias, every downstream decision inherits it.
- The **live capture** subsystem (`src/babylon/follow/capture/`) is the newer, forward
  markout scorer. It feeds **selection only** (per `docs/LIVE_CAPTURE.md`), so its bugs are
  power-losses unless you can show it leaks into the gate.

Read `docs/LIVE_CAPTURE.md` and `docs/LIVE_FOLLOW.md` for the design and the prior 3-agent
audit outcome. Read `other_repo_notes/README.txt` for the offline universe construction.

---

## 3. KNOWN ISSUES — do NOT just re-report these (go deeper or find them incompletely fixed)

These are already documented (memory: `babylon-pitfalls`) and most are fixed. Re-listing one
as a "finding" is worthless. **Valuable** = showing a fix is *incomplete*, has a gap, or was
reintroduced elsewhere.

1. Frozen-pool survivorship (fixed: rolling past-only universe, commit history).
2. Wallet's-own vs follower's-lagged pricing (priced at fill_t+lag).
3. edge-over-field cancels constant cost (so headline P&L is selected-net-of-cost).
4. Look-ahead pricing (use last fully-closed candle `_close_at`).
5. Seam leakage (count only RTs closed before T0, `before_ms`).
6. Eligibility on closed-RT count → gate on RAW ACTIVITY (commit fe44463).
7. Sortino EPS-explosion (floor downside-dev, commit 9ddf901).
8. No CI / wrong bootstrap → wallet-cluster bootstrap (resample wallets).
9. Coverage bias (~73% priceable; match the tradeable subset).
10. Dangling / MTM-at-cutoff open positions (commits 9ddf901/11a249d).
11. startPosition mis-seeding (his export seeds 0 → hold out leading position).
12. polars non-streaming `.collect()` OOM (use streaming).
13. `partition_by(as_dict=True)` tuple-key regression → silent `elig=0`.
14. Fills pagination dropping same-ms fills (dedup by tid, refetch from last_t).
15. Float residual staling positions (reset to exact 0; causal running-max tolerance).

---

## 4. REPORTING FORMAT — write to `audit/findings/NN_<slug>.md`

Use this structure. One file per agent. Rank findings most-severe first.

```
# Audit NN — <area>  (agent: <task slug>)

## Summary
<2–4 sentences: what you examined, did you find anything that moves a number, top severity.>

## Findings

### F1 — <one-line defect>  [CRITICAL|HIGH|MED|LOW|NIT]
- **Where:** path/file.py:LINE (function)
- **Blast radius:** gate-false-GO | selection-power | offline-estimate | reporting-only
- **Failure scenario:** concrete inputs/state → the wrong output it produces. Be specific
  enough to reproduce on paper. ("If a wallet's first in-window fill is a partial close of a
  position opened pre-window, _positions_for seeds dir from … → ret_bps sign flips → …")
- **Why it's real (not theoretical):** the code path that allows it; whether existing guards
  miss it.
- **Confidence:** high | medium | low (+ what would raise it)
- **Fix sketch:** the minimal change.

### F2 …
```

Rules for findings:
- **No speculation dressed as fact.** If you couldn't confirm, mark confidence low and say
  exactly what probe/data would settle it.
- **Tie every claim to a line.** "Seems biased" with no `file:line` and no scenario is noise.
- **A clean bill is a valid result.** If your area holds up, say so and list what you checked
  and what you could not rule out. Don't manufacture findings to look productive.
- **Don't fix anything.** This is audit-only. Propose fixes; do not edit source. (Editing also
  risks colliding with sibling agents.)

When done, your final message back to the coordinator should be just the path to your findings
file plus a one-line headline (top severity + count), nothing more.
