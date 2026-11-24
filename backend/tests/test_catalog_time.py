from datetime import datetime, timezone

from app.catalog import MEXICO_CITY, get_demo_slots


def test_catalog_uses_mexico_city_calendar_and_serializes_utc():
    # UTC is already on the 25th while Mexico City is still on the 24th.
    now = datetime(2026, 11, 25, 2, tzinfo=timezone.utc)
    slots = [slot for slot in get_demo_slots(now) if slot["clinic_id"] == "CL-001"]
    assert slots[0]["id"] == "SL-CL-001-20261125-09"
    assert slots[0]["starts_at"] == "2026-11-25T15:00:00Z"
    assert slots[-1]["starts_at"] == "2026-11-27T19:00:00Z"
    local = [datetime.fromisoformat(slot["starts_at"]).astimezone(MEXICO_CITY) for slot in slots]
    assert [slot.hour for slot in local] == list(range(9, 14)) * 3
    assert sorted({slot.day for slot in local}) == [25, 26, 27]
