"""Build user-meaningful series cards from raw race events."""

from __future__ import annotations

from collections import Counter, defaultdict
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


def _most_common_duration(items: list[dict[str, Any]]) -> int | str | None:
    durations: list[int] = []
    raw_fallback: Any = None
    for race in items:
        value = race.get("duration")
        if value is None:
            value = race.get("race_length")
        if raw_fallback is None and value is not None:
            raw_fallback = value
        parsed = _as_int(value)
        if parsed is not None:
            durations.append(parsed)
    if durations:
        return Counter(durations).most_common(1)[0][0]
    return raw_fallback


def _stable_interval_minutes(start_times: list[datetime]) -> int | None:
    if len(start_times) < 2:
        return None
    deltas = [
        int((start_times[i + 1] - start_times[i]).total_seconds() // 60)
        for i in range(len(start_times) - 1)
    ]
    if not deltas or deltas[0] <= 0:
        return None
    # Irregular schedules should not expose an "Every X" interval.
    if any(delta != deltas[0] for delta in deltas[1:]):
        return None
    return deltas[0]


def build_aggregated_series(races: list[dict]) -> list[dict]:
    """
    Aggregate raw race events into one card-like entity per grouped series session.

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

    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
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
        track = _first_non_empty_str(race.get("track"))
        race_class = _first_non_empty_str(race.get("class"), "Unknown")
        car = _first_non_empty_str(race.get("car"))
        grouped[(sim, source, series, track, race_class, car)].append(race)

    now = datetime.now(timezone.utc)
    series_list: list[dict[str, Any]] = []

    for (sim, source, series, track, race_class, car), items in grouped.items():
        first = items[0] if items else {}
        if not first:
            logger.warning("[series_builder] empty events list")
        parsed_group: list[tuple[datetime, dict[str, Any]]] = []
        for race in items:
            st = _parse_start_time(race.get("startTime"))
            if st is not None:
                parsed_group.append((st, race))
        if not parsed_group:
            continue

        parsed_group.sort(key=lambda item: item[0])
        start_times = [st for st, _ in parsed_group]
        future_group = [(st, race) for st, race in parsed_group if st >= now]
        next_start, next_race = future_group[0] if future_group else parsed_group[0]
        starts_in_minutes = get_starts_in_minutes(now, next_start)
        interval_minutes = _stable_interval_minutes(start_times)
        logger.debug(
            f"[TIME] next={next_start}, starts_in={starts_in_minutes}, interval={interval_minutes}",
        )

        duration = _most_common_duration(items)
        parsed_duration = _as_int(duration)
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
        race_type = _first_non_empty_str(next_race.get("type"), first.get("type"), "daily")
        requirements = first.get("requirements") if isinstance(first, dict) else None

        series_list.append(
            {
                "sim": sim,
                "source": source,
                "series": series,
                "type": race_type,
                "track": track,
                "duration": duration,
                "next_start": next_start,
                "starts_in_minutes": starts_in_minutes,
                "interval_minutes": interval_minutes,
                "interval_min": interval_minutes,
                "starts_in_text": starts_in_text,
                "interval_text": interval_text,
                "duration_text": duration_text,
                "events_count": len(items),
                "class": race_class,
                "car": car or None,
                "requirements": requirements,
            },
        )

    logger.info(f"[AGG] total series: {len(series_list)}")
    return series_list


def build_series_from_races(races: list[dict]) -> list[dict]:
    """Backward-compatible alias."""
    return build_aggregated_series(races)


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
