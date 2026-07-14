"""Build + execute the xsec cross-sectional book dashboard notebook (run with /opt/miniconda3/bin/python)."""
import nbformat as nbf
from nbclient import NotebookClient

nb = nbf.v4.new_notebook()
C = []
def md(s): C.append(nbf.v4.new_markdown_cell(s))
def code(s): C.append(nbf.v4.new_code_cell(s))

md("""# Cross-Sectional Wallet-Selection Edge — Dashboard
**Result 10** of the wallet-flow line: the first fully-hardened positive on the whole arc.

**What the signal is:** a cohort of ~1,500 skill-weighted "informed" Hyperliquid wallets. Each hour we read
*which alts they're rotating into vs out of*, relative to their own recent book, **counting wallets not dollars**
(size-blind breadth), skill-weighted. That per-alt signal predicts which alts beat/lag their peers over the next
~4h, after stripping BTC/ETH beta.

**Headline:** rank-IC **+0.023 (z≈8)**, 39/45 coins, survives leakage + Bonferroni + a full prosecutor pass.
Taker ≈ break-even (the spread eats the ~2bp/hr alpha); **maker is a powered positive** (+3.2–3.8 bp/hr, 7/7
folds) because it *earns* the spread instead of paying it. The forward paper follower is now live measuring the
one unknown offline can't: the passive-fill rate.""")

code("""import json, numpy as np, matplotlib.pyplot as plt, matplotlib.dates as mdates
from datetime import datetime, timezone
from pathlib import Path
plt.rcParams.update({'figure.dpi':110,'axes.grid':True,'grid.alpha':.3,'font.size':10})
D=Path('data/derived')
adj=json.load(open(D/'xsec_flow_adjudicate/results.json'))
dec=json.load(open(D/'xsec_flow_decompose/results.json'))
con=json.load(open(D/'xsec_concentrated_book/results.json'))
pol=json.load(open(D/'xsec_pollable_validate/results.json'))
viz=json.load(open(D/'xsec_viz/viz.json'))
VT=dec['V-trail']
def dt(ms): return datetime.fromtimestamp(ms/1000, tz=timezone.utc)
print('loaded. viz steps:', len(viz['series']['hour_ms']), '| impact half-spread median %.2fbp'%viz['impact_hs_median_bp'])""")

md("""## 1. The edge over time — cumulative paper PnL of the decile book
Each line is the running sum of per-rebalance net PnL (bp) across the 7 walk-forward months. The **maker** legs
(earning the spread, under 0 / 30% / 50% adverse-selection haircuts) climb steadily; the **taker** leg (paying the
spread) is roughly flat — same signal, the spread is the whole difference. Grey = raw gross (pre-cost).""")
code("""s=viz['series']; x=[dt(m) for m in s['hour_ms']]
fig,ax=plt.subplots(figsize=(11,5))
def cum(k,**kw): ax.plot(x, np.cumsum(s[k]), **kw)
cum('gross_bp', color='0.6', lw=1, ls='--', label='gross (pre-cost)')
cum('maker_earn_a0', color='#1a7f37', lw=2, label='maker earn-spread (0% adverse)')
cum('maker_earn_a30', color='#2da44e', lw=2, label='maker (30% adverse) — central')
cum('maker_earn_a50', color='#56d364', lw=1.7, label='maker (50% adverse) — pessimistic')
cum('taker_top_smallclip', color='#cf222e', lw=1.7, label='taker (top fee, small clip)')
cum('taker_top_impact', color='#fa8', lw=1.3, ls=':', label='taker (top fee, impact spread)')
ax.axhline(0,color='k',lw=.7); ax.set_ylabel('cumulative net PnL (bp)'); ax.set_title('Decile long-short book — cumulative paper PnL over the 7 walk-forward months')
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m')); ax.legend(fontsize=8,loc='upper left'); plt.tight_layout(); plt.show()
print('final cumulative bp — maker a30: %.0f | maker a50: %.0f | taker smallclip: %.0f | gross: %.0f'%(
    np.sum(s['maker_earn_a30']),np.sum(s['maker_earn_a50']),np.sum(s['taker_top_smallclip']),np.sum(s['gross_bp'])))""")

md("""## 2. Signal strength month by month (IC)
Rank-IC of the signal vs the forward peer-rank, per walk-forward month. Positive every month = the 7/7 fold
agreement that drives the month-block significance (sign p≈0.016). One weak/negative month is normal for a real
edge; the consistency is what matters.""")
code("""mic=viz['monthly_ic']; ms=sorted(mic); ys=[mic[m] for m in ms]
fig,ax=plt.subplots(figsize=(9,3.6))
ax.bar([str(m) for m in ms], ys, color=['#2da44e' if (y or 0)>0 else '#cf222e' for y in ys])
ax.axhline(0,color='k',lw=.7); ax.set_ylabel('rank-IC'); ax.set_title('Per-month signal IC (V-trail, h=4)')
for i,y in enumerate(ys):
    if y is not None: ax.text(i,y+ (0.001 if y>=0 else -0.003),'%.3f'%y,ha='center',fontsize=8)
plt.tight_layout(); plt.show()
npos=sum(1 for y in ys if (y or 0)>0); print(f'{npos}/{len(ys)} months positive')""")

md("""## 3. Information vs impact — the gap-lag decay
Left: IC against the return *k* hours ahead — it decays smoothly out to ~4–8h (not a 1-hour spike). Right: IC when
you **skip** the first g hours before entering. ~67% of the edge survives a **1-hour gap** and ~33% a **2-hour
gap** (labels are % of the no-gap IC) → this is genuine forward *information*, not the cohort's own price impact,
which would collapse to ~0 under any entry delay.""")
code("""gl=adj['primary_Vsim']['h4']['gap_lag']; kc=gl['k_curve']['all']; gp=gl['gapped']['all']
fig,(a1,a2)=plt.subplots(1,2,figsize=(11,3.8))
a1.plot(range(1,len(kc)+1), kc, marker='o', color='#0969da'); a1.axhline(0,color='k',lw=.6)
a1.set_xlabel('hours ahead (k)'); a1.set_ylabel('IC(signal, resid[t+k])'); a1.set_title('Forward IC decay')
gaps=['g0','g1','g2','g4']; lab=['no gap','1h gap','2h gap','4h gap']; vals=[gp[g]['ic'] for g in gaps]
a2.bar(lab, vals, color='#8250df'); a2.axhline(0,color='k',lw=.6); a2.set_ylabel('gapped cumulative IC')
a2.set_title('Edge surviving an entry delay');
for i,v in enumerate(vals): a2.text(i,v+.0004,'%.0f%%'%(100*v/vals[0]),ha='center',fontsize=8)
plt.tight_layout(); plt.show(); print('verdict:', gl['decision']['all']['verdict'] if isinstance(gl['decision']['all'],dict) else gl['decision']['all'])""")

md("""## 4. Which hold horizon to harvest
Gross spread per rebalance keeps rising to ~h8–12 but net-per-*hour* (after maker cost, amortized over the hold)
peaks around **h=3–4** and dies by h=24. That's why the book rebalances every 4h.""")
code("""hs=VT['D1_horizon_sweep']; H=sorted(int(k[1:]) for k in hs)
g=[hs['h%d'%h]['all']['gross_bp'] for h in H]; nph=[hs['h%d'%h]['all'].get('per_hour_bp') for h in H]
netm=[hs['h%d'%h]['all'].get('net_at_maker_bp') for h in H]
fig,ax=plt.subplots(figsize=(9,4)); ax.plot(H,g,marker='o',label='gross bp/crossing',color='#0969da')
ax.plot(H,netm,marker='s',label='net @maker (bp/crossing)',color='#2da44e')
ax2=ax.twinx(); ax2.plot(H,nph,marker='^',ls='--',color='#bf8700',label='gross bp/HOUR (right)')
ax.axhline(0,color='k',lw=.6); ax.set_xlabel('hold horizon (hours)'); ax.set_ylabel('bp per crossing')
ax2.set_ylabel('bp per hour'); ax.set_title('Horizon sweep (V-trail decile)')
l1,la1=ax.get_legend_handles_labels(); l2,la2=ax2.get_legend_handles_labels(); ax.legend(l1+l2,la1+la2,fontsize=8)
plt.tight_layout(); plt.show()""")

md("""## 5. The tail carries it — extremity gradient
Widening from quintile (top/bottom 20%) to decile (10%) to ventile (5%) roughly doubles the spread. The conviction
is in the extremes; equal-weighting the broad quintile dilutes it. (Decile is the deployed sweet spot — ventile is
too few names.) Bars show gross bp/crossing at h=4 with 95% CIs.""")
code("""ex=VT['D2_extremity']['h4']; order=['quintile','decile','ventile','conviction']
g=[ex[k]['all']['gross_bp'] for k in order]; lo=[ex[k]['all']['ci95'][0] for k in order]; hi=[ex[k]['all']['ci95'][1] for k in order]
fig,ax=plt.subplots(figsize=(8,4)); xs=range(len(order))
ax.bar(xs,g,color=['#54aeff','#0969da','#0a3069','#8250df']);
ax.errorbar(xs,g,yerr=[np.array(g)-np.array(lo),np.array(hi)-np.array(g)],fmt='none',ecolor='k',capsize=4)
ax.axhline(3.6,color='#cf222e',ls='--',lw=1,label='maker round-trip cost 3.6bp'); ax.axhline(0,color='k',lw=.6)
ax.set_xticks(xs); ax.set_xticklabels(order); ax.set_ylabel('gross bp/crossing'); ax.set_title('Extremity gradient (V-trail h=4)'); ax.legend(fontsize=8)
plt.tight_layout(); plt.show()""")

md("""## 6. When the edge is strong — dispersion regime
Splitting hours by cross-sectional dispersion (how much alts are decoupling): the signal roughly doubles in the
**mid** third and is ~flat in the low/high thirds. Selection works when there's coherent structure to rank.""")
code("""rg=VT['D4_regime']; buckets=['low','mid','high']
g=[rg[b]['all']['gross_bp'] for b in buckets]; lo=[rg[b]['all']['ci95'][0] for b in buckets]; hi=[rg[b]['all']['ci95'][1] for b in buckets]
fig,ax=plt.subplots(figsize=(7,3.8)); xs=range(3)
ax.bar(xs,g,color=['#afb8c1','#2da44e','#afb8c1']); ax.errorbar(xs,g,yerr=[np.array(g)-np.array(lo),np.array(hi)-np.array(g)],fmt='none',ecolor='k',capsize=4)
ax.axhline(0,color='k',lw=.6); ax.set_xticks(xs); ax.set_xticklabels(['low disp','MID disp','high disp'])
ax.set_ylabel('gross bp/crossing'); ax.set_title('Regime split (V-trail decile h=4)'); plt.tight_layout(); plt.show()""")

md("""## 7. Breadth — it's not one or two lucky coins
Per-coin IC across the 45 alts. The bulk are positive (the sign test that gives 39/45). A broad, diversified,
market-neutral effect — stronger in the liquid names (good for trading).""")
code("""pc=VT['D3_per_coin']['all']['per_coin']; items=sorted(pc.items(), key=lambda x:x[1])
names=[k for k,_ in items]; vals=[v for _,v in items]
fig,ax=plt.subplots(figsize=(11,4)); ax.bar(range(len(vals)),vals,color=['#2da44e' if v>0 else '#cf222e' for v in vals])
ax.axhline(0,color='k',lw=.6); ax.set_xticks(range(len(names))); ax.set_xticklabels(names,rotation=90,fontsize=6)
ax.set_ylabel('per-coin IC'); npos=sum(1 for v in vals if v>0); ax.set_title(f'Per-coin IC — {npos}/{len(vals)} positive')
plt.tight_layout(); plt.show()""")

md("""## 8. Does it survive a *pollable* cohort? (the deploy gate)
A live follower can only poll ~1,500 wallets. This shows the maker net-per-hr as we shrink the cohort by skill
weight. The powered positive **survives to top-1500** (7/7 folds) — unlike a pure-breadth signal that would decay.
This is the gate that killed the earlier alt-timing deploy; here it passes.""")
code("""bk=pol['by_K']; Ks=['None','2500','1500','1000']; klab=['full','2500','1500','1000']
def grab(K,sc): e=bk[K]['scenarios'][sc]; return e['net'],e['ci95'],e['folds_pos'],e['n_folds']
fig,ax=plt.subplots(figsize=(8,4))
for sc,col in [('maker_earn_a30','#2da44e'),('maker_earn_a50','#56d364'),('taker_top_smallclip','#cf222e')]:
    n=[grab(K,sc)[0] for K in Ks]; lo=[grab(K,sc)[1][0] for K in Ks]; hi=[grab(K,sc)[1][1] for K in Ks]
    ax.errorbar(range(4),n,yerr=[np.array(n)-np.array(lo),np.array(hi)-np.array(n)],marker='o',capsize=3,color=col,label=sc)
ax.axhline(0,color='k',lw=.6); ax.set_xticks(range(4)); ax.set_xticklabels(klab); ax.invert_xaxis()
ax.set_xlabel('cohort size (wallets)'); ax.set_ylabel('net bp/hr'); ax.set_title('Pollability: maker positive vs cohort size'); ax.legend(fontsize=8)
plt.tight_layout(); plt.show(); print('deployed cohort = top-1500')""")

md("""## 9. The deploy bracket — taker floor vs maker upside
Net-per-hr on the deployed config under the pre-registered cost scenarios, with day-block CIs. Taker ≈ break-even
(CI straddles 0); maker clears zero across the whole adverse-selection bracket. The forward test measures where in
this bracket reality falls (the passive-fill rate).""")
code("""pm=con['compare_pooled']['reb4']['scenarios']
order=['taker_base_impact','taker_top_impact','taker_top_smallclip','maker_earn_a50','maker_earn_a30','maker_earn_a0']
n=[pm[k]['net_bp_per_hr'] for k in order]; lo=[pm[k]['ci95'][0] for k in order]; hi=[pm[k]['ci95'][1] for k in order]
cols=['#cf222e','#fa8072','#ffb3a7','#56d364','#2da44e','#1a7f37']
fig,ax=plt.subplots(figsize=(9,4)); ys=range(len(order))
ax.barh(list(ys),n,color=cols); ax.errorbar(n,list(ys),xerr=[np.array(n)-np.array(lo),np.array(hi)-np.array(n)],fmt='none',ecolor='k',capsize=3)
ax.axvline(0,color='k',lw=.7); ax.set_yticks(list(ys)); ax.set_yticklabels(order); ax.set_xlabel('net bp/hr')
ax.set_title('Deploy scenario ladder (pooled decile, reb=4, all 7 folds)'); plt.tight_layout(); plt.show()""")

md("""## Takeaways & open levers
- **Real, hardened edge.** IC +0.023 (z≈8), 39/45 coins, survives every adversarial check — the first on this line.
- **Maker, not taker.** The ~2bp/hr alpha is thin vs the ~3.25bp half-spread: you must *provide* liquidity. Maker
  = powered positive (+3.2–3.8/hr, 7/7 folds); taker ≈ break-even.
- **Deployable-shaped.** Survives concentration to a pollable 1,500-wallet cohort; live paper follower running.
- **The one unknown = passive-fill rate**, now being measured forward (offline data can't).
- **Untested lever — Kalman / EMA smoothing of the signal** (never built): would raise membership persistence →
  cut turnover → could rescue the taker leg and tighten the maker. The highest-EV next offline experiment.""")

nb.cells = C
nb.metadata['kernelspec'] = {'name':'python3','display_name':'Python 3'}
NotebookClient(nb, timeout=600, kernel_name='python3', resources={'metadata':{'path':'.'}}).execute()
nbf.write(nb, 'notebooks/xsec_book_dashboard.ipynb')
print('WROTE notebooks/xsec_book_dashboard.ipynb with', len(nb.cells), 'cells')
errs=[o for c in nb.cells if c.cell_type=='code' for o in c.get('outputs',[]) if o.get('output_type')=='error']
print('errors:', len(errs))
for e in errs[:3]: print(' -', e.get('ename'), str(e.get('evalue'))[:200])
