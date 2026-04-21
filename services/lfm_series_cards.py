"""Aggregate flat LFM week events into series-level cards for display."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from services.formatting import format_requirements_lines

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc, assignment]

BERLIN_TZ_NAME = "Europe/Berlin"
LFM_SOURCE_LINE = "lowfuelmotorsport"

SIM_HASHTAGS: dict[str, str] = {
    "Automobilista 2": "AMS2",
    "Le Mans Ultimate": "LMU",
    "Assetto Corsa Competizione": "ACC",
    "iRacing": "IRACING",
    "rFactor 2": "RF2",
    "RaceRoom": "RACEROOM",
}

SIM_BLOCK_ORDER: list[str] = [
    "Automobilista 2",
    "Le Mans Ultimate",
    "Assetto Corsa Competizione",
    "iRacing",
    "rFactor 2",
    "RaceRoom",
]


def format_interval(delta_minutes: int) -> str:
    """Convert minutes to labels like ``1h`` or ``90m`` (empty if invalid)."""
    if delta_minutes <= 0:
        return ""
    if delta_minutes % 60 == 0:
        return f"{delta_minutes // 60}h"
    return f"{delta_minutes}m"


def compute_interval(future_starts: list[datetime]) -> int | None:
    """Difference in whole minutes between the first two future starts, if any."""
    if len(future_starts) < 2:
        return None
    delta_seconds = (future_starts[1] - future_starts[0]).total_seconds()
    minutes = int(delta_seconds // 60)
    if minutes <= 0:
        return None
    return minutes


def _berlin_tz() -> Any:
    if ZoneInfo is None:
        raise RuntimeError("zoneinfo is required (Python 3.9+)")
    return ZoneInfo(BERLIN_TZ_NAME)


def _week_bounds_berlin(day_in_week: date, tz: Any) -> tuple[datetime, datetime]:
    monday = day_in_week - timedelta(days=day_in_week.weekday())
    start = datetime.combine(monday, time.min, tzinfo=tz)
    end = start + timedelta(days=7)
    return start, end


def _parse_start_time(raw: Any) -> datetime | None:
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


def group_races_by_series(
    events: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Group flat LFM events by ``(simulation, series_name)``."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        if not isinstance(ev, dict):
            continue
        sim = ev.get("sim")
        series = ev.get("series")
        if not isinstance(sim, str) or not sim.strip():
            continue
        if not isinstance(series, str) or not series.strip():
            continue
        groups[(sim.strip(), series.strip())].append(ev)
    return groups


def _duration_display(ev: dict[str, Any]) -> str:
    d = ev.get("duration")
    if isinstance(d, int):
        return str(d)
    if isinstance(d, str) and d.strip():
        return d.strip()
    return "0"


def _class_display(ev: dict[str, Any]) -> str:
    for key in ("class", "car_class", "race_class"):
        v = ev.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _requirements(ev: dict[str, Any]) -> dict[str, str] | None:
    req = ev.get("requirements")
    if isinstance(req, dict) and req:
        return {str(k): str(v) for k, v in req.items() if v is not None}
    return None


def _starts_in_label(seconds_until: int) -> str:
    if seconds_until <= 0:
        return "0m"
    minutes = int((seconds_until + 59) // 60)
    label = format_interval(minutes)
    return label if label else f"{minutes}m"


def _sim_hashtag(sim: str) -> str:
    tag = SIM_HASHTAGS.get(sim.strip())
    if tag:
        return f"#{tag}"
    compact = "".join(ch for ch in sim.upper() if ch.isalnum())[:8]
    return f"#{compact or 'LFM'}"


def _ordered_sims(sims: set[str]) -> list[str]:
    remaining = set(sims)
    ordered: list[str] = []
    for name in SIM_BLOCK_ORDER:
        if name in remaining:
            ordered.append(name)
            remaining.discard(name)
    ordered.extend(sorted(remaining))
    return ordered


def format_lfm_series_weekly(
    flat_events: list[dict[str, Any]],
    *,
    reference_utc: datetime | None = None,
) -> str:
    """
    Build human-readable LFM text: one block per simulation, up to 5 series each,
    sorted by nearest upcoming start. Uses only fields present on flat parser output.
    """
    if not flat_events:
        return ""

    tz = _berlin_tz()
    ref = reference_utc or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    now = ref.astimezone(tz)
    week_start, week_end = _week_bounds_berlin(now.date(), tz)
    horizon_end = now + timedelta(days=7)

    groups = group_races_by_series(flat_events)
    sim_cards: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for (sim, series_name), rows in groups.items():
        parsed: list[tuple[datetime, dict[str, Any]]] = []
        for ev in rows:
            st = _parse_start_time(ev.get("startTime"))
            if st is None:
                continue
            parsed.append((st, ev))
        if not parsed:
            continue

        parsed.sort(key=lambda x: x[0])
        starts_only = [t for t, _ in parsed]
        future_starts = [t for t in starts_only if t >= now]
        if not future_starts:
            continue

        next_start = future_starts[0]
        if next_start > horizon_end:
            continue

        sample = parsed[0][1]
        race_type = (sample.get("type") or "").strip().lower()
        if race_type == "weekly":
            local_next = next_start.astimezone(tz)
            if not (week_start <= local_next < week_end):
                continue
        elif race_type != "daily":
            continue

        interval_minutes = compute_interval(future_starts)
        interval_label = format_interval(interval_minutes) if interval_minutes is not None else ""

        seconds_until = int((next_start - now).total_seconds())
        starts_in = _starts_in_label(seconds_until)

        track = ""
        if isinstance(sample.get("track"), str) and sample["track"].strip():
            track = sample["track"].strip()

        race_class = _class_display(sample)
        duration_str = _duration_display(sample)
        requirements = _requirements(sample)

        card = {
            "title": series_name,
            "track": track,
            "class": race_class,
            "duration": duration_str,
            "next_start_in": starts_in,
            "interval": interval_label or None,
            "requirements": requirements,
            "_sort_key": next_start,
        }
        sim_cards[sim].append(card)

    if not sim_cards:
        return ""

    lines: list[str] = []
    for sim in _ordered_sims(set(sim_cards.keys())):
        cards = sim_cards.get(sim, [])
        if not cards:
            continue
        cards.sort(key=lambda c: c["_sort_key"])
        cards = cards[:5]

        lines.append(_sim_hashtag(sim))
        lines.append(f"{sim} | {LFM_SOURCE_LINE}")
        lines.append("")

        for index, card in enumerate(cards):
            title = (card.get("title") or "Series").strip()
            track = (card.get("track") or "Unknown track").strip()
            race_class = (card.get("class") or "").strip()
            duration = (card.get("duration") or "0").strip()

            lines.append(title)
            lines.append(f"📍 {track}")
            if race_class:
                lines.append(f"🏁 {race_class}")
            lines.append(f"⏱ {duration} min")
            lines.append(f"⏳ Starts in {card.get('next_start_in') or '0m'}")
            if card.get("interval"):
                lines.append(f"🔁 Every {card['interval']}")

            req_lines = format_requirements_lines(
                {"requirements": card.get("requirements")},
                html=False,
            )
            if req_lines:
                lines.extend(req_lines)

            if index < len(cards) - 1:
                lines.extend(["", "──────────", ""])

        lines.extend(["", ""])

    return "\n".join(lines).rstrip()
