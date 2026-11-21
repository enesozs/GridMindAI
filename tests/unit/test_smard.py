"""SYNTHETIC SMARD payloads in the documented chart_data format (not real data)."""

import json
from datetime import datetime, timezone

from gridmind.providers.smard import parse_week

UTC = timezone.utc


def test_quarter_hour_mwh_converted_to_mw():
    t0 = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp() * 1000)
    payload = {
        "meta_data": {"version": 1, "created": t0},
        "series": [[t0, 13000.0], [t0 + 900_000, None], [t0 + 1_800_000, 12500.5]],
    }
    df, created = parse_week(json.dumps(payload).encode(), "quarterhour")
    assert df["value_mw"].to_list() == [52000.0, None, 50002.0]
    assert df["energy_mwh"].to_list() == [13000.0, None, 12500.5]
    assert df["timestamp_utc"][0] == datetime(2025, 1, 1, tzinfo=UTC)
    assert df["resolution_minutes"].to_list() == [15, 15, 15]
    assert created == datetime(2025, 1, 1, tzinfo=UTC)


def test_hourly_resolution_mwh_equals_mw():
    t0 = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp() * 1000)
    df, _ = parse_week(json.dumps({"series": [[t0, 50000.0]]}).encode(), "hour")
    assert df["value_mw"].to_list() == [50000.0]


def test_empty_series():
    df, created = parse_week(b'{"series": []}', "quarterhour")
    assert df.is_empty() and created is None
