from datetime import date, datetime, timezone

import pytest

from gridmind.contracts.issue_time import IssueRule
from gridmind.timeutils import (
    delivery_day_bounds_utc,
    delivery_day_hours,
    hourly_starts_utc,
    local_at,
)

UTC = timezone.utc
TZ = "Europe/Berlin"


@pytest.mark.parametrize(
    "day,hours",
    [
        (date(2025, 3, 30), 23),  # spring forward
        (date(2025, 10, 26), 25),  # fall back
        (date(2025, 7, 1), 24),
        (date(2024, 3, 31), 23),
        (date(2024, 10, 27), 25),
    ],
)
def test_delivery_day_lengths(day, hours):
    assert delivery_day_hours(day, TZ) == hours
    assert len(hourly_starts_utc(day, TZ)) == hours


def test_bounds_are_utc_interval_starts():
    start, end = delivery_day_bounds_utc(date(2025, 1, 15), TZ)
    assert start == datetime(2025, 1, 14, 23, tzinfo=UTC)
    assert end == datetime(2025, 1, 15, 23, tzinfo=UTC)
    start, end = delivery_day_bounds_utc(date(2025, 7, 15), TZ)
    assert start == datetime(2025, 7, 14, 22, tzinfo=UTC)


def test_local_at_rejects_dst_gap():
    with pytest.raises(ValueError):
        local_at(date(2025, 3, 30), 2, 30, TZ)


def test_issue_time_is_d_minus_1_10_local():
    rule = IssueRule()
    assert rule.issue_time(date(2025, 1, 15)) == datetime(2025, 1, 14, 9, tzinfo=UTC)
    assert rule.issue_time(date(2025, 7, 15)) == datetime(2025, 7, 14, 8, tzinfo=UTC)
    # delivery day after spring-forward: issue day is the 23h day itself (CEST at 10:00)
    assert rule.issue_time(date(2025, 3, 31)) == datetime(2025, 3, 30, 8, tzinfo=UTC)


def test_last_known_load_end_respects_publication_lag():
    rule = IssueRule()
    assert rule.last_known_load_end(date(2025, 1, 15)) == datetime(2025, 1, 14, 7, tzinfo=UTC)


def test_issue_precedes_target_window():
    rule = IssueRule()
    for d in [date(2025, 3, 30), date(2025, 10, 26), date(2025, 6, 1)]:
        start, _ = rule.target_window(d)
        assert rule.issue_time(d) < start
