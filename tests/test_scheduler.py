"""Slot scheduler: timezones, DST gaps/overlaps, taken slots and lead time."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from clipstudio.publish import next_free_slots, parse_slots, resolve_local

NY = "America/New_York"
UTC = timezone.utc


def test_parse_slots():
    assert parse_slots("11:00, 15:00 19:00,22:00, 25:00, junk") == [time(11), time(15), time(19), time(22)]


def test_winter_and_summer_offsets():
    now = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)            # 07:00 in New York (EST, UTC-5)
    out = next_free_slots([time(11), time(15)], NY, [], 2, now=now)
    assert out == [datetime(2026, 1, 10, 16, 0, tzinfo=UTC), datetime(2026, 1, 10, 20, 0, tzinfo=UTC)]
    now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)            # EDT, UTC-4
    assert next_free_slots([time(11)], NY, [], 1, now=now) == [datetime(2026, 7, 10, 15, 0, tzinfo=UTC)]


def test_skips_past_and_too_soon_slots():
    now = datetime(2026, 1, 10, 15, 50, tzinfo=UTC)           # 10:50 NY — 11:00 is within the 20 min lead
    out = next_free_slots([time(11), time(15)], NY, [], 2, now=now)
    assert out[0] == datetime(2026, 1, 10, 20, 0, tzinfo=UTC)
    assert out[1] == datetime(2026, 1, 11, 16, 0, tzinfo=UTC)


def test_skips_taken_slots():
    now = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    taken = [datetime(2026, 1, 10, 16, 0, tzinfo=UTC)]
    out = next_free_slots([time(11), time(15)], NY, taken, 2, now=now)
    assert datetime(2026, 1, 10, 16, 0, tzinfo=UTC) not in out
    assert out == [datetime(2026, 1, 10, 20, 0, tzinfo=UTC), datetime(2026, 1, 11, 16, 0, tzinfo=UTC)]


def test_spring_forward_gap_moves_to_real_time():
    # 2026-03-08: clocks jump 02:00 → 03:00 in New York; 02:30 doesn't exist.
    utc = resolve_local(datetime(2026, 3, 8).date(), time(2, 30), ZoneInfo(NY))
    assert utc == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)     # = 03:30 EDT
    assert utc.astimezone(ZoneInfo(NY)).strftime("%H:%M") == "03:30"


def test_spring_forward_no_duplicate_with_existing_slot():
    now = datetime(2026, 3, 8, 5, 0, tzinfo=UTC)
    out = next_free_slots([time(2, 30), time(3, 30)], NY, [], 3, now=now)
    assert len(set(out)) == 3                                 # 02:30→03:30 collides with 03:30: one is skipped
    assert out[0] == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    assert out[1].date() == datetime(2026, 3, 9).date()


def test_fall_back_overlap_uses_first_occurrence():
    # 2026-11-01: 01:30 happens twice in New York; we use the first (EDT, UTC-4).
    utc = resolve_local(datetime(2026, 11, 1).date(), time(1, 30), ZoneInfo(NY))
    assert utc == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)


def test_day_after_dst_change_uses_new_offset():
    now = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
    out = next_free_slots([time(11)], NY, [], 2, now=now)
    assert out == [datetime(2026, 11, 1, 16, 0, tzinfo=UTC), datetime(2026, 11, 2, 16, 0, tzinfo=UTC)]


def test_other_timezones():
    now = datetime(2026, 3, 29, 0, 30, tzinfo=UTC)            # Europe/London springs forward at 01:00 UTC
    out = next_free_slots([time(1, 30), time(19)], "Europe/London", [], 2, now=now)
    assert out[0] == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)  # 01:30 GMT doesn't exist → 02:30 BST = 01:30 UTC
    assert out[1] == datetime(2026, 3, 29, 18, 0, tzinfo=UTC)
    assert all(b - a > timedelta(0) for a, b in zip(out, out[1:]))
