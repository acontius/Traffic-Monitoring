"""Canonical timezone + calendar context for every temporal feature the ML
layer builds (SRS-equivalent spec §12, §53, §54).

The canonical *stored* timestamp stays UTC/tz-aware (unchanged from the rest
of the app); this module is the single place that converts to the
operational traffic timezone (`TCMS_TRAFFIC_TIMEZONE`, default
`Asia/Tehran`) before deriving hour-of-day/day-of-week/holiday features, so
no other module needs to reason about timezones directly.

Persian calendar conversion uses `jdatetime` (pure Python, per spec §54)
rather than hand-rolled arithmetic. If it isn't installed, Persian-calendar
fields degrade to `None`/`False` — the Gregorian-based features (weekday,
weekend, month, season) still work, so anomaly scoring and reconstruction
never hard-fail on a missing dependency.
"""

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone as dt_timezone
from typing import Optional
from zoneinfo import ZoneInfo

from Backend.app.core.config import get_settings

try:
    import jdatetime

    _HAS_JDATETIME = True
except ImportError:  # pragma: no cover - exercised only when dep is missing
    _HAS_JDATETIME = False

# Iran's weekend is Friday only (Python's date.weekday(): Monday=0 .. Sunday=6).
WEEKEND_WEEKDAYS = {4}

# Nowruz: the 4 official holiday days at the start of Farvardin. A small,
# explicit, documented rule rather than a hard-to-audit lookup table — real
# deployments extend this via the `traffic_events` table for anything more
# specific (§12).
NOWRUZ_MONTH = 1
NOWRUZ_HOLIDAY_DAYS = {1, 2, 3, 4}

SEASON_BY_MONTH = {
    12: "winter",
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
}


def get_timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().traffic_timezone)


def to_local(ts: datetime) -> datetime:
    """Converts a tz-aware (or assumed-UTC) timestamp to the traffic
    timezone. Never mixes naive/aware datetimes (§53)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt_timezone.utc)
    return ts.astimezone(get_timezone())


@dataclass
class DayContext:
    local_ts: datetime
    is_weekend: bool
    is_nowruz: bool
    is_official_holiday: bool  # is_weekend OR is_nowruz — for feature use
    month: int
    season: str
    persian_year: Optional[int]
    persian_month: Optional[int]
    persian_day: Optional[int]
    persian_weekday: Optional[int]


def classify_day(ts: datetime) -> DayContext:
    local_ts = to_local(ts)
    is_weekend = local_ts.weekday() in WEEKEND_WEEKDAYS

    persian_year = persian_month = persian_day = persian_weekday = None
    is_nowruz = False
    if _HAS_JDATETIME:
        jd = jdatetime.datetime.fromgregorian(datetime=local_ts)
        persian_year, persian_month, persian_day = jd.year, jd.month, jd.day
        persian_weekday = jd.weekday()
        is_nowruz = persian_month == NOWRUZ_MONTH and persian_day in NOWRUZ_HOLIDAY_DAYS

    return DayContext(
        local_ts=local_ts,
        is_weekend=is_weekend,
        is_nowruz=is_nowruz,
        is_official_holiday=is_weekend or is_nowruz,
        month=local_ts.month,
        season=SEASON_BY_MONTH[local_ts.month],
        persian_year=persian_year,
        persian_month=persian_month,
        persian_day=persian_day,
        persian_weekday=persian_weekday,
    )


def day_class_key(ts: datetime) -> str:
    """A coarse "kind of day" label used for historical-analogue matching
    (spec §13): "weekday"/"weekend"/"holiday" as three *distinct* classes —
    Nowruz traffic looks nothing like an ordinary Friday, so unlike
    `is_official_holiday` (used for the model's single `is_holiday`
    feature), this never merges the two."""
    ctx = classify_day(ts)
    if ctx.is_nowruz:
        return "holiday"
    return "weekend" if ctx.is_weekend else "weekday"


def find_active_events(ts: datetime, events: list[dict]) -> list[dict]:
    """Filters a pre-fetched list of `traffic_events` rows (already JSON,
    with tz-aware `start_at`/`end_at`) down to those active at `ts`. Kept as
    a pure function so callers control the (async) DB fetch."""
    active = []
    for event in events:
        start_at = event.get("start_at")
        end_at = event.get("end_at")
        if start_at and end_at and start_at <= ts <= end_at:
            active.append(event)
    return active
