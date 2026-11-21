"""Calendar and holiday features for German load (known in advance, so leakage-safe).

Regional holidays matter: e.g. Corpus Christi is a holiday in about half of Germany by
population. We weight each state by an APPROXIMATE population share (millions, rounded,
hand-entered from Destatis orders of magnitude). This is a labelled approximation; only
relative weights matter.
"""

from __future__ import annotations

from datetime import date, timedelta

import holidays
import polars as pl

STATE_POP_M = {
    "BW": 11.3, "BY": 13.4, "BE": 3.8, "BB": 2.6, "HB": 0.7, "HH": 1.9, "HE": 6.4, "MV": 1.6,
    "NI": 8.1, "NW": 18.1, "RP": 4.2, "SL": 1.0, "SN": 4.1, "ST": 2.2, "SH": 3.0, "TH": 2.1,
}


def calendar_table(first: date, last: date) -> pl.DataFrame:
    years = range(first.year, last.year + 1)
    total = sum(STATE_POP_M.values())
    per_state = {s: holidays.Germany(subdiv=s, years=years) for s in STATE_POP_M}
    rows = []
    d = first
    while d <= last:
        share = sum(STATE_POP_M[s] for s, h in per_state.items() if d in h) / total
        names = sorted({h.get(d) for h in per_state.values() if d in h})
        rows.append((d, share, "; ".join(names) if names else None))
        d += timedelta(days=1)
    df = pl.DataFrame(rows, schema={"date_local": pl.Date, "holiday_pop_share": pl.Float64,
                                    "holiday_names": pl.String}, orient="row")
    return df.with_columns(
        is_national_holiday=pl.col("holiday_pop_share") >= 0.999,
        day_of_week=pl.col("date_local").dt.weekday(),  # 1=Mon .. 7=Sun
        day_of_year=pl.col("date_local").dt.ordinal_day(),
        is_christmas_period=(
            ((pl.col("date_local").dt.month() == 12) & (pl.col("date_local").dt.day() >= 24))
            | ((pl.col("date_local").dt.month() == 1) & (pl.col("date_local").dt.day() <= 1))
        ),
    ).with_columns(
        # Bridge day: Mon before a Tue holiday or Fri after a Thu holiday (pop share > 0.5).
        is_bridge_day=(
            ((pl.col("day_of_week") == 1) & (pl.col("holiday_pop_share").shift(-1) > 0.5))
            | ((pl.col("day_of_week") == 5) & (pl.col("holiday_pop_share").shift(1) > 0.5))
        ).fill_null(False)
    )
