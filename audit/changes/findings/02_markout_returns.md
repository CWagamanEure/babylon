# 02 — `followable.markout_returns` vs validated `selci_fh.cmd_extract`

Auditor A2 (STATIC). Scope: is `markout_returns` faithful to the `selci_fh.py` extract that
validated the fixed-horizon edge (`audit/EDGE_INVESTIGATION.md`)? "Faithful" = it must reproduce
the per-entry TRAIN array the study ranked wallets on. The study's ranking key is computed on
`cell["tr"]` (entries with `end < t0`); that is the array `markout_returns(..., before_ms=t0)` must
equal.

## Summary
- **1 HIGH** (universe gate divergence — live would rank on a different array than the study).
- **1 MED** (neutralization is caller-contract, not enforced — wrong/absent basket or beta silently diverges).
- **1 LOW** (train-window length / lower-bound is caller config; 30d live vs 31d study default).
- Everything else checked **matches exactly**: the open-event state machine, seam-guard boundary,
  `_close_at` look-ahead semantics, taker/conviction filters, drop_leading default, and the absence
  of a min_hold filter. Clean on those.

---

## HIGH — `markout_returns` adds a `c not in universe` gate that `selci_fh.cmd_extract` does NOT have; with the live config this drops the 4 majors and changes the ranking array
**Where:** `src/babylon/follow/followable.py:148` vs `scripts/selci_fh.py:82-84`.

**The divergence (code-level, certain):**
- `selci_fh.cmd_extract` filters coins by **lookups membership only**:
  `coins = set(lookups)` (line 71), then `if c not in coins: continue` (line 83). There is **no
  alt-universe filter** in the validated extract.
- `markout_returns` filters by **BOTH**: `if c not in universe or c not in lookups: continue`
  (line 148). It additionally requires `c in universe`.

So the two agree **only if the caller passes `universe ⊇ set(lookups)`** (universe a superset of the
priced coins). If `universe` is a strict subset, every entry on a coin in `lookups \ universe` is
silently dropped from the array — a different per-wallet return series, a different eligibility count,
and therefore a different selected roster. That breaks the "live ≡ validated" invariant.

**Concrete live instance (verified by filename comparison, no data loaded):**
- `data/follow/candles/` (what `cmd_cache`/`load_price_lookups` build `lookups` from, default path
  shared by study and live) = **191 coins**.
- `data/follow/alt_universe.txt` (what `main.py:161` loads and passes as `universe`) = **187 coins**.
- The 4 coins in `lookups \ universe` are exactly **BTC, ETH, HYPE, SOL** (the majors); 0 universe
  coins lack candles. So `universe ⊊ set(lookups)` by precisely the 4 highest-volume names.

`selci_fh.cmd_extract` has no major exclusion in code, so its `set(lookups)` from this same candles
dir includes BTC/ETH/HYPE/SOL — the validated TRAIN arrays priced entries on the majors. A live
`markout_returns(universe=alt_universe)` call drops every major entry. For any candidate wallet that
took conviction taker opens in BTC/ETH/SOL/HYPE (very common), the train array, the `min_train`
eligibility, and the rank all change → an unvalidated roster.

**Why it's real:** pure control-flow; the extra `c not in universe` predicate is in the diff
(line 148) and absent from `cmd_extract`. The 4-coin gap is a concrete property of the checked-in
config files. Note `test_markout_skips_unpriceable_coin` only exercises the *lookups* side of the
`or`; nothing pins that `universe` must equal the study's `set(lookups)`.

**Confidence:** HIGH that the code paths differ and that `universe ⊊ lookups` in the live config.
MEDIUM on the magnitude of the resulting ranking change — that depends on how many major-coin
conviction opens the candidate pool has, which I cannot quantify statically (cannot load fills). It
is structurally guaranteed to be non-empty divergence, not merely possible.

**Nuance (doesn't change severity):** one could argue the major exclusion is the *intended*
alt-only philosophy (`skill.py` docstring: "Coins are restricted to the alt universe") and that
`selci_fh` is the one that "leaked" majors in. Even if so, the edge numbers in
`EDGE_INVESTIGATION.md` were validated *with* whatever `set(lookups)` the study used; live must
reproduce that exact set. If the study priced majors, live must price majors to be the validated
rule. The fix is to make the priced-coin set identical, not to argue intent.

**Fix sketch:** make the live caller pass `universe = set(lookups)` for the markout signal (i.e.
the markout pricing universe = the study's candle/basket universe), OR re-run `selci_fh` extract
with a candles cache restricted to `alt_universe` and re-confirm the edge before wiring — then live
and study share one coin set by construction. Do not wire `markout_returns` until the priced-coin
set is proven identical to the validated run. (Cannot verify the study pickle's exact `set(lookups)`
statically; that should be confirmed before deploy.)

---

## MED — neutralization is a caller contract, not enforced: `cmd_extract` ALWAYS neutralizes (beta 1.245, basket over `set(lookups)`); `markout_returns` neutralizes only if a basket is passed, default beta 1.0
**Where:** `followable.py:169-170` vs `selci_fh.py:105-106`.

`cmd_extract` has no `basket=None` branch — every TRAIN/TEST value is
`d*(eout/ein-1)*1e4 - d*beta*_basket_ret_bps(basket, et+lag, end)` with `args.beta` default
**1.245** and `basket = build_basket(candles_dir, sorted(set(lookups)))` (basket spans all 191
coins). `markout_returns` only subtracts the basket term `if basket is not None`, and its default
`beta=1.0`. To reproduce the validated array the caller MUST pass (a) a basket built over the same
coin set as the study (the 191), and (b) `beta=1.245`. The current live wiring is a trap here on two
counts: `SelectionAdapter` defaults `basket=None` (directional) and `main.py` never passes a basket
— so a naive wire of `markout_returns` into selection would produce the **directional**, un-neutralized
series, not the validated neutralized one. And a basket built over `universe` (187) rather than
`set(lookups)` (191) would neutralize against a different index for every entry (same root cause as
the HIGH).

**Confidence:** HIGH on the code asymmetry; the materiality is a wiring decision still to be made.
**Fix sketch:** when wiring markout selection, pass `basket=<built over the study's coin set>` and
`beta=config.beta (=1.245)`; add a parity assertion/test that the markout array equals a stored
`selci_fh` TRAIN array for a fixed wallet/seed.

---

## LOW — train-window lower bound is caller config: study `--train-days 31`, locked live config `train_days=30`
**Where:** `selci_fh.py:77` (`t0 - train_days*86.4e6`, default 31) vs `main.py:61`
(`train_days=30`) feeding `SelectionAdapter._train_ms` / the fills window.

`markout_returns` itself has no lower bound — it prices every open in the `df` it's handed with
`end < before_ms`. With `before_ms=t0` and the `lag+horizon` offset, the oldest relevant entries sit
near `t0 - lag - horizon`, so a 30d vs 31d window only perturbs roughly the oldest ~1 day of train
entries. Minor, and it is a config/caller difference rather than a `markout_returns` logic bug, but
it is one more reason the live array won't be byte-identical to the study extract unless the window
is matched.

**Fix sketch:** align the markout selection train window to whatever the validated run used (31d if
that is the validated number) when wiring.

---

## Checked and MATCHES (no finding)
- **Open-event machine:** both paths call the *same* `skill.open_events` (study via
  `_skill_open_events`, line 51). The entry set, ordering, direction, taker_open, conviction,
  is_leading, and notional are identical by construction — no divergence possible there. The
  flat-state machine mirrors `reconstruct` bit-for-bit (verified by reading both; pinned by
  `tests/test_markout_returns.py`).
- **Seam-guard boundary — exact, no off-by-one:** `markout_returns` excludes when
  `end >= before_ms`, i.e. **includes** `end < before_ms`. With `before_ms=t0` the kept set is
  `{end < t0}`, which is exactly `cmd_extract`'s TRAIN partition `if end < t0` (line 108). `>=`
  vs `<` are complementary at the same boundary; the entry at `end == t0` is excluded by both. The
  study ranked on TRAIN, so reproducing TRAIN (not TEST) is the correct target.
  `test_markout_seam_guard_*` confirms the boundary.
- **`_close_at` look-ahead:** identical imported function; both call `ein=_close_at(.,entry+lag)`
  and `eout=_close_at(.,entry+lag+H)` (study lines 101-102, markout 164-165). Same
  "last fully-closed candle" semantics (`searchsorted(t-CANDLE,"right")-1`), no look-ahead.
- **Filters:** markout defaults `taker_only=True, conviction_only=True` ⇒ keep iff
  `taker_open and conviction`, exactly `cmd_extract`'s `if topen and conv` (line 91).
- **drop_leading:** validated ranking did NOT drop leading opens — `cmd_ci` applies the leading
  mask to TEST only (`te = te[~lead]`, line 535) while the train skill uses the full `tr`. markout
  default `drop_leading=False` matches the ranking path.
- **min_hold:** `cmd_extract` applies no hold filter to opens (only `topen and conv`); the fixed
  horizon replaces the hold concept. `markout_returns` correctly has no `min_hold_ms` (unlike its
  round-trip sibling `followable_returns`). Correct.

## What I could not rule out (static limits)
- The exact coin set inside the study's `scratch_conv/selci_cache.pkl` (cannot unpickle / load).
  I inferred `set(lookups)` from the shared default candles dir; the HIGH finding stands on the
  code-level extra predicate regardless, but the precise major-inclusion of the validated run
  should be confirmed before relying on it.
- The magnitude of roster change from dropping majors (needs fills, which I must not load).
- Note: `SelectionAdapter.returns_fn` currently calls `followable_returns`, NOT `markout_returns`
  — so markout is added but **not yet wired** into live selection. These findings are about the
  faithfulness it must have *before* that wire is made.
