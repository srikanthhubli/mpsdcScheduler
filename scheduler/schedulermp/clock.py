"""Daily clock for legacy migration.

Times are interpreted in the schedule timezone, default Asia/Kolkata.
A legacy window starts once per day and may keep running only until it ends.
"""

from __future__ import annotations

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

OPEN_LEGACY = {"PENDING", "RUNNING", "FAILED", "STOPPED", "NOT_STARTED", "IN_PROGRESS"}


def default_schedule() -> dict:
    return {
        "timezone": "Asia/Kolkata",
        "legacy": {
            "enabled": False,
            "start": "01:00",
            "hours": 4,
            "stopWhenComplete": True,
            "lastWindow": "",
            "automatic": False,
            "message": "Off. Choose a start time and how many hours it may run each day.",
        },
    }


def parse_clock(value: str) -> time:
    text = str(value or "").strip()
    hour_text, minute_text = text.split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if hour > 23 or minute > 59 or hour < 0 or minute < 0:
        raise ValueError("time must be HH:MM")
    return time(hour, minute)


def clock_text(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def normalize_schedule(raw: dict | None) -> dict:
    base = default_schedule()
    incoming = raw or {}
    base["timezone"] = str(incoming.get("timezone") or base["timezone"])
    ZoneInfo(base["timezone"])
    for name in ("legacy",):
        patch = incoming.get(name) or {}
        if "enabled" in patch:
            base[name]["enabled"] = bool(patch["enabled"])
        if "start" in patch and patch["start"]:
            base[name]["start"] = clock_text(parse_clock(patch["start"]))
        if "message" in patch:
            base[name]["message"] = str(patch["message"])
    legacy = incoming.get("legacy") or {}
    if "hours" in legacy and legacy["hours"] not in ("", None):
        hours = int(legacy["hours"])
        if hours < 1 or hours > 12:
            raise ValueError("legacy hours must be from 1 to 12")
        base["legacy"]["hours"] = hours
    if "stopWhenComplete" in legacy:
        base["legacy"]["stopWhenComplete"] = bool(legacy["stopWhenComplete"])
    if "lastWindow" in legacy:
        base["legacy"]["lastWindow"] = str(legacy["lastWindow"] or "")
    if "automatic" in legacy:
        base["legacy"]["automatic"] = bool(legacy["automatic"])
    return base


def active_window(now: datetime, start: str, hours: int):
    clock = parse_clock(start)
    span = timedelta(hours=max(1, min(int(hours), 12)))
    for days_back in (0, 1):
        day = now.date() - timedelta(days=days_back)
        begin = datetime.combine(day, clock, tzinfo=now.tzinfo)
        end = begin + span
        if begin <= now < end:
            return begin, end
    return None


def legacy_finished(items: list[dict]) -> bool:
    if not items:
        return False
    return all(item.get("status") in {"SUCCESS", "SKIPPED"} for item in items)


def legacy_open_count(items: list[dict]) -> int:
    return sum(1 for item in items if item.get("status") in OPEN_LEGACY)
