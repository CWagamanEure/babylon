# A3 — Is the `selci_fh.py` `_open_events` refactor lossless?

**Headline: CLEAN BILL on the refactor — tuple order, import surface, and call sites all check out;
2 LOW caveats + 1 coverage caveat that static review cannot fully close.**

Scope: verify the new thin-wrapper `_open_events` (delegates to `skill.open_events`) is byte-identical
to the validated study. STATIC only — no execution, no data loads.

Important constraint on this audit: `scripts/selci_fh.py` is **untracked** (`git status` shows `??`),
the diff patch (`audit/changes/the_diff.patch`) contains ONLY `followable.py` + `skill.py`, and no
`.bak`/`.orig` of the old inline `_open_events` exists anywhere in the tree. **I therefore cannot
diff the new wrapper against the old local function directly.** All conclusions below reason about
internal consistency of the current file + faithfulness of the wrapper mapping, not a literal
old-vs-new source diff. This is the single biggest limit on the strength of the "byte-identical" claim.

---

## 1. Tuple order — NO swap. (CLEAN)

`skill.OpenEvent` field order (skill.py:133-139):
`(entry_t, direction, taker_open, conviction, is_leading, notional)`.

Wrapper (selci_fh.py:50-51) builds the tuple **by attribute name**, not by position:
`(e.entry_t, e.direction, e.taker_open, e.conviction, e.is_leading, e.notional)`.

Call site (cmd_extract, selci_fh.py:86) unpacks:
`for et, d, topen, conv, lead, notl in _open_events(...)`.

Mapping is exact and the variable names are self-checking:
`et=entry_t, d=direction, topen=taker_open, conv=conviction, lead=is_leading, notl=notional`.
Downstream usage is consistent with these semantics: the eligibility gate `if topen and conv`
(selci_fh.py:91) = "taker-opened AND non-TWAP/non-liquidation conviction", exactly the study's
intent; the appended record `(c, et, d, lead, notl)` (line 92) matches the inline comment
`# (coin, entry_t, dir, is_leading, notional)` (line 80).

Because the wrapper reads fields by name, an OpenEvent field-reordering could never silently
mis-position a value here — it would only matter if a field's *semantics* differed from what the old
function placed in that slot, and the names align perfectly (topen↔taker_open, conv↔conviction,
lead↔is_leading, notl↔notional). **No topen/conv or lead/notl swap is possible.**

Argument order on the call into the skill is also correct: wrapper signature
`_open_events(times, px, sz, side, crossed, startpos, hashes)` forwards positionally to
`skill.open_events(times, px, sz, side, crossed, startpos, hashes)` (skill.py:142-145), and
cmd_extract passes `time, px, sz, side, crossed, startPosition, hash` in that same order
(lines 87-90). Aligned.

---

## 2. `len(startpos)` → `startpos.size` — equivalent on the real inputs. (LOW / contract note)

`skill.open_events` uses `... if startpos is not None and startpos.size else 0.0` (skill.py:157),
where the old local code (per the task brief) used `len(startpos)`.

For the ONLY input this script ever supplies — `g["startPosition"].to_numpy()` (selci_fh.py:89), a
**1-D ndarray** — `len(arr) == arr.shape[0] == arr.size`. The guard and the subsequent `startpos[0]`
access are identical in both forms (empty array → both falsy → `pos = 0.0`; non-empty → both index
`[0]`). **No divergence on the study's data path.**

Where they *could* differ (none reached here, hence LOW not a bug):
- `startpos` a Python **list** → `.size` raises `AttributeError` where `len()` worked. Not reached:
  callers always pass ndarrays (study via `.to_numpy()`; live `markout_returns` likewise).
- 0-d scalar array → `len()` raises, `.size==1`. Not reached: a polars column → ndarray is never 0-d.
- 2-D array → `len`=rows, `.size`=rows×cols. Not reached: always 1-D.

Net: an implicit contract change (now requires a `.size` attribute, i.e. ndarray-only) but **zero
behavioral difference for every actual call site.** Worth a one-line note, not a fix.

---

## 3. `ZERO_HASH` / `_REL_TOL` after the import change — no undefined refs. (CLEAN)

New import (selci_fh.py:31): `from babylon.follow.skill import _basket_ret_bps, build_basket,
open_events as _skill_open_events`. `ZERO_HASH` and `_REL_TOL` are NOT imported.

`grep` over `scripts/selci_fh.py` for `ZERO_HASH` and `_REL_TOL` → **zero hits.** Both symbols were
only ever needed by the inline state machine (conviction = hash≠ZERO_HASH; flat-tolerance = _REL_TOL·
max|pos|), and that machine now lives entirely inside `skill.open_events` (skill.py:156, 159, 164).
The script consumes only the precomputed `conv` flag and never recomputes tolerance. **No
NameError-able reference remains.**

---

## 4. Coverage: k>0 and the other modes — structurally safe, with one residual static-review gap.

**Other modes (ci / panel / persist / sizeedge / coincost):** all of them only `read_text()` the
`selci_fh.jsonl` produced by `extract` and operate on those arrays (e.g. cmd_ci:517, cmd_panel:346,
cmd_persist:288, cmd_sizeedge:474, cmd_coincost:410). **None of them call `_open_events`.** They are
pure consumers. Therefore: if `extract`'s jsonl is byte-identical, every downstream mode is
byte-identical by construction. The refactor's blast radius collapses to "does extract still emit the
same jsonl?" — i.e. "does `open_events` emit the same `(et,d,topen,conv,lead,notl)` tuples?"

**k-dependence:** `open_events` has no `k` parameter and is a pure deterministic function of the
per-coin fill arrays. `k` only selects the boundary window `t0,t1` and the train lookback
(`df = provider(w, t0 - train_days*86_400_000, t1)`, selci_fh.py:77) — i.e. it changes *which fill
subsequence* is fed in, not the code path inside `open_events`. So 40 k=0 jobs validating extract is
strong: the function under test is k-agnostic and downstream is k-agnostic w.r.t. the refactor.

**The residual gap I cannot close statically:** k>0 windows feed *different* input sequences (different
`startPosition[0]` seeds, different lengths, different scale-in/flip/partial-close interleavings). The
branches in `open_events` (open-from-flat, same-side add → no emit, partial close, full close, flip →
emit opposite, `is_leading=not seen_close`, conviction via ZERO_HASH, taker via `crossed`, empty-seed)
are generic micro-patterns that a 40-job k=0 sweep over many wallets/coins almost certainly exercises
exhaustively — but "almost certainly" is not a proof. The specific thing k=0-only validation cannot
rule out is a **data-dependent float-tolerance / seed edge case**: the running-max tol anchoring
(`tol = max(_REL_TOL*maxabs, 1e-15)`, skill.py:163-164) classifies a near-flat residual as flat in a
way that depends on the realized `|pos|` trajectory. If the *old* inline function had ever anchored
tol differently (e.g. full-sequence cumsum max — a pattern the `reconstruct` docstring at skill.py:74-77
explicitly says it was changed AWAY from), the two would diverge only on sequences where `|pos|` peaks
AFTER a marginal close — and such a sequence could first appear in a k>0 window. **I cannot confirm or
deny this**, because the old source is not in git (see scope note). This is the one place the
"byte-identical, proven on 40 k=0 jobs" claim rests on extrapolation rather than coverage.

Recommendation (not a code fix): before arming live, run the same byte-diff on a sample of k>0 jobs
(at least one per boundary), since extract is cheap relative to the fill read and this is the only
untested axis. If the old `_open_events` source can be recovered (reflog / editor history), a literal
old-vs-new textual diff of the open-detection branch would close this far more cheaply than a re-run.

---

## Summary
| # | Check | Verdict |
|---|-------|---------|
| 1 | Tuple order vs unpack | CLEAN — by-name mapping, no swap |
| 2 | `len(startpos)`→`.size` | LOW — equivalent for 1-D ndarray (always the case); contract now ndarray-only |
| 3 | ZERO_HASH/_REL_TOL imports | CLEAN — no remaining refs in selci_fh |
| 4 | k>0 / other-mode coverage | Structurally safe (modes are pure consumers; fn is k-agnostic); residual float-tol/seed edge case unprovable statically + old source not in git |

No CRITICAL/HIGH/MED defect found in the refactor itself. The only thing standing between this and a
fully airtight "lossless" verdict is (a) the missing old source for a literal diff and (b) k=0-only
empirical coverage of the float-tolerance path.
