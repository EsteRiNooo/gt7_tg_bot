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
    "Assetto Corsa EVO": "ACEVO",
    "iRacing": "IRACING",
    "rFactor 2": "RF2",
    "RaceRoom": "RACEROOM",
}

SIM_BLOCK_ORDER: list[str] = [
    "Automobilista 2",
    "Le Mans Ultimate",
    "Assetto Corsa Competizione",
    "Assetto Corsa EVO",
    "iRacing",
    "rFactor 2",
    "RaceRoom",
]


def format_duration(minutes: int) -> str:
    """Human-readable duration from total minutes (days/hours/mins, skip zeros)."""
    if minutes <= 0:
        return "0m"
    days = minutes // 1440
    hours = (minutes % 1440) // 60
    mins = minutes % 60
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    if not parts:
        return "0m"
    return "".join(parts)


def format_interval(delta_minutes: int) -> str:
    """Convert a positive minute delta to short labels (kept for compatibility)."""
    if delta_minutes <= 0:
        return ""
    return format_duration(delta_minutes)


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


def _class_label_from_event(ev: dict[str, Any]) -> str:
    v = ev.get("class")
    if isinstance(v, str) and v.strip():
        return v.strip()
    raw_cc = ev.get("carClasses")
    if isinstance(raw_cc, list) and raw_cc:
        parts: list[str] = []
        for item in raw_cc:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("class") or item.get("name") or item.get("label")
                if isinstance(name, str) and name.strip():
                    parts.append(name.strip())
        if parts:
            return " / ".join(dict.fromkeys(parts))
    cc = ev.get("car_class")
    if isinstance(cc, str) and cc.strip():
        return cc.strip()
    return ""


def _class_label_for_group(rows: list[dict[str, Any]]) -> str:
    labels: list[str] = []
    seen: set[str] = set()
    for ev in rows:
        lab = _class_label_from_event(ev)
        if lab and lab not in seen:
            seen.add(lab)
            labels.append(lab)
    return " / ".join(labels)


def _requirements(ev: dict[str, Any]) -> dict[str, str] | None:
    req = ev.get("requirements")
    if isinstance(req, dict) and req:
        return {str(k): str(v) for k, v in req.items() if v is not None}
    return None


def _lfm_message_tag(sim: str) -> str:
    tag = SIM_HASHTAGS.get(sim.strip())
    if not tag:
        tag = "".join(ch for ch in sim.upper() if ch.isalnum())[:8] or "LFM"
    return f"#{tag}_LFM"


def _ordered_sims(sims: set[str]) -> list[str]:
    remaining = set(sims)
    ordered: list[str] = []
    for name in SIM_BLOCK_ORDER:
        if name in remaining:
            ordered.append(name)
            remaining.discard(name)
    ordered.extend(sorted(remaining))
    return ordered


def build_lfm_simulation_messages(
    flat_events: list[dict[str, Any]],
    *,
    reference_utc: datetime | None = None,
) -> list[str]:
    """
    One Telegram message text per simulation (AMS2_LFM, LMU_LFM, ...), each with up to
    5 series cards sorted by next start.
    """
    if not flat_events:
        return []

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
        seconds_until = int((next_start - now).total_seconds())
        starts_in = format_duration(int((seconds_until + 59) // 60))
        interval_label = format_duration(interval_minutes) if interval_minutes is not None else ""

        track = ""
        if isinstance(sample.get("track"), str) and sample["track"].strip():
            track = sample["track"].strip()

        race_class = _class_label_for_group(rows)
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

    messages: list[str] = []
    for sim in _ordered_sims(set(sim_cards.keys())):
        cards = sim_cards.get(sim, [])
        if not cards:
            continue
        cards.sort(key=lambda c: c["_sort_key"])
        cards = cards[:5]

        lines: list[str] = [
            _lfm_message_tag(sim),
            f"{sim} | {LFM_SOURCE_LINE}",
            "",
        ]

        for index, card in enumerate(cards):
            title = (card.get("title") or "Series").strip()
            track = (card.get("track") or "Unknown track").strip()
            race_class = (card.get("class") or "").strip() or "Unknown class"
            duration = (card.get("duration") or "0").strip()

            lines.append(title)
            lines.append(f"📍 {track}")
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

        messages.append("\n".join(lines).rstrip())

    return messages


def format_lfm_series_weekly(
    flat_events: list[dict[str, Any]],
    *,
    reference_utc: datetime | None = None,
) -> str:
    """Backward-compatible: join all simulation blocks (prefer ``build_lfm_simulation_messages``)."""
    return "\n\n".join(
        build_lfm_simulation_messages(flat_events, reference_utc=reference_utc)
    ).rstrip()
