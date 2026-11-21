from gridmind.storage import read_manifest, store_raw


def test_store_raw_is_content_addressed_and_strips_secrets(tmp_path):
    rec = store_raw(
        b"<xml/>",
        source="s",
        dataset="d",
        params={"zone": "DE_LU", "securityToken": "SECRET"},
        licence="test",
        suffix=".xml",
        raw_dir=tmp_path,
    )
    assert (tmp_path / rec.path).read_bytes() == b"<xml/>"
    assert "securityToken" not in rec.params
    manifest_text = (tmp_path / "manifest.jsonl").read_text()
    assert "SECRET" not in manifest_text
    rec2 = store_raw(b"<xml/>", source="s", dataset="d", params={}, licence="t", suffix=".xml", raw_dir=tmp_path)
    assert rec2.sha256 == rec.sha256
    assert len(read_manifest(tmp_path)) == 2


def test_write_actuals_merges_incrementally(tmp_path):
    from datetime import datetime, timezone

    import polars as pl

    from gridmind.ingest.smard_ingest import write_actuals

    t = [datetime(2025, 1, 1, h, tzinfo=timezone.utc) for h in range(3)]

    def frame(ts, vals):
        return pl.DataFrame({"zone_id": "Z", "metric": "m", "timestamp_utc": ts, "value_mw": vals},
                            schema_overrides={"timestamp_utc": pl.Datetime("us", "UTC")})

    write_actuals(frame(t, [1.0, 2.0, 3.0]), tmp_path)
    write_actuals(frame(t[2:], [30.0]), tmp_path)  # revised last value only
    out = pl.read_parquet(tmp_path / "actuals_qh.parquet").sort("timestamp_utc")
    assert out["value_mw"].to_list() == [1.0, 2.0, 30.0]
