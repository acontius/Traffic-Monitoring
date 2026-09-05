"""Timezone handling, Persian-calendar conversion, and holiday flags
(Backend/app/ml/calendar.py)."""

from datetime import datetime, timezone

from Backend.app.ml.calendar import classify_day, day_class_key, find_active_events


def test_naive_timestamp_is_treated_as_utc():
    ctx = classify_day(datetime(2026, 3, 21, 6, 0))  # naive
    assert ctx.local_ts.tzinfo is not None


def test_local_conversion_shifts_to_traffic_timezone():
    # 2026-03-21 06:00 UTC -> Asia/Tehran (UTC+3:30) is 09:30 local.
    ts = datetime(2026, 3, 21, 6, 0, tzinfo=timezone.utc)
    ctx = classify_day(ts)
    assert ctx.local_ts.hour == 9
    assert ctx.local_ts.minute == 30


def test_friday_is_weekend_in_iran():
    # 2026-03-20 is a Friday.
    ts = datetime(2026, 3, 20, 6, 0, tzinfo=timezone.utc)
    ctx = classify_day(ts)
    assert ctx.is_weekend is True


def test_persian_calendar_conversion_nowruz():
    # 2026-03-21 is 1 Farvardin 1405 (Nowruz).
    ts = datetime(2026, 3, 21, 6, 0, tzinfo=timezone.utc)
    ctx = classify_day(ts)
    assert ctx.persian_month == 1
    assert ctx.persian_day in (1, 2)  # timezone shift may land on day 1 or 2
    assert ctx.is_official_holiday is True


def test_day_class_key_distinguishes_weekday_weekend_holiday():
    weekday_ts = datetime(2026, 3, 18, 6, 0, tzinfo=timezone.utc)  # Wednesday
    assert day_class_key(weekday_ts) == "weekday"

    # An ordinary Friday (not Nowruz) is its own "weekend" class, distinct
    # from "holiday" — a plain Friday's traffic looks nothing like Nowruz's.
    friday_ts = datetime(2026, 3, 20, 6, 0, tzinfo=timezone.utc)
    assert day_class_key(friday_ts) == "weekend"

    nowruz_ts = datetime(2026, 3, 21, 6, 0, tzinfo=timezone.utc)
    assert day_class_key(nowruz_ts) == "holiday"


def test_find_active_events_filters_by_window():
    ts = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    events = [
        {
            "name": "in-window",
            "start_at": datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
            "end_at": datetime(2026, 5, 2, 0, 0, tzinfo=timezone.utc),
        },
        {
            "name": "out-of-window",
            "start_at": datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
            "end_at": datetime(2026, 6, 2, 0, 0, tzinfo=timezone.utc),
        },
    ]
    active = find_active_events(ts, events)
    assert [e["name"] for e in active] == ["in-window"]
