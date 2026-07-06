"""
Stage L, Job L1: GROUND-TRUTH vault/entity tagging of the frozen cohort_K wallets via the HL info API.
{"type":"userRole","user":addr} -> {"role": "user"|"vault"|"agent"|...}. is_vault := role=="vault".
Present-day identity (slow-moving, not performance) applied retroactively -> acceptable per design audit.
NETWORK job, RAM-free, throttled ~4/s. Resumable: skips wallets already in the output. -> out/cohort_K_vault.parquet
"""
import json, time, urllib.request
from pathlib import Path
import polars as pl

API = "https://api.hyperliquid.xyz/info"
OUT = Path("out/cohort_K_vault.parquet")
# known protocol vaults (HLP) for explicit tagging beyond the role flag
KNOWN_VAULT = {"0xdfc24b077bc1425ad1dea75bcb6f8158e10df303": "HLP"}

def role_of(addr, retries=4):
    body = json.dumps({"type": "userRole", "user": addr}).encode()
    for k in range(retries):
        try:
            req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode())
            # response shapes seen: {"role":"user"} or {"role":"vault"} or nested {"role":{"role":...}}
            role = d.get("role") if isinstance(d, dict) else None
            if isinstance(role, dict):
                role = role.get("role")
            return role if isinstance(role, str) else "unknown"
        except Exception:
            time.sleep(1.0 + 1.5 * k)
    return "error"

wallets = [l.strip() for l in open("out/cohort_K.txt") if l.strip()]
done = {}
if OUT.exists():
    prev = pl.read_parquet(OUT)
    done = dict(zip(prev["wallet"].to_list(), prev["role"].to_list()))
    print(f"resuming: {len(done)} already tagged", flush=True)

rows = [(w, done[w]) for w in wallets if w in done]
todo = [w for w in wallets if w not in done]
print(f"tagging {len(todo)} / {len(wallets)} cohort wallets via userRole...", flush=True)
for i, w in enumerate(todo):
    r = role_of(w.lower())
    rows.append((w, r))
    time.sleep(0.25)                       # ~4 req/s, polite
    if (i + 1) % 100 == 0:
        pl.DataFrame(rows, schema=["wallet", "role"], orient="row").write_parquet(OUT)  # checkpoint
        print(f"  {i+1}/{len(todo)}", flush=True)

df = pl.DataFrame(rows, schema=["wallet", "role"], orient="row")
df = df.with_columns(
    is_vault=(pl.col("role") == "vault")
    | pl.col("wallet").str.to_lowercase().is_in(list(KNOWN_VAULT))
)
df.write_parquet(OUT)
print(f"\nwrote {df.height} -> {OUT}")
print("role distribution:")
print(df.group_by("role").agg(pl.len()).sort("len", descending=True))
print(f"is_vault: {df['is_vault'].sum()}")
