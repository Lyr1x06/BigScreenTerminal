# -*- coding: utf-8 -*-
"""Weekly schedule calculations and migration from legacy screen-off alarms."""

import datetime as dt
import uuid


ACTIONS = {"blackout", "shutdown"}
ALL_DAYS = list(range(7))


def normalize_rule(value):
    if not isinstance(value, dict):
        return None
    try:
        hour, minute = (int(part) for part in str(value["time"]).split(":"))
        if not 0 <= hour < 24 or not 0 <= minute < 60:
            return None
        action = value.get("action", "blackout")
        if action not in ACTIONS:
            return None
        days = sorted({int(day) for day in value.get("days", ALL_DAYS)
                       if 0 <= int(day) <= 6})
        if not days:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "id": str(value.get("id") or uuid.uuid4().hex),
        "time": f"{hour:02d}:{minute:02d}",
        "days": days,
        "action": action,
        "enabled": bool(value.get("enabled", True)),
    }


def migrate_alarms(alarms):
    rules = []
    for alarm in alarms if isinstance(alarms, list) else []:
        if not isinstance(alarm, dict):
            continue
        rule = normalize_rule({
            "time": alarm.get("time"), "days": ALL_DAYS,
            "action": "blackout",
            # Old one-shot alarms cannot safely become repeating weekly rules.
            "enabled": bool(alarm.get("enabled", True) and alarm.get("repeat", True)),
        })
        if rule:
            rules.append(rule)
    return rules


def next_occurrence(rule, now):
    if not rule["enabled"]:
        return None
    hour, minute = map(int, rule["time"].split(":"))
    for offset in range(8):
        day = now.date() + dt.timedelta(days=offset)
        if day.weekday() not in rule["days"]:
            continue
        candidate = dt.datetime.combine(day, dt.time(hour, minute))
        if candidate > now:
            return candidate
    return None


def due_occurrence(rule, now, last_fired):
    if not rule["enabled"] or now.weekday() not in rule["days"]:
        return None
    hour, minute = map(int, rule["time"].split(":"))
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    elapsed = (now - scheduled).total_seconds()
    key = f"{rule['id']}:{scheduled.date().isoformat()}"
    if 0 <= elapsed < 60 and key not in last_fired:
        return key
    return None
