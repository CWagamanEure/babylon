# Finding 01 — `skill.open_events` vs validated `reconstruct` state machine

**Auditor:** A1 (static — read+reason only; no execution, no data loads)
**Files:** `src/babylon/follow/skill.py` (`open_events` L142–181 vs `reconstruct` L61–120);
cross-checked consumers `followable.markout_returns` (L128–172) and `scripts/selci_fh.py`
(`_open_events` L46–51, `cmd_extract` L66–117).

## Headline
CLEAN BILL on the load-bearing path: the signed-contract state machine in `open_events` is
bit-for-bit identical to `reconstruct`, and the two markout consumers (live `markout_returns`,
study `selci_fh`) call the SAME `open_events`, so `live ≡ validated` holds by construction. Two
LOW/NIT latent warts noted; no CRITICAL/HIGH/MED.

---

## What I verified (the state machine is identical)

Line-by-line, every `pos`-transition / tolerance / branch in `open_events` matches `reconstruct`:

| concern | reconstruct | open_events | match |
|---|---|---|---|
| signed fill | L79 `where(side=="B", sz, -sz)` | L153 same | ✓ |
| seed `pos` | L84 `startpos[0] or 0` | L157 same | ✓ |
| running causal `maxabs`/`tol` | L93–94 | L163–164 (identical expr) | ✓ |
| open/add test | L95 `pos==0 or (d>0)==(pos>0)` | L165 same | ✓ |
| `pos += d` on open/add | L100 | L169 | ✓ |
| close size | L104 `min(abs(d),abs(pos))` | L171 same | ✓ |
| `pos += close if pos<0 else -close` | L107 | L172 | ✓ |
| close detect `abs(pos)<tol` | L108 | L173 | ✓ |
| exact-zero reset `pos=0.0` | L113 | L175 | ✓ |
| flip detect `leftover>tol` | L115 | L177 | ✓ |
| flip seed `pos=leftover if d>0 else -leftover` | L119 | L180 | ✓ |

Adversarial cases reasoned through:

- **Flip (long→short in one fill):** seed flat, fill1 d=+10, fill2 d=−25. Both close the +10
  (`seen_close`/close-emit), `leftover=15>tol`, both open the opposite side with
  `direction = 1 if d>0 else -1` = **−1 (short)** and bet-size `leftover*px = 15*px`. Direction,
  entry_t (= flip-fill time), and notional all match `reconstruct`'s `held_dir`/`et`/(`en/es=px`,
  size `leftover`). ✓
- **Add (same-side scale-in):** `if pos==0` is False on an add → **no emit**; only `pos += d`.
  Matches `reconstruct` (accumulates en/es, no new Position). ✓
- **Exact-zero close + float residual:** both reset `pos=0.0` exactly inside `abs(pos)<tol`, using
  the same RUNNING (causal) `maxabs`-anchored `tol`. No future-dependent tolerance; identical to
  `reconstruct` (and to `capture.CoinStepper` per the docstring). ✓
- **`is_leading` (the new field):** `is_leading = not seen_close`, and `seen_close=True` is set the
  instant `abs(pos)<tol` (close completes) — i.e. BEFORE the flip-open emit, which is hardcoded
  `is_leading=False`. So `is_leading=True` is raised for **exactly one** event: the first from-flat
  open when no close has yet been observed. Constructed flip-before-clean-close (seed flat, +10 then
  −25): the +10 open is `is_leading=True`, the flip short is `is_leading=False` (a close was just
  observed) — correct. ✓
- **Non-zero `startpos` seeding:** the seeded position has no opening fill, so `open_events` emits
  NO event for it; the first emitted event (a flip, or a from-flat open after the seed closes and
  sets `seen_close`) is correctly `is_leading=False`. This mirrors `reconstruct`'s `valid` flag
  (seeded `valid=abs(pos)<tol` → False for non-zero seed; the seed position is reconstructed but not
  emitted). Both keep the first POST-seed position as a real position. ✓
- **`startpos=0` seed artifact (Audit 11):** first from-flat open gets `is_leading=True` so consumers
  can drop it; `reconstruct` would silently keep it (`valid=True`). This is the *intended* divergence
  `is_leading` exists to surface — not a bug.
- **Out-of-order fills:** `open_events` does NOT sort internally (same as `reconstruct`). Both
  markout consumers sort identically before the call: `selci_fh` L81+L85 (`df.sort` then per-group
  `g.sort("time")`) and `markout_returns` L146+L151 (same double-sort); `reconstruct`'s caller
  `_positions_for` L124 sorts too. Consistent → no divergence. (Residual: trust-the-caller; see NIT-2.)

## Why `live ≡ validated` holds despite open_events ≠ reconstruct on emission

`open_events` deliberately differs from `reconstruct` in three documented ways: (1) it emits at the
OPEN, not the close, so it **keeps never-closers** (the whole point of fixed-horizon markout — no
open/closed disposition bias); (2) `is_leading` replaces `valid`; (3) `notional` is the first fill's
`abs(d)*px`. None of these break the validation claim, because the markout path uses `open_events`
on BOTH sides — `selci_fh._open_events` (L46–51) is a thin tuple-adapter over `skill.open_events`,
and `markout_returns` (L152) calls the same function. The load-bearing fields for pricing
(`entry_t`, `direction`) are byte-identical between the two paths and to `reconstruct`. `reconstruct`
is used only by the round-trip path (`wallet_skill`/`followable_returns`), which is NOT the markout
reference — so its emit-on-close behavior is irrelevant to markout parity. Default filters also align:
`selci_fh` hardcodes `topen and conv` (L91); `markout_returns` defaults `taker_only=conviction_only=True`
(same), `drop_leading=False` (study default is also keep-leading; `--drop-leading` is a symmetric
toggle present in both, ci L534).

---

## LOW-1 — zero-size fill from flat emits a phantom event (latent; parity-preserving)
**Severity: LOW.** `src/babylon/follow/skill.py:166–168`.
If a fill has `sz==0` while flat, `signed[i]==0`, so `pos==0` → the from-flat branch fires and
`open_events` **emits** `OpenEvent(direction = 1 if d>0 else -1 → −1, notional = abs(0)*px → 0)`.
`reconstruct` suppresses this: its close-emit is gated on `es>0 and xs>0` (L109), so a 0-size open
never becomes a Position. So `open_events` would inject a phantom short, notional-0 entry that
`reconstruct` would not.
**Why it's (barely) real:** requires `sz==0` fills, which I could NOT rule out statically (no data
read). **Blast radius is contained:** both markout consumers share `open_events`, so the phantom is
identical in study and live → it does NOT break `live ≡ validated`; the edge was validated *with*
whatever phantoms exist. It only diverges from `reconstruct`, which markout doesn't use.
**Fix sketch:** guard the from-flat emit (and `pos+=d`) with `if d != 0.0:`, or drop `sz<=0` rows
upstream. Also makes the `direction = 1 if d>0 else -1` tie-break (currently silently −1 at d==0)
moot.

## NIT-1 — `notional` is the FIRST fill only, not the full built position
`skill.py:168`. For a scale-in, `notional = abs(first_fill)*px`, not the size-weighted full position
(`reconstruct`'s `en/es`). The docstring says "|opening fill| * px — the bet size at entry," so it's
intentional, and it's used only for relative size analysis (`sizeedge` normalizes by the wallet's own
median, L491) — parity-preserving. No action; flagging so a future "position notional" reader isn't
surprised.

## NIT-2 — no internal sort guard
Both `open_events` and `reconstruct` assume time-sorted input. All current callers sort, so this is
fine today; it is a latent foot-gun if a future caller forgets. Optional: assert monotonic `times`
in debug builds.

---

## What I could NOT rule out (static limits)
- Whether `sz==0` or duplicate-`time` fills actually occur in the parquet (would activate LOW-1 /
  expose any sort-tie nondeterminism). Not readable under resource rules.
- Numerical parity of the two separate `df.sort("time")` passes on tied timestamps — relies on polars
  sort determinism for identical input (believed deterministic; both paths sort the same frame the
  same way, so any nondeterminism would be shared, not divergent).

**Bottom line:** `open_events` faithfully reproduces the validated `reconstruct` flat-state machine on
every `pos`/tol/flip transition; `is_leading` and never-closer retention are correct, intended
extensions; `live ≡ validated` is sound. Only a contained zero-size-fill wart (LOW) and two NITs.
