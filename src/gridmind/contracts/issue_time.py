"""The issue-time contract: what a day-ahead forecast is allowed to know.

A forecast is identified by (zone, issue_time, valid_time, horizon, model_version).
For delivery day D the forecast is issued at D-1 10:00 local market time: the same
deadline by which TSOs must publish their own day-ahead total load forecast (EU
Regulation 543/2013, Art. 6.1(b): at least two hours before day-ahead gate closure,
which is 12:00 CET). Issuing at the same deadline makes the comparison with the TSO
forecast fair.

Information available at issue time:
- actual load: only intervals that END at or before `issue_time - load_publication_lag`.
- weather: only forecasts whose (nominal) run time + availability_lag <= issue_time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from gridmind.timeutils import delivery_day_bounds_utc, local_at


@dataclass(frozen=True)
class IssueRule:
    tz: str = "Europe/Berlin"
    issue_hour_local: int = 10
    issue_minute_local: int = 0
    # Actual load is published "no later than one hour after the operating period";
    # we assume 2 h to be conservative.
    load_publication_lag: timedelta = timedelta(hours=2)

    def issue_time(self, delivery_day: date) -> datetime:
        return local_at(
            delivery_day - timedelta(days=1),
            self.issue_hour_local,
            self.issue_minute_local,
            self.tz,
        )

    def target_window(self, delivery_day: date) -> tuple[datetime, datetime]:
        return delivery_day_bounds_utc(delivery_day, self.tz)

    def last_known_load_end(self, delivery_day: date) -> datetime:
        """Latest interval END time whose actual load may be used as a feature."""
        t = self.issue_time(delivery_day) - self.load_publication_lag
        return t.replace(minute=0, second=0, microsecond=0)


# Publication lag of the weather forecasts we use. GridMind's weather is a fixed-lead
# archive (Open-Meteo "previous_day2"): every value was predicted 48 h before its valid
# time, so its nominal run time is valid - 48 h. 6 h is a conservative allowance for the
# run to be published. assert_point_in_time checks run + lag <= issue for every row.
WEATHER_AVAILABILITY_LAG: dict[str, timedelta] = {
    "openmeteo-gfs_seamless-previous_day2": timedelta(hours=6),
}
