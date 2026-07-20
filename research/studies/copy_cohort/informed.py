"""Wallet informedness scoring — exact Student-t survival + Efron two-groups local-FDR (numpy only).

Implements the frozen ALT_UNIVERSE_PREREG addendum Arm T / Arm P machinery:
  t_sf(t, df)      exact one-sided Student-t survival via regularized incomplete beta (no scipy)
  two_groups(z)    empirical-null local FDR: 60 bins on [-8,8], deg-5 log-poly f-hat, central-matching
                   N(mu0, sigma0) null, pi0 capped at 1 -> lfdr(z), P_informed = 1 - lfdr
All constants are pre-registered; do not tune after lake data is viewed.
"""
from __future__ import annotations

import numpy as np

from research.lib.stats import inv_norm

Z_CLIP = 8.0
N_BINS = 60
F_DEG = 5          # log-density polynomial degree (Efron standard)
NULL_DEG = 2       # quadratic -> gaussian null


# ---------- exact Student-t survival (regularized incomplete beta, Numerical-Recipes betacf) ----------

def _betacf(a: float, b: float, x: float, itmax: int = 200, eps: float = 3e-12) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            return h
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a,b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    import math
    ln_bt = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
             + a * np.log(x) + b * np.log(1.0 - x))
    bt = np.exp(ln_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return float(bt * _betacf(a, b, x) / a)
    return float(1.0 - bt * _betacf(b, a, 1.0 - x) / b)


def t_sf(t: float, df: float) -> float:
    """One-sided survival P(T_df > t), exact."""
    if not np.isfinite(t):
        return 0.0 if t > 0 else 1.0
    p_two = _betai(df / 2.0, 0.5, df / (df + t * t))   # P(|T| > |t|)
    return p_two / 2.0 if t >= 0 else 1.0 - p_two / 2.0


def t_to_z(t: np.ndarray, df: np.ndarray) -> np.ndarray:
    """z_w = Phi^-1(1 - p_w), clipped to [-Z_CLIP, Z_CLIP]."""
    z = np.empty(t.size)
    for i in range(t.size):
        p = min(max(t_sf(float(t[i]), float(df[i])), 1e-15), 1 - 1e-15)
        z[i] = inv_norm(1.0 - p)
    return np.clip(z, -Z_CLIP, Z_CLIP)


# ---------- Efron two-groups / local FDR with empirical null ----------

def two_groups(z: np.ndarray) -> dict:
    """Returns dict with per-wallet lfdr + P_informed and the fitted null (mu0, sigma0, pi0)."""
    z = np.clip(np.asarray(z, float), -Z_CLIP, Z_CLIP)
    n = z.size
    edges = np.linspace(-Z_CLIP, Z_CLIP, N_BINS + 1)
    mids = 0.5 * (edges[:-1] + edges[1:])
    width = edges[1] - edges[0]
    counts, _ = np.histogram(z, bins=edges)

    # f-hat: degree-5 polynomial fit to log counts (bins with count>0), Poisson-style.
    # Fit, normalization, and evaluation are all restricted to the OCCUPIED support — the
    # polynomial is unconstrained in empty tail bins and can explode there, which would
    # corrupt the mass normalization (found in synthetic smoke, 2026-07-16).
    pos = counts > 0
    z_lo, z_hi = mids[pos].min(), mids[pos].max()
    coef_f = np.polyfit(mids[pos], np.log(counts[pos]), F_DEG, w=np.sqrt(counts[pos]))
    fhat_pos = np.exp(np.polyval(coef_f, mids[pos]))
    norm = counts.sum() / fhat_pos.sum()                     # mass over occupied bins only
    f_dens_bins = np.zeros(N_BINS)
    f_dens_bins[pos] = fhat_pos * norm / (n * width)         # density scale on support

    # empirical null: quadratic fit to log f-hat on the central-quartile z-range
    q25, q75 = np.percentile(z, 25), np.percentile(z, 75)
    cen = (mids >= q25) & (mids <= q75)
    if cen.sum() < NULL_DEG + 1:                             # degenerate window -> widen
        cen = (mids >= np.percentile(z, 10)) & (mids <= np.percentile(z, 90))
    a2, a1, a0 = np.polyfit(mids[cen], np.log(np.maximum(f_dens_bins[cen], 1e-300)), NULL_DEG)
    if a2 >= 0:                                              # not concave -> fall back to theoretical null
        mu0, sigma0 = 0.0, 1.0
    else:
        sigma0 = float(np.sqrt(-1.0 / (2.0 * a2)))
        mu0 = float(a1 * sigma0 ** 2)
    log_p0_at_mu0 = a0 + a1 * mu0 + a2 * mu0 ** 2 if a2 < 0 else np.log(
        f_dens_bins[np.argmin(np.abs(mids))])
    # pi0: implied null mass / total (density at mu0 vs N(mu0,sigma0) peak), capped at 1
    pi0 = float(min(1.0, np.exp(log_p0_at_mu0) * sigma0 * np.sqrt(2 * np.pi)))

    def lfdr_of(zv: np.ndarray) -> np.ndarray:
        zc = np.clip(zv, z_lo, z_hi)                          # evaluate on occupied support only
        f = np.exp(np.polyval(coef_f, zc)) * norm / (n * width)
        f0 = np.exp(-0.5 * ((zc - mu0) / sigma0) ** 2) / (sigma0 * np.sqrt(2 * np.pi))
        return np.clip(pi0 * f0 / np.maximum(f, 1e-300), 0.0, 1.0)

    # Tweedie posterior mean of the true (studentized) effect: for z | theta ~ N(theta, sigma0^2)
    # with marginal density f, E[theta | z] = z + sigma0^2 * d/dz log f(z) (Efron 2011,
    # "Tweedie's formula and selection bias"). log f = polyval(coef_f, z) + const, so the
    # correction is sigma0^2 * polyval(coef_f', z) — exact, straight off the fitted log-density.
    # This is the winner's-curse-corrected effect: it shrinks bulk z heavily toward the null and
    # the extreme tail barely at all. Evaluated on the occupied support only (same clip as lfdr).
    dcoef_f = np.polyder(coef_f)

    def theta_of(zv: np.ndarray) -> np.ndarray:
        zc = np.clip(zv, z_lo, z_hi)
        return zc + sigma0 ** 2 * np.polyval(dcoef_f, zc)

    lf = lfdr_of(z)
    return {"lfdr": lf, "p_informed": 1.0 - lf, "mu0": mu0, "sigma0": sigma0, "pi0": pi0,
            "lfdr_of": lfdr_of, "theta_hat": theta_of(z), "theta_of": theta_of,
            "coef_f": coef_f, "z_lo": z_lo, "z_hi": z_hi}
