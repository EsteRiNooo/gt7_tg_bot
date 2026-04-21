from datetime import date, timedelta
from html import escape
from typing import Any

from services.utils import is_single_car

_REQUIREMENT_EMOJI: dict[str, str] = {
    "license": "🎫",
    "safety": "🛡",
}


def format_requirements_lines(race: dict[str, Any], *, html: bool = True) -> list[str]:
    """One line per requirement key; empty dict / None -> no lines."""
    requirements = race.get("requirements")
    if not isinstance(requirements, dict) or not requirements:
        return []

    lines: list[str] = []
    for key in sorted(requirements.keys()):
        if str(key).endswith("_raw"):
            continue
        raw_value = requirements.get(key)
        if raw_value is None:
            continue
        text = str(raw_value).strip()
        if not text:
            continue
        display = escape(text) if html else text
        emoji = _REQUIREMENT_EMOJI.get(key)
        if emoji:
            lines.append(f"{emoji} {display}")
        else:
            key_display = escape(str(key)) if html else str(key)
            lines.append(f"{key_display}: {display}")
    return lines


def get_week_range() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.strftime('%b')} {monday.day} – {sunday.strftime('%b')} {sunday.day}"


def format_full_week(races: list[dict[str, str | int | None]]) -> str:
    race_order = {"Race A": 0, "Race B": 1, "Race C": 2}
    ordered_races = sorted(
        races, key=lambda race: race_order.get((race.get("title") or "").strip(), 99)
    )

    lines: list[str] = ["🏁 <b>GT7 Weekly Races</b>", f"🗓 <i>{get_week_range()}</i>", ""]

    for index, race in enumerate(ordered_races):
        title = escape((race.get("title") or "Race").strip())
        track = escape((race.get("track") or "Unknown track").strip())
        race_class = escape((race.get("class") or "Unknown class").strip())

        lines.extend(
            [
                f"🏁 <b>{title}</b>",
                f"📍 {track}",
                f"🏎 {race_class}",
            ]
        )

        lines.extend(format_requirements_lines(race, html=True))

        laps_value = race.get("laps")
        if laps_value is not None:
            lines.append(f"🔁 {escape(str(laps_value))} laps")

        tires = (race.get("tires") or "").strip()
        if tires:
            lines.append(f"🛞 {escape(tires)}")

        car = (race.get("car") or "").strip()
        if car and is_single_car(car):
            lines.append(f"🚘 {escape(car)}")

        if index < len(ordered_races) - 1:
            lines.extend(["", "➖➖➖➖➖➖", ""])

    return "\n".join(lines).rstrip()


def append_source_errors(
    full_text: str, errors: list[dict[str, str]] | None
) -> str:
    if not errors:
        return full_text

    lines = [full_text, "", "⚠ Some sources failed:"]
    for item in errors:
        source = escape((item.get("source") or "unknown").strip())
        error = escape((item.get("error") or "unknown error").strip())
        lines.append(f"- {source}: {error}")

    return "\n".join(lines).rstrip()
