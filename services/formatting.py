from datetime import date, timedelta
from html import escape

from services.races import is_single_car


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
