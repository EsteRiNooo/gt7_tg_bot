"""Build user-meaningful series cards from raw race events."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from services.races_logging import logger
from services.time_utils import (
    format_minutes,
    format_starts_in,
    get_interval_minutes,
    get_next_start,
    get_starts_in_minutes,
)


def _parse_start_time(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, str):
        value = raw.strip()
        if not value:
            return None
        if value.endswith("Z"):
            value = f"{value[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _first_non_empty_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def build_series_from_races(races: list[dict]) -> list[dict]:
    """
    Aggregate raw race events into one card-like entity per (sim, source, series).

    Output schema:
    {
      "sim": str,
      "source": str,
      "series": str,
      "track": str,
      "duration": int | str | None,
      "next_start": datetime,
      "starts_in_minutes": int,
      "interval_minutes": int | None,
      "events_count": int,
      "class": str,
    }
    """
    logger.info(f"[AGG] total races: {len(races)}")

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for race in races:
        if not isinstance(race, dict):
            continue
        sim = _first_non_empty_str(race.get("sim"), "Unknown sim")
        source = _first_non_empty_str(race.get("source"), "unknown")
        series = _first_non_empty_str(
            race.get("series"),
            race.get("series_name"),
            race.get("title"),
            "Unknown series",
        )
        grouped[(sim, source, series)].append(race)

    now = datetime.now(timezone.utc)
    series_list: list[dict[str, Any]] = []

    for (sim, source, series), items in grouped.items():
        parsed_times: list[datetime] = []
        for race in items:
            st = _parse_start_time(race.get("startTime"))
            if st is not None:
                parsed_times.append(st)
        if not parsed_times:
            continue

        start_times = sorted(parsed_times)
        next_start = get_next_start(start_times, now)
        starts_in_minutes = get_starts_in_minutes(now, next_start)
        interval_minutes = get_interval_minutes(start_times)
        logger.debug(
            f"[TIME] next={next_start}, starts_in={starts_in_minutes}, interval={interval_minutes}",
        )

        first = items[0]
        duration_val: Any = first.get("duration")
        if duration_val is None:
            duration_val = first.get("race_length")
        parsed_duration = _as_int(duration_val)
        duration = parsed_duration if parsed_duration is not None else duration_val
        duration_text = format_minutes(parsed_duration) if parsed_duration is not None else ""
        starts_in_text = format_starts_in(starts_in_minutes)
        interval_text = (
            format_minutes(interval_minutes)
            if interval_minutes is not None
            else None
        )
        logger.debug(
            f"[SERIES] {series} starts_in={starts_in_minutes} interval={interval_minutes}",
        )

        track = _first_non_empty_str(first.get("track"))
        race_class = _first_non_empty_str(first.get("class"), "Unknown")
        car = _first_non_empty_str(first.get("car"))

        series_list.append(
            {
                "sim": sim,
                "source": source,
                "series": series,
                "type": first.get("type"),
                "track": track,
                "duration": duration,
                "next_start": next_start,
                "starts_in_minutes": starts_in_minutes,
                "interval_minutes": interval_minutes,
                "starts_in_text": starts_in_text,
                "interval_text": interval_text,
                "duration_text": duration_text,
                "events_count": len(items),
                "class": race_class,
                "car": car or None,
                "requirements": first.get("requirements"),
            },
        )

    logger.info(f"[AGG] total series: {len(series_list)}")
    return series_list


MAX_PER_SIM = 5


def filter_series(series_list: list[dict]) -> list[dict]:
    """Deterministic, explainable filter for 'what can I race this week?'."""
    logger.info(f"[FILTER] before: {len(series_list)}")

    kept: list[dict] = []
    week_minutes = 7 * 24 * 60
    for series in series_list:
        starts_in = series.get("starts_in_minutes")
        interval = series.get("interval_minutes")
        if isinstance(starts_in, int) and starts_in >= 0:
            kept.append(series)
            continue
        if isinstance(interval, int):
            kept.append(series)
            continue
        if isinstance(starts_in, int) and starts_in <= week_minutes:
            kept.append(series)

    kept.sort(key=lambda s: s.get("starts_in_minutes", 10**9))

    by_sim: dict[str, list[dict]] = defaultdict(list)
    for item in kept:
        sim = item.get("sim")
        if not isinstance(sim, str) or not sim.strip():
            sim = "Unknown sim"
        by_sim[sim.strip()].append(item)

    limited: list[dict] = []
    for sim in sorted(by_sim.keys()):
        bucket = by_sim[sim]
        bucket.sort(key=lambda s: s.get("starts_in_minutes", 10**9))
        limited.extend(bucket[:MAX_PER_SIM])

    logger.info(f"[FILTER] after: {len(limited)}")
    return limited
