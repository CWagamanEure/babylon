"""Layer A — live position + entry-VWAP reconstruction (foundation of the ANTICIPATION engine).

Streams fills per wallet (causal), maintains signed position + entry-VWAP with episode resets, tags
left-censored basis (positions opened before the tape), and VALIDATES via closed_pnl reconciliation
(correctness-audit gate). This feeds the live fuel map -> P(reach zone) -> trade-the-run-in signal.

Correctness fixes baked in (design audit): order by (wallet, ts, event_index); signed size by side
(fail-loud on non-B/A); add/close decided SIGN-RELATIVE to position (not by side); flips split into
close-portion + open-residual (VWAP reseeds at the flip px); liq/forced closes never re-weight VWAP;
first-seen fill with start_position != 0 => censored basis (VWAP unknowable, tracked but not invented).

  .venv/bin/python -m research.studies.liq_fuel_map.reconstruct validate SOL 202508
"""
import sys
import numpy as np
from research.data.db import connect

EPS = 1e-9


def _load(coin, month, con):
    q = f"""
      SELECT wallet,
             CASE WHEN side='B' THEN 1.0 WHEN side='A' THEN -1.0 ELSE NULL END AS s,
             sz_d::DOUBLE AS sz, px_d::DOUBLE AS px,
             start_position_d::DOUBLE AS sp, closed_pnl_d::DOUBLE AS cpnl,
             is_liq_origin AS liq
      FROM fills WHERE coin='{coin}' AND month={month}
      ORDER BY wallet, ts, event_index
    """
    t = con.execute(q).fetch_arrow_table()
    d = {c: t[c].to_numpy(zero_copy_only=False) for c in ("wallet", "s", "sz", "px", "sp", "cpnl", "liq")}
    if np.isnan(d["s"].astype(float)).any():
        raise ValueError("side not in {B,A} on some rows — fail loud (correctness-F4)")
    return d


def reconstruct(coin, month, con):
    d = _load(coin, month, con)
    W, S, SZ, PX, SP, CP, LIQ = (d["wallet"], d["s"].astype(float), d["sz"].astype(float),
                                 d["px"].astype(float), d["sp"].astype(float), d["cpnl"].astype(float),
                                 d["liq"].astype(bool))
    n = len(W)
    pos, vwap, cens = {}, {}, {}      # wallet -> signed position / entry vwap (None=flat/unknown) / censored bool
    seen = set()
    my_pnl_sum = 0.0; abs_err_list = []; n_close_known = 0
    cens_wallets = set()
    for i in range(n):
        w = W[i]; ssz = S[i] * SZ[i]; p = PX[i]
        if w not in seen:
            seen.add(w); pos[w] = SP[i]
            if abs(SP[i]) > EPS:                     # opened before tape -> basis unknowable
                vwap[w] = None; cens[w] = True; cens_wallets.add(w)
            else:
                vwap[w] = None; cens[w] = False
        pb = pos[w]; nb = pb + ssz
        if abs(pb) < EPS:                            # open from flat
            vwap[w] = p; cens[w] = False
        elif (pb > 0) == (ssz > 0):                  # ADD (same sign) -> re-weight VWAP
            if vwap[w] is not None:
                vwap[w] = (vwap[w] * abs(pb) + p * abs(ssz)) / (abs(pb) + abs(ssz))
        else:                                        # reduce / close / flip (opposite sign)
            closed = min(abs(ssz), abs(pb))
            if vwap[w] is not None:                  # realized pnl on closed portion (validation)
                pnl = (p - vwap[w]) * closed * np.sign(pb)
                my_pnl_sum += pnl
                abs_err_list.append(abs(pnl - CP[i])); n_close_known += 1
            if abs(ssz) > abs(pb) + EPS:             # FLIP -> reseed VWAP at flip px on the residual
                vwap[w] = p; cens[w] = False
            elif abs(nb) < EPS:                       # FULL close -> flat
                vwap[w] = None
            # else PARTIAL close -> VWAP unchanged
        pos[w] = nb
    # standing book at month end
    open_pos = {w: pos[w] for w in pos if abs(pos[w]) > EPS}
    return dict(n_fills=n, n_wallets=len(seen), n_open_end=len(open_pos),
                cens_wallet_frac=len(cens_wallets) / max(len(seen), 1),
                n_close_known=n_close_known,
                pnl_med_abs_err=float(np.median(abs_err_list)) if abs_err_list else None,
                pnl_p95_abs_err=float(np.quantile(abs_err_list, 0.95)) if abs_err_list else None,
                my_pnl_sum=my_pnl_sum,
                pos=pos, vwap=vwap, cens=cens)


def validate(coin, month):
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='3000MB'; SET threads=3")
    r = reconstruct(coin, month, con)
    print(f"=== reconstruct {coin} {month} ===")
    for k in ("n_fills", "n_wallets", "n_open_end", "cens_wallet_frac",
              "n_close_known", "pnl_med_abs_err", "pnl_p95_abs_err"):
        print(f"  {k:22s} {r[k]}")
    print("  (pnl_*_abs_err = |my realized pnl - closed_pnl_d| per close; ~0 => VWAP logic correct)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        validate(sys.argv[2] if len(sys.argv) > 2 else "SOL", int(sys.argv[3]) if len(sys.argv) > 3 else 202508)
