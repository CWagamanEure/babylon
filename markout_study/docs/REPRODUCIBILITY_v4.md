# Reproducibility package — report v4

Run order (RAM-safe; one heavy job at a time; POLARS_MAX_THREADS≤3):
1. `src/build_entries.py` → `out/entries/part_*.parquet` (bar-net taker entries)
2. `src/cohort_K_define.py`, `src/cohort_K_price.py` → `out/cohort_K.txt`, `out/cohort_K_entries.parquet`
3. `src/cohort_M_freeze.py` → `out/cohort_M_frozen.{txt,parquet}` (fixed 121)
4. `src/pi_compute.py` (heavy, bar-pricing) → `out/eventstudy.json`, `out/entry_features.parquet`
5. `src/verify_v2.py` → `out/termstructure_ci.json`; core table inline → `out/core_markout_table.md`
6. `src/verify_v4.py` (light) → `out/v4.json` (all Phase-1 re-computations)
7. `src/fig_v4.py` → `figs_v4/*.png`
8. pandoc + Chrome headless → `report_v4.pdf` (see below)

PDF build:
`pandoc report_v4.md -f markdown-implicit_figures -o report_v4.html --standalone --embed-resources --css pdf_style_v2.css`
then Chrome `--headless=new --no-pdf-header-footer --print-to-pdf`.

Key inputs: 5-min candle closes (`mkcommon._load_bars`), cand2 taker fills. No BBO/order-book data (execution markout not computable).
Audit trail: `docs/FINAL_AUDIT_NOTE.md`, `docs/CHANGELOG_v4.md`, `docs/NUMBER_SOURCE_MAP.md`, `docs/FINDINGS_LEDGER.md`.
