"""Aggregate flat LFM week events into series-level cards for display."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from services.aggregation.series_builder import build_series_from_races, filter_series
from services.races_logging import logger

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


def _rank_line(race: dict[str, Any]) -> str | None:
    requirements = race.get("requirements")
    if not isinstance(requirements, dict):
        return None
    for key in ("license", "rank", "safety"):
        value = requirements.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        # Hide noisy numeric-only values (e.g. 4, 3.5)
        if all(ch.isdigit() or ch == "." for ch in text):
            continue
        return f"🏆 {text}"
    return None


def render_daily_race(race: dict[str, Any]) -> list[str]:
    title = (race.get("title") or "Series").strip()
    track = (race.get("track") or "Unknown track").strip()
    race_class = (race.get("class") or "").strip() or "Unknown class"
    car = (race.get("car") or "").strip()
    duration = (race.get("duration") or "0").strip()
    lines = [
        title,
        f"📍 {track}",
        f"🏁 {race_class}",
    ]
    if race_class.lower() == "fixed" and car:
        lines.append(f"🚗 {car}")
    lines.append(f"⏱ {duration} min")
    return lines


def render_weekly_race(race: dict[str, Any]) -> list[str]:
    lines = render_daily_race(race)
    lines.append(f"🕐 Starts in {race.get('next_start_in') or '0m'}")
    rank = _rank_line(race)
    if rank:
        lines.append(rank)
    return lines


def build_lfm_simulation_messages(
    flat_events: list[dict[str, Any]],
    *,
    reference_utc: datetime | None = None,
) -> list[str]:
    """
    One Telegram message text per simulation (AMS2_LFM, LMU_LFM, ...), each with up to
    one card per series, sorted by next start.
    """
    if not flat_events:
        return []

    ref = reference_utc or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)

    series_list = build_series_from_races(flat_events)
    filtered_series = filter_series(series_list)

    sim_cards: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_input_sims = {
        str(ev.get("sim")).strip()
        for ev in flat_events
        if isinstance(ev, dict)
        and isinstance(ev.get("sim"), str)
        and str(ev.get("sim")).strip()
    }

    for item in filtered_series:
        sim = str(item.get("sim") or "").strip()
        if not sim:
            continue
        title = str(item.get("series") or "Series").strip() or "Series"
        track = str(item.get("track") or "").strip()
        race_class = str(item.get("class") or "").strip()
        race_car = str(item.get("car") or "").strip()
        duration_text = str(item.get("duration_text") or "").strip()
        if not duration_text:
            raw_duration = item.get("duration")
            duration_text = str(raw_duration).strip() if raw_duration is not None else "0"
        starts_in_text = str(item.get("starts_in_text") or "").strip() or "0m"
        interval_text = item.get("interval_text")
        interval_label = str(interval_text).strip() if interval_text is not None else None
        requirements = _requirements(item)
        sort_key = item.get("next_start")
        if not isinstance(sort_key, datetime):
            sort_key = ref
        race_type = str(item.get("type") or "").strip().lower()
        if race_type not in {"daily", "weekly"}:
            race_type = "daily"

        sim_cards[sim].append(
            {
                "title": title,
                "track": track,
                "class": race_class,
                "car": race_car,
                "type": race_type,
                "duration": duration_text,
                "next_start_in": starts_in_text,
                "interval": interval_label or None,
                "requirements": requirements,
                "_sort_key": sort_key,
            },
        )

    messages: list[str] = []
    for sim in _ordered_sims(all_input_sims):
        cards = sim_cards.get(sim, [])
        if not cards:
            print(f"[LFM WARNING] sim {sim} has 0 races after filtering")
            logger.warning(f"[LFM] sim {sim} has 0 races after filtering")
            continue
        cards.sort(
            key=lambda c: (
                0 if c.get("type") == "weekly" else 1,
                c.get("_sort_key") if c.get("type") == "weekly" else datetime.max.replace(tzinfo=timezone.utc),
                (c.get("title") or "").strip().lower(),
            ),
        )

        lines: list[str] = [
            _lfm_message_tag(sim),
            f"{sim} | {LFM_SOURCE_LINE}",
            "",
        ]

        for index, card in enumerate(cards):
            race_type = str(card.get("type") or "").strip().lower()
            if race_type == "weekly":
                lines.extend(render_weekly_race(card))
            else:
                lines.extend(render_daily_race(card))

            if index < len(cards) - 1:
                lines.extend(["", "──────────", ""])

        messages.append("\n".join(lines).rstrip())

    logger.info(f"[LFM] final sims to send: {list(sim_cards.keys())}")
    logger.info(f"[LFM] total messages: {len(messages)}")

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
