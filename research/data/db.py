"""DuckDB query layer for the research workbench — an embedded lens over the Parquet lake (no ETL).

    from research.data.db import connect
    con = connect()
    con.sql("SELECT coin, count(*) FROM fills WHERE month=202508 GROUP BY coin")

`connect()` returns a DuckDB connection with views registered over `data/raw` + `data/derived`. Views whose
Parquet doesn't exist yet are skipped (so it works while the tape is still landing). The Parquet stays the
source of truth; nothing is copied into DuckDB.
"""
from __future__ import annotations
from pathlib import Path
from glob import glob as _glob
import duckdb
from . import schema

REPO_ROOT = Path(__file__).resolve().parents[2]   # research/data/db.py -> repo root
DATA_DIR = REPO_ROOT / "data"


def _has_files(rel_glob: str) -> bool:
    return bool(_glob(str(DATA_DIR / rel_glob), recursive=True))


def connect(data_dir: Path = DATA_DIR, warn_missing: bool = True) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()                          # in-memory; views recreated fresh each session
    registered = []
    for name, rel in schema.DATASET_GLOBS.items():
        absglob = str(data_dir / rel)
        if not _glob(absglob, recursive=True):
            if warn_missing:
                print(f"[db] skip view '{name}' — no parquet yet at {rel}")
            continue
        if name == "fills":
            con.execute(schema.fills_views_sql(absglob))
        else:                                           # incl. alt_flow — SEPARATE view, never unioned into `fills`
            con.execute(schema.simple_view_sql(name, absglob))
        registered.append(name)
    con.execute("SET TimeZone='UTC'")
    if registered:
        print(f"[db] views: {', '.join(registered)}")
    return con


def render_catalog(data_dir: Path = DATA_DIR) -> str:
    """Emit the CREATE VIEW SQL as text (for `duckdb -c \".read catalog.sql\"` CLI use)."""
    parts = []
    for name, rel in schema.DATASET_GLOBS.items():
        absglob = str(data_dir / rel)
        if name == "fills":
            parts.append(schema.fills_views_sql(absglob))
        else:
            parts.append(schema.simple_view_sql(name, absglob))
    return "\n".join(parts)


if __name__ == "__main__":
    con = connect()
    try:
        print(con.sql("SELECT coin, count(*) AS fills FROM fills GROUP BY coin ORDER BY fills DESC"))
    except duckdb.CatalogException:
        print("[db] no 'fills' view yet — tape not migrated to data/raw/ (still in scratchpad).")
