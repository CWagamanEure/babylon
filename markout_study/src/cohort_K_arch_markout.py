"""
Stage L, Job L4: per-archetype TEST markout of the frozen cohort (STAGE_L_ARCHITECTURE §5-6, FROZEN
post-audit REVISION). Join out/cohort_K_arch.parquet (wallet->archetype) with out/cohort_K_entries.parquet
(already-priced raw+neut, no re-pricing). PRIMARY estimand per archetype = pooled TEST neut_4h, EQUAL-WEIGHT
across wallets with a k>=10 TEST-entry floor (reuse cohort_K_analyze.cohort_ew verbatim), wallet-clustered
bootstrap 95% CI, MDE = 2.8*sd/sqrt(n_wallets), vs care-about +3bp AND +10bp.

Power/injection control per archetype: inject a clean +10bp into ALL of that archetype's TEST entries
(fixed seed), recompute the eq-wt CI; inject_recovers = CI-excludes-0. A cell whose injected CI can't
exclude 0 is INCONCLUSIVE-by-construction (blind), never "null". (Clean +10bp -> recovers iff MDE<~14.3,
consistent with the powered gate MDE<=10; a 25% partial would test only +2.5bp and mislabel powered cells.)

MANDATORY mechanical placebo (generic-reversal benchmark): a contrarian portfolio over TEST on bars
(BTC/ETH/SOL/HYPE) -- at each bar signal dir = -sign(close_now/close_{-4h} - 1), enter at next close, hold
4h, strip the SAME coin-month drift as cohort_K_price. The DIR-mean-rev cell is CAPPED at "reproduces
generic reversal (not new)" unless its eq-wt TEST neut_4h CI-excludes-0 AND exceeds the placebo magnitude.

FROZEN verdict rubric (REVISION): LIVE POSITIVE / EXPECTED-ZERO CONFIRMED / METHOD-SCOPED NEGATIVE /
INCONCLUSIVE, with BH-FDR across the 6-cell PRIMARY family (neut_4h x {VAULT,TWAP,HEDGER,DIR-mom,DIR-mrev,
MIXED}). Per-coin/regime = descriptive, NO CI-excl-0 claims.

In-memory on small parquets + bars only (NO tape). Deterministic. -> out/cohort_K_arch_markout.parquet
"""
import sys, glob
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mkcommon as mk

MAJORS = ["BTC", "ETH", "SOL", "HYPE"]
BP = 1e4
H4_MS = int(mk.H_MS[5])                 # 4h  (HORIZONS index 5, verified)
CARE_LO, CARE_HI = 3.0, 10.0            # care-about: +3bp honest live (skill) effect; +10bp deployable/powered gate
INJECT_BP, INJECT_FRAC = 10.0, 1.0      # CLEAN +10bp into ALL test entries (frozen spec) -> recovers iff MDE<~14.3,
                                        #   consistent with the powered gate (MDE<=10); 25% partial caused a
                                        #   contradiction (powered cell whose +2.5bp injection could not recover).
RNG = np.random.default_rng(3)          # matches cohort_K_analyze bootstrap seed

def ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TEST_LO = ms(2026, 3, 1)

def ym_of(b_ts):
    dt = datetime.fromtimestamp(b_ts / 1000, tz=timezone.utc)
    return dt.year * 100 + dt.month

# ---------------------------------------------------------------- cohort_ew (verbatim from cohort_K_analyze)
def cohort_ew(sub, col, min_e=10, rng=RNG):
    """per-wallet mean of col (>=min_e non-null entries), then equal-weight across wallets + wallet-boot CI.
    Returns (mean, lo, hi, mde, n_wallets) or None if <20 qualifying wallets."""
    g = (sub.select("wallet", col).drop_nulls()
         .group_by("wallet").agg(m=pl.col(col).mean(), n=pl.len()).filter(pl.col("n") >= min_e))
    if g.height < 20:
        return None
    x = g["m"].to_numpy()
    boot = np.array([x[rng.choice(x.size, x.size, True)].mean() for _ in range(2000)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    mde = 2.8 * x.std() / np.sqrt(x.size)
    return x.mean(), lo, hi, mde, x.size

def pval_from(mean, mde):
    """two-sided normal p that the eq-wt mean != 0. se = mde/2.8 (same SE as the MDE)."""
    if mde is None or mde <= 0:
        return 1.0
    from math import erf, sqrt
    z = abs(mean) / (mde / 2.8)
    return 2.0 * (1.0 - 0.5 * (1.0 + erf(z / sqrt(2.0))))

def bh_fdr(pv):
    """Benjamini-Hochberg q-values."""
    p = np.asarray(pv, float)
    m = p.size
    order = np.argsort(p)
    q = p[order] * m / (np.arange(1, m + 1))
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.clip(q, 0, 1)
    return out

# ---------------------------------------------------------------- MECHANICAL PLACEBO (generic reversal)
def placebo_neut_4h():
    """Contrarian 'fade the trailing 4h, hold 4h' portfolio on bars over the TEST window.
    Strip the SAME coin-month drift as cohort_K_price. Returns (per_coin_dict, pooled_bps)."""
    lookups = mk._load_bars()
    per_coin = {}
    all_neut = []
    for coin in MAJORS:
        lk = lookups.get(coin)
        if lk is None:
            continue
        bar_ts, bar_cl = lk
        bar_ts = np.asarray(bar_ts, np.int64); bar_cl = np.asarray(bar_cl, np.float64)
        test = bar_ts >= TEST_LO
        if test.sum() < 20:
            continue
        t = bar_ts[test]
        # coin-month 4h drift (identical construction to cohort_K_price): mean forward 4h ret on the coin grid
        bar_ym = np.array([ym_of(x) for x in bar_ts])
        drift = {}
        for m in np.unique(bar_ym[test]):
            bmask = bar_ym == m
            if bmask.sum() < 20:
                continue
            bts = bar_ts[bmask]
            ent = mk._next_bar_close_vec(lk, bts)
            ex = mk._next_bar_close_vec(lk, bts + H4_MS)
            rr = ex / ent - 1.0
            fin = np.isfinite(rr)
            drift[int(m)] = float(rr[fin].mean()) if fin.any() else 0.0
        # signal: fade trailing 4h move; enter at next close, hold 4h
        now = mk._next_bar_close_vec(lk, t - mk.BAR_MS)     # close of the current bar t
        past = mk._next_bar_close_vec(lk, t - H4_MS)         # close ~4h before t
        entry = mk._next_bar_close_vec(lk, t)                # next close after t (post-signal)
        exit_ = mk._next_bar_close_vec(lk, t + H4_MS)
        with np.errstate(invalid="ignore", divide="ignore"):
            sig = -np.sign(now / past - 1.0)
            raw = sig * (exit_ / entry - 1.0)
        ymt = np.array([ym_of(x) for x in t])
        dr = np.array([drift.get(int(y), 0.0) for y in ymt])
        neut = (raw - sig * dr) * BP
        ok = np.isfinite(neut) & (sig != 0)
        if ok.sum() == 0:
            continue
        per_coin[coin] = float(neut[ok].mean())
        all_neut.append(neut[ok])
    pooled = float(np.concatenate(all_neut).mean()) if all_neut else float("nan")
    return per_coin, pooled

# ================================================================ load + join
arch = pl.read_parquet("out/cohort_K_arch.parquet")
ent = pl.read_parquet("out/cohort_K_entries.parquet")
df = ent.join(arch.select("wallet", "archetype", "dir_style"), on="wallet", how="left")
# entries whose wallet somehow lacks a label -> MIXED (should not happen; cohort is closed)
df = df.with_columns(archetype=pl.col("archetype").fill_null("MIXED"),
                     dir_style=pl.col("dir_style").fill_null("na"))
train = df.filter(pl.col("split") == "train")
test = df.filter(pl.col("split") == "test")
print(f"entries: {df.height} | test: {test.height} | wallets: {df['wallet'].n_unique()}", flush=True)

# archetype cell selectors: 5 primary classes + the two DIR sub-styles
def sel(frame, g):
    if g == "DIR-mom":
        return frame.filter((pl.col("archetype") == "DIRECTIONAL") & (pl.col("dir_style") == "momentum"))
    if g == "DIR-mrev":
        return frame.filter((pl.col("archetype") == "DIRECTIONAL") & (pl.col("dir_style") == "meanrev"))
    return frame.filter(pl.col("archetype") == g)

CELLS = ["VAULT", "TWAP", "HEDGER", "DIRECTIONAL", "MIXED", "DIR-mom", "DIR-mrev"]
FDR_FAMILY = ["VAULT", "TWAP", "HEDGER", "DIR-mom", "DIR-mrev", "MIXED"]   # 6-cell primary family
EXPECTED_ZERO = {"VAULT", "TWAP", "HEDGER"}
DIR_TILT = {"DIR-mom", "DIR-mrev"}

# ================================================================ placebo (once)
pc_placebo, pooled_placebo = placebo_neut_4h()
print("\n=== MECHANICAL PLACEBO (contrarian, fade trailing-4h, hold 4h; TEST; neut bps) ===")
for c in MAJORS:
    print(f"    {c:5s} {pc_placebo.get(c, float('nan')):+.2f}")
print(f"    POOLED {pooled_placebo:+.2f}")

# ================================================================ per-cell stats
rows = []
for g in CELLS:
    st, se = sel(train, g), sel(test, g)
    tr = cohort_ew(st, "neut_4h", min_e=10, rng=np.random.default_rng(101))
    te = cohort_ew(se, "neut_4h", min_e=10, rng=np.random.default_rng(3))
    rw = cohort_ew(se, "raw_4h", min_e=10, rng=np.random.default_rng(7))
    c24 = cohort_ew(se, "neut_24h", min_e=10, rng=np.random.default_rng(9))
    # per-coin descriptive sign test (NO CI claims)
    coin_signs = {}
    for coin in MAJORS:
        cc = cohort_ew(se.filter(pl.col("coin") == coin), "neut_4h", min_e=10,
                       rng=np.random.default_rng(hash(coin) % 1_000_000))
        coin_signs[coin] = cc[0] if cc else None
    vals = [v for v in coin_signs.values() if v is not None]
    n_pos = sum(1 for v in vals if v > 0); n_neg = sum(1 for v in vals if v < 0)
    coins_same_sign = max(n_pos, n_neg)
    # injection positive control: clean +10bp into ALL of this cell's TEST neut_4h entries
    inj = se.select("wallet", "neut_4h").drop_nulls()
    inject_recovers = None; inj_ci = None
    if inj.height:
        irng = np.random.default_rng(20260705)
        v = inj["neut_4h"].to_numpy().copy()
        mask = irng.random(v.size) < INJECT_FRAC
        v[mask] += INJECT_BP
        inj2 = inj.with_columns(pl.Series("neut_4h", v))
        ir = cohort_ew(inj2, "neut_4h", min_e=10, rng=np.random.default_rng(21))
        if ir:
            inj_ci = (float(ir[1]), float(ir[2]))
            inject_recovers = bool((ir[1] > 0) or (ir[2] < 0))   # Python bool (np.bool_ breaks `is False`)
    rows.append(dict(archetype=g, tr=tr, te=te, rw=rw, c24=c24, coin_signs=coin_signs,
                     coins_same_sign=coins_same_sign, n_coins=len(vals),
                     inject_recovers=inject_recovers, inj_ci=inj_ci))

# BH-FDR across the 6-cell primary family
fam = [r for r in rows if r["archetype"] in FDR_FAMILY]
pvs = [pval_from(r["te"][0], r["te"][3]) if r["te"] else 1.0 for r in fam]
qvs = bh_fdr(pvs)
for r, p, qv in zip(fam, pvs, qvs):
    r["pval"], r["qval"], r["fdr_survive"] = p, float(qv), bool(qv < 0.05)
for r in rows:
    r.setdefault("pval", float("nan")); r.setdefault("qval", float("nan")); r.setdefault("fdr_survive", False)

# ================================================================ FROZEN verdict rubric
def verdict(r):
    """Over-null gate: a NEGATIVE must EARN it — the CI must EXCLUDE the +3bp skill effect we care about
    (upper CI < CARE_LO for the copyable-positive-edge question). A cell whose CI still ADMITS +3bp is
    INCONCLUSIVE, never 'no edge'. Over-carry gate: a positive lean that does not BEAT the mechanical
    reversal placebo is generic reversal, never wallet alpha."""
    te = r["te"]
    if te is None:
        return "INCONCLUSIVE (<20 wallets @ k>=10 TEST floor — blind by N)"
    mean, lo, hi, mde, _ = te
    ci_excl0 = (lo > 0) or (hi < 0)
    coins_ok = r["coins_same_sign"] >= 3
    recov = r["inject_recovers"]
    if recov is not None and not recov:
        return "INCONCLUSIVE-by-construction (blind: +10bp injection did not recover)"
    rules_out_pos = hi < CARE_LO            # upper CI below +3bp -> earns "no copyable positive edge"
    plc = pooled_placebo if np.isfinite(pooled_placebo) else 0.0
    g = r["archetype"]
    if g in DIR_TILT:
        beats_plc = mean > plc              # must earn MORE than a mechanical fade to be wallet alpha
        if ci_excl0 and mean >= CARE_LO and coins_ok and r["fdr_survive"] and beats_plc:
            return f"LIVE POSITIVE (beats mechanical placebo {plc:+.1f})"
        if mean > 0 and not beats_plc:
            return f"reproduces generic reversal (lean {mean:+.1f} <= mechanical placebo {plc:+.1f}; no wallet edge)"
        if rules_out_pos:
            return "METHOD-SCOPED NEGATIVE (no positive edge from this archetype)"
        return "INCONCLUSIVE (CI admits +3bp skill; underpowered)"
    if g == "DIRECTIONAL":                  # aggregate parent (sub-cells carry the FDR-tested primary)
        if rules_out_pos:
            return "METHOD-SCOPED NEGATIVE (aggregate; no positive edge; cannot resolve a within-archetype minority)"
        if ci_excl0 and mean > 0:
            return "aggregate CI-excl-0 (descriptive; see DIR-mom/DIR-mrev sub-cells, not FDR-tested)"
        return "INCONCLUSIVE (aggregate)"
    if g in EXPECTED_ZERO:
        tight = abs(lo) <= CARE_LO and abs(hi) <= CARE_LO          # CI rules out even a ±3bp effect
        if ci_excl0 and mean >= CARE_LO and r["fdr_survive"]:
            return "LIVE POSITIVE (unexpected)"
        if recov and not ci_excl0 and tight:
            return "EXPECTED-ZERO CONFIRMED (tight, within +/-3bp)"
        if recov and rules_out_pos:
            return "EXPECTED-ZERO (no deployable/positive edge; sub-cost +/-3bp residual unresolved)"
        return "INCONCLUSIVE"
    # MIXED
    if ci_excl0 and mean >= CARE_LO and coins_ok and r["fdr_survive"]:
        return "LIVE POSITIVE (graduates)"
    if rules_out_pos:
        return "METHOD-SCOPED NEGATIVE (mixture; no positive edge)"
    return "INCONCLUSIVE"

for r in rows:
    r["verdict"] = verdict(r)

# ================================================================ report + parquet
def fmt(t):
    return f"{t[0]:+6.2f} [{t[1]:+6.2f},{t[2]:+6.2f}] MDE{t[3]:4.1f} n={t[4]}" if t else "n/a (<20 wallets)"

print("\n=== PER-ARCHETYPE TEST neut_4h (equal-weight, k>=10 floor; care-about +3 / +10 bp) ===")
for r in rows:
    print(f"\n  [{r['archetype']}]  verdict: {r['verdict']}")
    print(f"    train neut_4h : {fmt(r['tr'])}")
    print(f"    TEST  neut_4h : {fmt(r['te'])}")
    if r["te"]:
        m = r["te"][3]
        print(f"      MDE {m:.1f}  vs care +3bp: {'OK' if m <= CARE_LO else 'blind'} | "
              f"vs care +10bp: {'OK' if m <= CARE_HI else 'blind'}")
    print(f"    raw_4h (annot): {fmt(r['rw'])}")
    print(f"    neut_24h ctx  : {fmt(r['c24'])}")
    cs = "  ".join(f"{c}:{(v if v is not None else float('nan')):+.1f}" for c, v in r["coin_signs"].items())
    print(f"    per-coin neut_4h (descriptive): {cs}   -> {r['coins_same_sign']}/{r['n_coins']} same sign")
    print(f"    injection +10bp recovers CI-excl-0: {r['inject_recovers']}  (inj CI {r['inj_ci']})")
    if r["archetype"] in FDR_FAMILY:
        print(f"    p={r['pval']:.3f}  q(BH)={r['qval']:.3f}  FDR-survive={r['fdr_survive']}")

print("\n=== CLEAN VERDICT TABLE (PRIMARY = TEST neut_4h eq-wt) ===")
print(f"    {'cell':11s} {'n_w':>4s} {'test_neut4h':>13s} {'95% CI':>18s} {'MDE':>5s} "
      f"{'q_BH':>6s} {'inj':>4s} {'verdict'}")
for r in rows:
    te = r["te"]
    if te:
        s = f"{te[0]:+7.2f}"; ci = f"[{te[1]:+6.2f},{te[2]:+6.2f}]"; mde = f"{te[3]:4.1f}"; nw = te[4]
    else:
        s = "n/a"; ci = "-"; mde = "-"; nw = 0
    qv = f"{r['qval']:.3f}" if r["archetype"] in FDR_FAMILY else "-"
    inj = str(r["inject_recovers"])[:4]
    print(f"    {r['archetype']:11s} {nw:>4d} {s:>13s} {ci:>18s} {mde:>5s} {qv:>6s} {inj:>4s} {r['verdict']}")
print(f"\n    placebo (generic reversal) pooled neut_4h = {pooled_placebo:+.2f} bp  "
      f"(DIR-mrev capped at 'reproduces generic reversal' unless it CI-excl-0 AND exceeds this magnitude)")

# ---- parquet ----
def unpack(t, keys):
    if t is None:
        return {k: None for k in keys}
    return dict(zip(keys, [float(t[0]), float(t[1]), float(t[2]), float(t[3]), int(t[4])]))

recs = []
for r in rows:
    rec = {"archetype": r["archetype"]}
    rec.update(unpack(r["te"], ["test_neut_4h", "ci_lo", "ci_hi", "mde", "n_wallets"]))
    rec.update(unpack(r["tr"], ["train_neut_4h", "tr_lo", "tr_hi", "tr_mde", "n_wallets_train"]))
    rec.update(unpack(r["rw"], ["test_raw_4h", "rw_lo", "rw_hi", "rw_mde", "rw_n"]))
    rec.update(unpack(r["c24"], ["test_neut_24h", "c24_lo", "c24_hi", "c24_mde", "c24_n"]))
    for c in MAJORS:
        rec[f"coin_neut_4h_{c}"] = r["coin_signs"].get(c)
    rec["coins_same_sign"] = r["coins_same_sign"]
    rec["inject_recovers"] = r["inject_recovers"]
    rec["pval"] = r["pval"]; rec["qval_bh"] = r["qval"]; rec["fdr_survive"] = r["fdr_survive"]
    rec["placebo_pooled_neut_4h"] = pooled_placebo
    rec["verdict"] = r["verdict"]
    recs.append(rec)
res = pl.DataFrame(recs)
res.write_parquet("out/cohort_K_arch_markout.parquet")
print(f"\nwrote {res.height} archetype rows -> out/cohort_K_arch_markout.parquet")
