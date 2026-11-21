from datetime import date, datetime, timezone

import polars as pl
import pytest

from gridmind.forecasting import live


def test_track_record_is_append_only(tmp_path, monkeypatch):
    track = tmp_path / "live_forecasts.csv"
    monkeypatch.setattr(live, "TRACK", track)
    row = {k: [None] for k in live.SCHEMA}
    row.update(delivery_day=[date(2026, 11, 16)], valid_at_utc=[datetime(2026, 11, 15, 23, tzinfo=timezone.utc)],
               model=["gbm_weather"], on_time=[True])
    pl.DataFrame(row, schema=live.SCHEMA).write_csv(track)
    before = track.read_text()
    with pytest.raises(ValueError, match="append-only"):
        live.issue_live(date(2026, 11, 16), now=datetime(2026, 11, 15, 7, tzinfo=timezone.utc))
    assert track.read_text() == before  # nothing rewritten
