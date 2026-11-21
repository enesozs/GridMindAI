"""DuckDB views over the processed Parquet tables (no data copied into the .duckdb file)."""

from __future__ import annotations

from pathlib import Path

import duckdb

from gridmind.config import DATA_DIR, PROCESSED_DIR


def connect(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(path or DATA_DIR / "gridmind.duckdb"))
    for p in sorted(PROCESSED_DIR.glob("*.parquet")):
        con.execute(f"CREATE OR REPLACE VIEW {p.stem.replace('-', '_')} AS SELECT * FROM read_parquet('{p}')")
    return con
