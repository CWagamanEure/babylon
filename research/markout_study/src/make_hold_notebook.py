"""Build notebooks/hold_feasibility.ipynb from out/hold_size_dist.parquet.
Run AFTER hold_size_dist.py completes:  python3 src/make_hold_notebook.py && \
  jupyter nbconvert --execute --inplace notebooks/hold_feasibility.ipynb
"""
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []

cells.append(nbf.v4.new_markdown_cell(
    "# Hold-time × sample-size feasibility\n"
    "**Question:** how many wallets actually live in the copyable box — enough TAKER-opened round-trips "
    "at a mid-frequency hold — to matter?\n\n"
    "**Reconciliations (why avg-hold alone is misleading):**\n"
    "- Hold is bucketed **per trade** (not averaged): `<15m / 15m–1h / 1–4h / 4–24h / 24–72h / >72h`, so a "
    "wallet that mixes 48h swings and 10-min scalps shows its true spread.\n"
    "- Only **taker-OPENED** round-trips count (entry taker-share > 0.5) — maker legs are not copyable.\n"
    "- The feasibility number is **`n_copyable` = taker-opened round-trips with hold in 1–24h**, per wallet — "
    "not `total trades × avg-hold≈4h`.\n\n"
    "Whole-window (train+test), majors, dust floor $100. Source: `out/hold_size_dist.parquet`."
))

cells.append(nbf.v4.new_code_cell(
    "import numpy as np, polars as pl, matplotlib.pyplot as plt\n"
    "from matplotlib.patches import Rectangle\n"
    "df = pl.read_parquet('../out/hold_size_dist.parquet')\n"
    "print('wallets:', df.height)\n"
    "BANDS = ['lt15m','15m_1h','1_4h','4_24h','24_72h','gt72h']\n"
    "band_tot = {b:int(df['nb_'+b].sum()) for b in BANDS}\n"
    "print('taker-opened round-trips by hold band:')\n"
    "for b in BANDS: print(f'   {b:8s}: {band_tot[b]:>10,}')\n"
    "def box(nmin, tk):\n"
    "    m = (df['n_copyable']>=nmin) & (df['taker_share']>=tk)\n"
    "    return int(m.sum())\n"
    "print('\\nwallets in the COPYABLE box (n_copyable = taker-opened 1-24h holds):')\n"
    "for nmin in [50,100,200]:\n"
    "    print(f'   n_copyable>={nmin:3d}: all={box(nmin,0.0):5d} | taker_share>=0.7 {box(nmin,0.7):5d} | >=0.9 {box(nmin,0.9):5d}')"
))

cells.append(nbf.v4.new_markdown_cell("## The picture"))

cells.append(nbf.v4.new_code_cell(
    "d = df.filter((pl.col('n_tk_close')>=1) & pl.col('med_hold_h').is_finite()).to_pandas()\n"
    "fig, ax = plt.subplots(2, 2, figsize=(14, 11)); fig.suptitle('Hold-time × sample-size feasibility (taker-opened round-trips)', fontsize=14)\n"
    "# --- Panel A: n_copyable vs median taker hold, target box highlighted ---\n"
    "a = ax[0,0]\n"
    "sc = a.scatter(np.maximum(d['n_copyable'],0.5), np.maximum(d['med_hold_h'],0.02), c=np.clip(d['taker_share'],0,1),\n"
    "               s=7, alpha=0.35, cmap='viridis')\n"
    "a.set_xscale('log'); a.set_yscale('log'); a.set_xlabel('n_copyable  (taker-opened round-trips, 1–24h hold)'); a.set_ylabel('median taker hold (h)')\n"
    "a.axhspan(1,24, color='orange', alpha=0.06); a.axvline(100, color='red', ls='--', lw=1)\n"
    "a.add_patch(Rectangle((100,1), 1e6, 23, fill=False, edgecolor='red', lw=1.5))\n"
    "nbox = int(((d['n_copyable']>=100)&(d['med_hold_h']>=1)&(d['med_hold_h']<=24)).sum())\n"
    "a.set_title(f'A. copyable-sample vs hold — {nbox} wallets in box (>=100 & 1–24h)'); plt.colorbar(sc, ax=a, label='taker share')\n"
    "# --- Panel B: within-wallet hold DISPERSION (median vs IQR width) — reconciles 'avg is misleading' ---\n"
    "b = ax[0,1]\n"
    "iqr = (d['p75_hold_h']-d['p25_hold_h']).clip(lower=0.01)\n"
    "b.scatter(np.maximum(d['med_hold_h'],0.02), iqr, s=7, alpha=0.3, color='steelblue')\n"
    "b.set_xscale('log'); b.set_yscale('log'); b.set_xlabel('median taker hold (h)'); b.set_ylabel('hold IQR width p75-p25 (h)')\n"
    "b.plot([0.02,1000],[0.02,1000],'k:',lw=1,label='IQR = median (very dispersed)'); b.legend()\n"
    "b.set_title('B. within-wallet hold dispersion (points near/above line = NOT a single hold style)')\n"
    "# --- Panel C: distribution of copyable sample size ---\n"
    "c = ax[1,0]\n"
    "vals = np.clip(d['n_copyable'],0.5,None)\n"
    "c.hist(vals, bins=np.logspace(np.log10(0.5), np.log10(max(vals.max(),10)), 40), color='slateblue', alpha=0.8)\n"
    "c.set_xscale('log'); c.axvline(100, color='red', ls='--', label='n=100'); c.legend()\n"
    "c.set_xlabel('n_copyable per wallet'); c.set_ylabel('# wallets'); c.set_title('C. how many wallets reach a usable copyable sample')\n"
    "# --- Panel D: where the mass of trades actually is (pooled band totals) ---\n"
    "e = ax[1,1]\n"
    "tot = [int(df['nb_'+bb].sum()) for bb in BANDS]\n"
    "cols = ['#bbb','#89c','#4a8','#2a6','#c84','#a44']\n"
    "e.bar(range(len(BANDS)), tot, color=cols); e.set_xticks(range(len(BANDS))); e.set_xticklabels(BANDS, rotation=30)\n"
    "e.set_ylabel('taker-opened round-trips (pooled)'); e.set_title('D. hold-band composition (1–4h & 4–24h = the copyable bands)')\n"
    "for i,v in enumerate(tot): e.text(i, v, f'{v:,}', ha='center', va='bottom', fontsize=8)\n"
    "plt.tight_layout(rect=[0,0,1,0.97]); import os; os.makedirs('../out/figs_hold', exist_ok=True)\n"
    "plt.savefig('../out/figs_hold/hold_feasibility.png', dpi=110, bbox_inches='tight'); plt.show()"
))

cells.append(nbf.v4.new_markdown_cell(
    "## Reading it\n"
    "- **Panel A** is the direct answer to your question: the red box is *≥100 copyable samples AND a 1–24h "
    "median hold*. Its count is how many wallets are even eligible for a per-wallet mid-freq test.\n"
    "- **Panel B** is the reconciliation you asked for: points on/above the dotted line are wallets whose hold "
    "*IQR is as wide as their median* — i.e. they do NOT have a single hold style (48h swings + scalps mixed). "
    "For those, 'average hold' is meaningless and they can't be cleanly labelled a '4h trader'.\n"
    "- **Panel C**: the histogram of `n_copyable` with the n=100 line — most wallets fall short.\n"
    "- **Panel D**: where trades actually concentrate across hold bands."
))

nb['cells'] = cells
with open('notebooks/hold_feasibility.ipynb', 'w') as f:
    nbf.write(nb, f)
print('wrote notebooks/hold_feasibility.ipynb')
