"""Plain-text formatting for GT7 / LMU Official weekly blocks (used by bot and scheduler)."""

from __future__ import annotations

from typing import Any

from services.formatting import get_week_range

LMU_MAX_CARDS = 10


def ordered_gt7_races(races: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    race_order = {"Race A": 0, "Race B": 1, "Race C": 2}
    return sorted(races, key=lambda race: race_order.get((race.get("title") or "").strip(), 99))


def _parse_starts_in_minutes(value: str | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"now", "0m"}:
        return 0

    total = 0
    number = ""
    had_unit = False
    for ch in text:
        if ch.isdigit():
            number += ch
            continue
        if ch in {"d", "h", "m"} and number:
            amount = int(number)
            if ch == "d":
                total += amount * 1440
            elif ch == "h":
                total += amount * 60
            else:
                total += amount
            had_unit = True
            number = ""
    if had_unit:
        return total
    if text.isdigit():
        return int(text)
    return None


def _group_icon(minutes: int | None) -> str:
    if minutes is not None and minutes <= 15:
        return "🔥"
    if minutes is not None and minutes <= 120:
        return "⚡"
    return "📅"


def map_lmu_sr(sr: str) -> str | None:
    """LMU-only: tier label from Safety Rank multiplier (safetyRank)."""
    if not sr:
        return None
    s = sr.strip()
    if s.startswith("1.0"):
        return "Bronze"
    if s.startswith("1.3"):
        return "Silver"
    if s.startswith("1.5") or s.startswith("2.0"):
        return "Gold"
    return None


def _lmu_safety_rank_for_display(race: dict[str, object]) -> str | None:
    for key in ("safety_rank", "safetyRank"):
        raw = race.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return None


def get_sr_emoji(tier: str) -> str:
    if tier == "Bronze":
        return "🟢"
    if tier == "Silver":
        return "🟡"
    if tier == "Gold":
        return "🟠"
    return "⚪"


def _format_lmu_tier(tier: str, sr: str | None = None) -> str:
    clean_tier = tier.strip()
    display_tier = clean_tier.title()
    sr_text = (sr or "").strip()
    if sr_text and not sr_text.lower().startswith("sr"):
        sr_text = f"SR {sr_text}"
    suffix = f" ({sr_text})" if sr_text else ""

    emoji = get_sr_emoji(display_tier)
    return f"{emoji} {display_tier}{suffix}"


def _extract_lmu_tier_line(race: dict[str, object]) -> str | None:
    sr = _lmu_safety_rank_for_display(race)
    if not sr:
        return None

    tier = map_lmu_sr(sr)
    if tier:
        return _format_lmu_tier(tier, sr)
    return f"SR {sr}"


def _group_and_sort_cards(cards: list[dict[str, object]]) -> list[dict[str, object]]:
    now_cards: list[dict[str, object]] = []
    soon_cards: list[dict[str, object]] = []
    later_cards: list[dict[str, object]] = []
    for card in cards:
        starts = card.get("starts_in_minutes")
        starts_minutes = starts if isinstance(starts, int) else None
        if starts_minutes is not None and starts_minutes <= 15:
            now_cards.append(card)
        elif starts_minutes is not None and starts_minutes <= 120:
            soon_cards.append(card)
        else:
            later_cards.append(card)

    def _sort_key(card: dict[str, object]) -> tuple[int, str]:
        starts = card.get("starts_in_minutes")
        starts_minutes = starts if isinstance(starts, int) else 10**9
        title = str(card.get("title") or "").strip().lower()
        return (starts_minutes, title)

    now_cards.sort(key=_sort_key)
    soon_cards.sort(key=_sort_key)
    later_cards.sort(key=_sort_key)
    return now_cards + soon_cards + later_cards


def _gt7_duration(race: dict[str, str | None]) -> str:
    laps = race.get("laps")
    if isinstance(laps, int) and laps > 0:
        return f"{laps}L"
    if isinstance(laps, str) and laps.strip().isdigit() and int(laps.strip()) > 0:
        return f"{int(laps.strip())}L"
    return ""


def format_gt7_week_message(races: list[dict[str, str | None]]) -> str:
    cards: list[dict[str, object]] = []
    for race in ordered_gt7_races(races):
        title = (race.get("title") or "Race").strip()
        track = (race.get("track") or "Unknown track").strip()
        class_name = (race.get("class") or "Unknown class").strip()
        duration = _gt7_duration(race)
        car = (race.get("car") or "").strip()
        tires = (race.get("tires") or "").strip()
        parts = [f"🏁 {class_name}"]
        if duration:
            parts.append(duration)
        lines = [
            f"{_group_icon(None)} {title}",
            f"📍 {track}",
            " • ".join(parts),
        ]
        if car and car != class_name:
            lines.append(f"🚗 {car}")
        if tires:
            lines.append(f"🛞 {tires}")
        cards.append({"title": title, "starts_in_minutes": None, "lines": lines})

    cards = _group_and_sort_cards(cards)
    details: list[str] = []
    for index, card in enumerate(cards):
        details.extend(card["lines"])  # type: ignore[arg-type]
        if index < len(cards) - 1:
            details.extend(["", "──────────", ""])

    gt7_header = [
        "#GT7",
        "🏁 GT7 Weekly Races",
        f"📅 {get_week_range()}",
        "",
    ]
    return "\n".join(gt7_header + details).rstrip()


def format_lmu_official_week_message(races: list[dict[str, str | None]]) -> str:
    print(f"[DEBUG] LMU races count BEFORE formatting: {len(races)}")
    lines = ["#LMU", "🏁 LMU Official", "📅 Daily & Weekly", ""]
    cards: list[dict[str, object]] = []
    for race in races:
        title = (race.get("title") or "Daily Race").strip()
        track = (race.get("track") or "Unknown track").strip()
        race_class = (race.get("class") or "Unknown class").strip()
        duration = (race.get("duration") or "").strip()
        if duration.isdigit():
            duration = f"{duration}m"
        next_in = race.get("next_start_in")
        starts_in = _parse_starts_in_minutes(next_in)  # type: ignore[arg-type]
        class_duration = f"🏁 {race_class} • {duration}" if duration else f"🏁 {race_class}"
        block: list[str] = [
            f"{_group_icon(starts_in)} {title}",
            f"📍 {track}",
            class_duration,
        ]
        req_line = _extract_lmu_tier_line(race)  # type: ignore[arg-type]
        if req_line:
            block.append(req_line)
        if next_in:
            block.append(f"⏱ Starts in {next_in}")
        cards.append(
            {
                "title": title,
                "starts_in_minutes": starts_in,
                "lines": block,
                "tier": race.get("tier"),
            },
        )
        print(f"[LMU PIPELINE] stage=builder tier={race.get('tier')}")

    print(f"[DEBUG] LMU races count AFTER card aggregation: {len(cards)}")
    sorted_cards = _group_and_sort_cards(cards)
    print(f"[DEBUG] LMU races count AFTER grouping/sorting: {len(sorted_cards)}")
    limited_cards = sorted_cards[:LMU_MAX_CARDS]
    print(f"[DEBUG] LMU races count BEFORE final formatting: {len(limited_cards)}")

    for index, card in enumerate(limited_cards):
        lines.extend(card["lines"])  # type: ignore[arg-type]
        if index < len(limited_cards) - 1:
            lines.extend(["", "──────────", ""])

    return "\n".join(lines).rstrip()
