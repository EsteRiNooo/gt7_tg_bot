"""Expand LFM minified season JSON into concrete race events for the current calendar week."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any

from services.races_logging import ensure_races_logging_configured, logger

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc, assignment]

BERLIN_TZ_NAME = "Europe/Berlin"


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _parse_lfm_datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = f"{s[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _week_bounds_berlin(day_in_week: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """Monday 00:00 (inclusive) through the following Monday 00:00 (exclusive), Europe/Berlin."""
    monday = day_in_week - timedelta(days=day_in_week.weekday())
    start = datetime.combine(monday, time.min, tzinfo=tz)
    end = start + timedelta(days=7)
    return start, end


def _dates_in_week(week_start: date) -> list[date]:
    return [week_start + timedelta(days=i) for i in range(7)]


def _iter_daily_starts(
    day: date,
    earliest_h: int,
    latest_h: int,
    every_minutes: int,
    tz: tzinfo,
) -> list[datetime]:
    if every_minutes <= 0:
        return []
    if earliest_h < 0 or earliest_h > 23 or latest_h < 0 or latest_h > 23:
        return []
    if earliest_h > latest_h:
        return []

    day_start = datetime.combine(day, time.min, tzinfo=tz)
    first = day_start.replace(hour=earliest_h, minute=0, second=0, microsecond=0)
    last = day_start.replace(hour=latest_h, minute=59, second=59, microsecond=999999)

    out: list[datetime] = []
    t = first
    while t <= last:
        out.append(t)
        t += timedelta(minutes=every_minutes)
    return out


def _track_name(series: dict[str, Any]) -> str:
    at = series.get("active_track")
    if isinstance(at, dict):
        name = at.get("track_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return ""


def _series_title(series: dict[str, Any]) -> str:
    for key in ("series_name", "short_name", "name"):
        v = series.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _weekly_race_times(series: dict[str, Any]) -> list[datetime]:
    times: list[datetime] = []
    seen: set[tuple[int, int, int, int, int, int, int]] = set()

    for raw in (series.get("next_race"),):
        dt = _parse_lfm_datetime(raw)
        if dt is not None:
            k = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond)
            if k not in seen:
                seen.add(k)
                times.append(dt)

    n3 = series.get("next3_races")
    if isinstance(n3, list):
        for item in n3:
            dt = _parse_lfm_datetime(item)
            if dt is None:
                continue
            k = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond)
            if k not in seen:
                seen.add(k)
                times.append(dt)

    return times


def flatten_lfm_week_events(
    payload: dict[str, Any],
    *,
    reference_utc: datetime | None = None,
    timezone_name: str | None = None,
) -> list[dict[str, Any]]:
    """
    Build a flat list of race dicts for the ISO week (Mon–Sun, Europe/Berlin) that contains
    ``reference_utc`` (defaults to now, UTC-aware).
    """
    ensure_races_logging_configured()

    tz_name = timezone_name or BERLIN_TZ_NAME
    if ZoneInfo is None:
        raise RuntimeError("zoneinfo is required (Python 3.9+)")
    tz = ZoneInfo(tz_name)

    ref = reference_utc or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    ref_local = ref.astimezone(tz)
    week_start, week_end = _week_bounds_berlin(ref_local.date(), tz)
    week_dates = _dates_in_week(week_start.date())

    events: list[dict[str, Any]] = []

    series_root = payload.get("series")
    if not isinstance(series_root, dict):
        logger.info("[LFM] sims: 0")
        logger.info("[LFM] total series: 0")
        logger.info("[LFM] generated races before week filter: 0")
        logger.info("[LFM] generated races after week filter: 0")
        return events

    sims_count = len(series_root)
    series_total = 0
    for _sim_block in series_root.values():
        if isinstance(_sim_block, dict):
            _sl = _sim_block.get("series")
            if isinstance(_sl, list):
                series_total += len(_sl)

    generated_before = 0

    for sim_block in series_root.values():
        if not isinstance(sim_block, dict):
            continue
        sim_name = sim_block.get("simulation")
        sim = sim_name.strip() if isinstance(sim_name, str) else ""
        series_list = sim_block.get("series")
        if not isinstance(series_list, list):
            continue

        for series in series_list:
            if not isinstance(series, dict):
                continue
            style = series.get("event_style")
            if style not in ("daily", "weekly"):
                continue

            title = _series_title(series)
            track = _track_name(series)
            duration = _as_int(series.get("race_length"))
            if duration is None:
                duration = 0

            if style == "daily":
                settings = series.get("settings")
                ses: dict[str, Any] = {}
                if isinstance(settings, dict):
                    raw_ses = settings.get("season_event_settings")
                    if isinstance(raw_ses, dict):
                        ses = raw_ses

                earliest = _as_int(ses.get("ingame_earliest_racehour"))
                latest = _as_int(ses.get("ingame_latest_racehour"))
                every = _as_int(ses.get("races_every"))
                if earliest is None or latest is None or every is None:
                    continue

                for d in week_dates:
                    for start in _iter_daily_starts(d, earliest, latest, every, tz):
                        generated_before += 1
                        if not (week_start <= start < week_end):
                            continue
                        events.append(
                            {
                                "sim": sim,
                                "series": title,
                                "track": track,
                                "startTime": start.isoformat(),
                                "duration": duration,
                                "type": "daily",
                            }
                        )

            else:  # weekly
                for start in _weekly_race_times(series):
                    generated_before += 1
                    local_start = start.astimezone(tz)
                    if not (week_start <= local_start < week_end):
                        continue
                    events.append(
                        {
                            "sim": sim,
                            "series": title,
                            "track": track,
                            "startTime": local_start.isoformat(),
                            "duration": duration,
                            "type": "weekly",
                        }
                    )

    events.sort(key=lambda e: (e.get("startTime") or "", e.get("sim") or "", e.get("series") or ""))
    logger.info(f"[LFM] sims: {sims_count}")
    logger.info(f"[LFM] total series: {series_total}")
    logger.info(f"[LFM] generated races before week filter: {generated_before}")
    logger.info(f"[LFM] generated races after week filter: {len(events)}")
    return events
