"""
Stage L, Job L3: classify the frozen cohort_K wallets into trader archetypes (STAGE_L_ARCHITECTURE §4,
FROZEN post-audit REVISION). Join out/cohort_K_archfeat.parquet (TRAIN-only behavior features) + out/
cohort_K_vault.parquet (HL userRole identity). Cutpoints (Q1/median/Q3) are TRAIN-only and computed from
BEHAVIOR features only (never markout) -> frozen before any outcome is read. Apply the §4 priority rule
tree (first match wins) -> one archetype per wallet, plus a DIRECTIONAL momentum/mean-rev style flag.

Robustness (confirmatory-MUST-AGREE, NOT new discovery): a 2-of-3 soft-membership relaxation of the same
conditions, and an optional k-means (sklearn, random_state=0, k=5, standardized features). We emit the
priority-vs-soft and priority-vs-kmeans cross-tabs so the reader can see the priority order is not driving
the verdict.

In-memory on small parquets only (NO tape). Deterministic. -> out/cohort_K_arch.parquet
"""
import sys
from pathlib import Path
import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))

ARCHFEAT = "out/cohort_K_archfeat.parquet"
VAULT = "out/cohort_K_vault.parquet"
OUT = "out/cohort_K_arch.parquet"
# known protocol vaults (HLP) tagged is_vault regardless of role string (mirror cohort_K_vault.KNOWN_VAULT)
KNOWN_VAULT = {"0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"}

# ---------------------------------------------------------------- load + join
feat = pl.read_parquet(ARCHFEAT)
vdf = pl.read_parquet(VAULT)
# vault parquet may be a mid-run checkpoint (role only) or the final (role+is_vault) -> derive robustly.
if "is_vault" not in vdf.columns:
    vdf = vdf.with_columns(is_vault=pl.lit(False))
vdf = vdf.with_columns(
    is_vault=(pl.col("is_vault") | (pl.col("role") == "vault")
              | pl.col("wallet").str.to_lowercase().is_in(list(KNOWN_VAULT)))
)
df = feat.join(vdf.select("wallet", "role", "is_vault"), on="wallet", how="left").with_columns(
    is_vault=pl.col("is_vault").fill_null(False),
    role=pl.col("role").fill_null("unknown"),
)
N = df.height
print(f"cohort wallets: {N} | is_vault: {int(df['is_vault'].sum())} | "
      f"roles: {dict(zip(*[c.to_list() for c in df['role'].value_counts()]))}", flush=True)

# ---------------------------------------------------------------- feature arrays (float, null -> nan)
def col(name):
    return df[name].cast(pl.Float64).to_numpy()

fc = col("funding_capture_bps");   afc = np.abs(fc)
tip = col("time_in_pos_frac")
cad = col("cadence_cv")
scv = col("size_cv")
nlf = col("net_long_frac");        anlf = np.abs(nlf - 0.5)
hhi = col("coin_hhi")
tilt = col("regime_tilt")
is_vault = df["is_vault"].to_numpy()

def q(arr, p):
    a = arr[np.isfinite(arr)]
    return float(np.quantile(a, p)) if a.size else np.nan

# ---------------------------------------------------------------- TRAIN-only cutpoints (FROZEN, behavior-only)
CUT = {
    "Q1_cadence_cv": q(cad, 0.25),
    "Q1_size_cv": q(scv, 0.25),
    "med_size_cv": q(scv, 0.50),
    "Q3_abs_funding_capture_bps": q(afc, 0.75),
    "Q3_time_in_pos_frac": q(tip, 0.75),
    "med_abs_net_long_dev": q(anlf, 0.50),
    "med_coin_hhi": q(hhi, 0.50),
    "med_cadence_cv": q(cad, 0.50),
}
print("\n=== FROZEN TRAIN-only cutpoints (behavior features only) ===")
for k, v in CUT.items():
    print(f"    {k:32s} = {v:.6g}")

# NaN-safe comparison helpers (a missing feature must NOT silently pass a <= / >= test)
def le(a, thr):
    return np.isfinite(a) & (a <= thr)
def ge(a, thr):
    return np.isfinite(a) & (a >= thr)

# ---------------------------------------------------------------- §4 PRIORITY rule tree (first match wins)
c_twap = le(cad, CUT["Q1_cadence_cv"]) & le(scv, CUT["Q1_size_cv"])
c_hedg = (ge(afc, CUT["Q3_abs_funding_capture_bps"]) & ge(tip, CUT["Q3_time_in_pos_frac"])
          & (np.isfinite(anlf) & (anlf <= 0.15)) & le(scv, CUT["med_size_cv"]))
c_dir = (ge(anlf, CUT["med_abs_net_long_dev"])
         & (ge(hhi, CUT["med_coin_hhi"]) | ge(scv, CUT["med_size_cv"])))

archetype = np.full(N, "MIXED", dtype=object)
# peel in priority order; each guard excludes wallets already claimed by a higher rule
claimed = np.zeros(N, bool)
for label, cond in [("VAULT", is_vault.astype(bool)), ("TWAP", c_twap),
                    ("HEDGER", c_hedg), ("DIRECTIONAL", c_dir)]:
    take = cond & (~claimed)
    archetype[take] = label
    claimed |= take

# DIRECTIONAL sub-style by regime_tilt sign (LABEL only; primary class stays DIRECTIONAL)
dir_style = np.full(N, "na", dtype=object)
is_dir = archetype == "DIRECTIONAL"
dir_style[is_dir & (np.isfinite(tilt) & (tilt > 0))] = "momentum"
dir_style[is_dir & (np.isfinite(tilt) & (tilt < 0))] = "meanrev"

# ---------------------------------------------------------------- CONFIRMATORY: 2-of-3 soft membership
# Relax each behavioral archetype's AND-conjunction to "satisfies >=2 of its 3 core conditions", evaluated
# in the SAME priority order. VAULT stays hard identity. (Spec ambiguity resolved: TWAP/HEDGER list only 2/4
# strict conditions -> for a genuine 2-of-3 relaxation we use a coherent 3-condition core per archetype.)
soft_sets = {
    "TWAP": [le(cad, CUT["Q1_cadence_cv"]), le(scv, CUT["Q1_size_cv"]), le(cad, CUT["med_cadence_cv"])],
    "HEDGER": [ge(afc, CUT["Q3_abs_funding_capture_bps"]), ge(tip, CUT["Q3_time_in_pos_frac"]),
               (np.isfinite(anlf) & (anlf <= 0.15))],
    "DIRECTIONAL": [ge(anlf, CUT["med_abs_net_long_dev"]), ge(hhi, CUT["med_coin_hhi"]),
                    ge(scv, CUT["med_size_cv"])],
}
soft = np.full(N, "MIXED", dtype=object)
sclaimed = is_vault.astype(bool).copy()
soft[is_vault.astype(bool)] = "VAULT"
for label in ["TWAP", "HEDGER", "DIRECTIONAL"]:
    votes = np.sum(soft_sets[label], axis=0)
    take = (votes >= 2) & (~sclaimed)
    soft[take] = label
    sclaimed |= take

# ---------------------------------------------------------------- CONFIRMATORY: k-means (optional)
KM_FEATS = ["funding_capture_bps", "time_in_pos_frac", "med_hold_h_train", "cadence_cv", "size_cv",
            "net_long_frac", "coin_hhi", "add_frac", "avgdown_rate", "regime_tilt"]
kmeans_cluster = np.full(N, -1, dtype=np.int64)
try:
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    X = np.column_stack([col(c) for c in KM_FEATS])
    med = np.nanmedian(X, axis=0)
    inds = np.where(~np.isfinite(X))
    X[inds] = np.take(med, inds[1])            # impute missing with column median
    Xs = StandardScaler().fit_transform(X)
    kmeans_cluster = KMeans(n_clusters=5, random_state=0, n_init=10).fit_predict(Xs).astype(np.int64)
    print("\nk-means: fit on standardized features (k=5, random_state=0)")
except Exception as e:
    print(f"\nk-means skipped ({type(e).__name__}: {e}); kmeans_cluster=-1")

# ---------------------------------------------------------------- outputs + cross-tabs
out = pl.DataFrame({
    "wallet": df["wallet"],
    "archetype": pl.Series(archetype, dtype=pl.String),
    "dir_style": pl.Series(dir_style, dtype=pl.String),
    "soft_archetype": pl.Series(soft, dtype=pl.String),
    "kmeans_cluster": pl.Series(kmeans_cluster, dtype=pl.Int64),
})
out.write_parquet(OUT)

ORDER = ["VAULT", "TWAP", "HEDGER", "DIRECTIONAL", "MIXED"]
print("\n=== ARCHETYPE SIZES (priority rule tree) ===")
sz = out.group_by("archetype").agg(n=pl.len())
szd = dict(zip(sz["archetype"].to_list(), sz["n"].to_list()))
for a in ORDER:
    print(f"    {a:14s} {szd.get(a, 0):5d}")
print("    DIRECTIONAL sub-style:")
for st in ["momentum", "meanrev", "na"]:
    print(f"      DIR-{st:9s} {int(np.sum((archetype=='DIRECTIONAL') & (dir_style==st))):5d}")

def crosstab(a_col, b_col, title, b_vals=None):
    print(f"\n=== {title} ===")
    ct = out.group_by(a_col, b_col).agg(n=pl.len())
    piv = ct.pivot(values="n", index=a_col, on=b_col).fill_null(0)
    print(piv.sort(a_col))

crosstab("archetype", "soft_archetype", "PRIORITY (rows) vs SOFT-MEMBERSHIP (cols) cross-tab")
if (kmeans_cluster >= 0).any():
    crosstab("archetype", "kmeans_cluster", "PRIORITY (rows) vs K-MEANS cluster (cols) cross-tab")

print(f"\nwrote {out.height} -> {OUT}")
