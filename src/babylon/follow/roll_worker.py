"""RAM-bounded roll selection via chunked subprocesses.

The roll ranks all ~2431 candidates by loading each one's train-window fills. Two RAM hazards:
1. WHALE READS (the big one): a few HFT wallets have 100-500MB of full history; the old
   `read_parquet(whole).filter` decompressed the entire file (~3GB peak) before windowing. FIXED
   at the source by `ParquetFillsProvider` now using `scan_parquet(...).filter().collect()`
   (predicate pushdown → reads only the windowed rows).
2. POLARS RETENTION: even with scan, a single long-running process that scans 2431 files in a row
   plateaus at ~1GB RSS and never gives it back — so a weeks-long live run would sit bloated at
   ~1GB the whole time on a 1GB box.

This module handles (2): process the pool in CHUNKS, each in its own subprocess that computes its
slice then EXITS — the OS reclaims that subprocess's memory. The long-running PARENT only
accumulates the small per-wallet result arrays, so it stays ~140MB across the whole run, and peak
concurrent RSS during a roll stays ~one chunk (parent + one worker ≈ under 1GB).

Parity: the worker computes via the SAME `SelectionAdapter` the in-process roll uses, so the
chunked roster is bit-identical to the single-process one. Only local (parquet `--fills-dir`) mode
is chunked; REST mode keeps the in-process loop (a subprocess can't share the REST session).
"""

from __future__ import annotations

import pickle
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from babylon.follow.experiment import ExperimentConfig
from babylon.follow.selection import SelectionAdapter

Lookups = dict[str, tuple[np.ndarray, np.ndarray]]
Basket = tuple[np.ndarray, np.ndarray] | None


def compute_returns_chunk(
    wallets: list[str], t0_ms: int, *, config: ExperimentConfig, fills_dir: Path,
    lookups: Lookups, basket: Basket, universe: set[str],
) -> dict[str, dict]:
    """One chunk's per-wallet {returns, cutoff, activity}, computed via a SelectionAdapter over a
    local ParquetFillsProvider — identical to the in-process roll for the same wallets."""
    from babylon.follow.fills_source import ParquetFillsProvider

    adapter = SelectionAdapter(ParquetFillsProvider(Path(fills_dir)), universe=universe,
                               lookups=lookups, config=config, basket=basket)
    out: dict[str, dict] = {}
    for w in wallets:
        r = adapter.returns_fn(w, t0_ms)                  # single-entry cache: one wallet at a time
        out[w] = {"returns": r.tolist(), "cutoff": adapter.cutoff_fn(w, t0_ms),
                  "activity": adapter.activity_fn(w, t0_ms)}
    return out


def chunked_batch_returns(
    candidates: list[str], t0_ms: int, *, config: ExperimentConfig, fills_dir: Path,
    lookups: Lookups, basket: Basket, universe: set[str], chunk_size: int = 120,
    python_exe: str | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, int], dict[str, int]]:
    """Aggregate the whole pool's (returns, cutoffs, activity) by farming chunks to worker
    subprocesses. The shared per-roll data (config, lookups, basket, universe) is pickled ONCE and
    every worker loads that one file; each job pickle is just its wallet slice."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be ≥1")
    returns: dict[str, np.ndarray] = {}
    cutoffs: dict[str, int] = {}
    activity: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="roll_chunks_") as td:
        work = Path(td)
        shared = work / "shared.pkl"
        with shared.open("wb") as f:
            pickle.dump({"config": config, "fills_dir": str(fills_dir), "lookups": lookups,
                         "basket": basket, "universe": set(universe)}, f)
        exe = python_exe or sys.executable
        chunks = [candidates[i:i + chunk_size] for i in range(0, len(candidates), chunk_size)]
        for ci, chunk in enumerate(chunks):
            job = work / f"job_{ci}.pkl"
            outp = work / f"out_{ci}.pkl"
            with job.open("wb") as f:
                pickle.dump({"wallets": chunk, "t0_ms": t0_ms, "shared": str(shared)}, f)
            subprocess.run([exe, "-m", "babylon.follow.roll_worker", str(job), str(outp)],
                           check=True)
            with outp.open("rb") as f:
                res = pickle.load(f)
            for w, d in res.items():
                returns[w] = np.asarray(d["returns"], dtype=np.float64)
                cutoffs[w] = int(d["cutoff"])
                activity[w] = int(d["activity"])
            job.unlink(missing_ok=True)
            outp.unlink(missing_ok=True)
    return returns, cutoffs, activity


def _worker_main(argv: list[str]) -> int:
    job_path, out_path = Path(argv[0]), Path(argv[1])
    with job_path.open("rb") as f:
        job = pickle.load(f)
    with Path(job["shared"]).open("rb") as f:
        shared = pickle.load(f)
    res = compute_returns_chunk(
        job["wallets"], int(job["t0_ms"]), config=shared["config"],
        fills_dir=Path(shared["fills_dir"]), lookups=shared["lookups"], basket=shared["basket"],
        universe=set(shared["universe"]))
    with out_path.open("wb") as f:
        pickle.dump(res, f)
    return 0


if __name__ == "__main__":
    raise SystemExit(_worker_main(sys.argv[1:]))
