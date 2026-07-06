"""
Step-0 EDGE GATE (free, existing data) — source-attribution of the top cohort's 24h edge.
Per the 4-agent edge-isolation swarm: an edge is only worth a confirmatory Stage-E test if it is
(a) COPYABLE — survives a follower's 15-min entry lag — and (b) IDIOSYNCRATIC — not just being on the
right side of a market-wide move (beta-timing), which is unconfirmable with 5 coins x 11 months.

This is DESCRIPTIVE source-attribution, NOT the confirmatory test. The cohort is selected in-sample on
vw_edge@24h, so the LEVEL of its edge is selection-inflated by construction — the gate reads the SHAPE:
  - raw 24h edge   vs   15-min-lagged 24h edge      -> copyability (how much is born after the lag)
  - beta-timing (b*dir*index_ret)  vs  idiosyncratic residual  -> is the edge market-timing or coin-specific
Decision (swarm): edge dies under lag -> not copyable STOP; residual~0 -> all beta-timing STOP/pivot;
idiosyncratic post-lag residual survives -> GO to the pre-registered feature test.
"""
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import MAJORS, _load_bars, _next_bar_close_vec, HORIZONS, H_LABELS, H_MS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
H24 = 24 * 3_600_000
LAG = 15 * 60_000
FLOOR = 30
K = 50
SEED = 20260704
BP = 1e4


def _fwd_ret(L, t, hms):
    """dir-agnostic forward simple return over hms, priced post-fill both ends (leak-free)."""
    e = _next_bar_close_vec(L, t)
    x = _next_bar_close_vec(L, t + hms)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = x / e - 1.0
    r[~(np.isfinite(e) & (e > 0) & np.isfinite(x) & (x > 0))] = np.nan
    return r


def build_index_fwd24(lk):
    """Equal-weight-of-majors 24h forward return on the shared 5-min grid (fit target for beta)."""
    frames = []
    for c in MAJORS:
        L = lk[c]
        bt = L[0]
        fwd = _fwd_ret(L, bt, H24)
        frames.append(pl.DataFrame({"t": bt, c: fwd}))
    df = frames[0]
    for f in frames[1:]:
        df = df.join(f, on="t", how="full", coalesce=True)
    idx = df.select("t", pl.mean_horizontal([pl.col(c) for c in MAJORS]).alias("idx")).sort("t")
    return idx["t"].to_numpy(), idx["idx"].to_numpy()


def main():
    rng = np.random.default_rng(SEED)
    lk = _load_bars()
    it, iv = build_index_fwd24(lk)

    ms = pl.read_parquet(OUT / "markout_stats.parquet").filter(
        (pl.col("coin").is_in(MAJORS)) & (pl.col("n") >= FLOOR))
    pool24 = ms.filter(pl.col("horizon") == "24h").select("wallet", "coin", "vw_edge_bps")

    ent = (pl.scan_parquet(OUT / "entries" / "part_*.parquet")
           .filter(pl.col("coin").is_in(MAJORS))
           .join(pool24.lazy().select("wallet", "coin"), on=["wallet", "coin"], how="semi")
           .select("wallet", "coin", "b_ts", "dir").collect())

    # per-entry: raw 24h markout, 15-min-lagged 24h markout, beta exposure x = dir*index_fwd24(t)
    parts = []
    for c in MAJORS:
        e = ent.filter(pl.col("coin") == c)
        if e.height == 0:
            continue
        L = lk[c]
        b = e["b_ts"].to_numpy(); d = e["dir"].to_numpy().astype(np.float64)
        mk = d * _fwd_ret(L, b, H24)
        mk_lag = d * _fwd_ret(L, b + LAG, H24)
        j = np.clip(np.searchsorted(it, b), 0, it.size - 1)
        x = d * iv[j]
        parts.append(e.with_columns(pl.Series("mk", mk), pl.Series("mk_lag", mk_lag), pl.Series("x", x)))
    E = pl.concat(parts)

    # field-wide beta fit y = a + b*x (fit on ALL pool entries; residual = idiosyncratic dir-move)
    fin = E.filter(pl.col("mk").is_finite() & pl.col("x").is_finite())
    y = fin["mk"].to_numpy(); x = fin["x"].to_numpy()
    b_hat = float(np.cov(x, y)[0, 1] / np.var(x))
    a_hat = float(y.mean() - b_hat * x.mean())
    E = E.with_columns((pl.col("mk") - a_hat - b_hat * pl.col("x")).alias("resid"),
                       (b_hat * pl.col("x")).alias("beta_part"))
    print(f"field beta fit: b={b_hat:.3f}  a={a_hat*BP:+.1f}bp  (N={fin.height:,})", flush=True)

    def agg(df, wallets=None):
        d = df.filter(pl.col("wallet").is_in(wallets)) if wallets is not None else df
        raw = d["mk"].drop_nans(); lag = d["mk_lag"].drop_nans()
        idio = d["resid"].drop_nans(); beta = d["beta_part"].drop_nans()
        return dict(nent=raw.len(), raw=raw.mean() * BP, lag=lag.mean() * BP,
                    idio=idio.mean() * BP, beta=beta.mean() * BP)

    def wboot(df, wallets, key, R=400):
        """wallet-clustered bootstrap CI (bps) of the mean of `key` over the cohort."""
        wl = np.array(list(wallets))
        by = {w: df.filter(pl.col("wallet") == w)[key].drop_nans().to_numpy() for w in wl}
        means = []
        for _ in range(R):
            pick = wl[rng.integers(0, wl.size, wl.size)]
            v = np.concatenate([by[w] for w in pick if by[w].size])
            if v.size:
                means.append(v.mean() * BP)
        return (np.nanpercentile(means, 5), np.nanpercentile(means, 95)) if means else (np.nan, np.nan)

    print(f"\n{'='*78}\nEDGE GATE  (top-{K} by vw_edge@24h, per coin; DESCRIPTIVE/in-sample — read SHAPE not level)\n{'='*78}")
    hdr = f"{'coin':5s} {'cohort/field':13s} {'Nent':>7s} {'raw24h':>9s} {'lag15m':>9s} {'keep%':>6s} {'beta':>8s} {'idio':>8s} {'idio_CI':>16s}"
    print(hdr)
    for c in MAJORS:
        ec = E.filter(pl.col("coin") == c)
        p = pool24.filter(pl.col("coin") == c)
        if p.height < K:
            continue
        coh = set(p.sort("vw_edge_bps", descending=True).head(K)["wallet"].to_list())
        cg = agg(ec, coh); fg = agg(ec)
        keep = 100 * cg["lag"] / cg["raw"] if cg["raw"] else float("nan")
        lo, hi = wboot(ec, coh, "resid")
        print(f"{c:5s} {'COHORT':13s} {cg['nent']:>7d} {cg['raw']:>+8.1f} {cg['lag']:>+8.1f} {keep:>5.0f}% "
              f"{cg['beta']:>+7.1f} {cg['idio']:>+7.1f}  [{lo:>+6.1f},{hi:>+6.1f}]")
        print(f"{'':5s} {'field':13s} {fg['nent']:>7d} {fg['raw']:>+8.1f} {fg['lag']:>+8.1f} {'':6s} "
              f"{fg['beta']:>+7.1f} {fg['idio']:>+7.1f}")

    # SNR term structure of the pooled cohort (from markout_stats: mean / (per-entry std / sqrt(N)))
    print(f"\n{'-'*78}\nSNR TERM STRUCTURE (pooled top-{K} cohorts; SNR = mean_edge / (sigma_entry/sqrt(N)))")
    coh_all = {}
    for c in MAJORS:
        p = pool24.filter(pl.col("coin") == c)
        if p.height >= K:
            coh_all[c] = set(p.sort("vw_edge_bps", descending=True).head(K)["wallet"].to_list())
    line_h, line_e, line_s = [], [], []
    for hl in H_LABELS:
        rows = ms.filter(pl.col("horizon") == hl)
        m, v, N = 0.0, 0.0, 0
        for c, wl in coh_all.items():
            r = rows.filter((pl.col("coin") == c) & pl.col("wallet").is_in(list(wl)))
            if r.height == 0:
                continue
            n = r["n"].to_numpy(); mu = r["avg_edge_bps"].to_numpy()
            sh = r["sharpe"].to_numpy()
            sig = np.where(np.abs(sh) > 1e-9, np.abs(mu / sh), np.nan)  # per-entry std (bps)
            ok = np.isfinite(mu) & np.isfinite(sig)
            m += float((mu[ok] * n[ok]).sum()); v += float((sig[ok] ** 2 * n[ok]).sum()); N += int(n[ok].sum())
        if N == 0:
            continue
        mean_bp = m / N; sig_bp = np.sqrt(v / N); snr = mean_bp / (sig_bp / np.sqrt(N))
        line_h.append(hl); line_e.append(mean_bp); line_s.append(snr)
    print("horizon : " + " ".join(f"{h:>7s}" for h in line_h))
    print("mean_bp : " + " ".join(f"{e:>+7.1f}" for e in line_e))
    print("SNR     : " + " ".join(f"{s:>7.2f}" for s in line_s))
    peak = line_h[int(np.argmax(np.abs(line_s)))]
    print(f"\n-> peak |SNR| horizon = {peak}  (is 24h the most DETECTABLE horizon, or just the biggest mean?)")


if __name__ == "__main__":
    main()
