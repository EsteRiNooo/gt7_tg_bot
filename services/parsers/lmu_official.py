import re
from datetime import datetime, timezone

import requests

from services.parsers.base import BaseParser

LMU_SCHEDULES_URL = "https://api.lmuschedule.com/racingschedules"
REQUEST_TIMEOUT_SECONDS = 10
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/115.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.lmuschedule.com/",
    "Origin": "https://www.lmuschedule.com",
}


def _slugify(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return re.sub(r"_+", "_", normalized)


def _build_uid(game: str | None, race: str | None, track: str | None) -> str:
    parts = [_slugify(game), _slugify(race), _slugify(track)]
    return "_".join(part for part in parts if part)


def _parse_track(circuit: str | None) -> tuple[str | None, str | None]:
    if not circuit:
        return None, None

    value = circuit.strip()
    if " - " in value:
        track_name, layout = value.split(" - ", 1)
        return track_name.strip() or None, layout.strip() or None

    paren_match = re.match(r"^(.*?)\s*\((.*?)\)\s*$", value)
    if paren_match:
        return paren_match.group(1).strip() or None, paren_match.group(2).strip() or None

    return value or None, None


def _normalize_time(raw_time: str | None) -> datetime | None:
    if not raw_time or not isinstance(raw_time, str):
        return None

    value = raw_time.strip()
    if not value:
        return None

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_time_candidates(raw_times: object) -> list[datetime]:
    candidates: list[datetime] = []
    if not isinstance(raw_times, list):
        return candidates

    for item in raw_times:
        if isinstance(item, str):
            parsed = _normalize_time(item)
            if parsed is not None:
                candidates.append(parsed)
            continue

        if isinstance(item, dict):
            for key in ("time", "startTime", "start", "date", "datetime"):
                parsed = _normalize_time(item.get(key))
                if parsed is not None:
                    candidates.append(parsed)
                    break

    return candidates


class LMUOfficialParser(BaseParser):
    name = "lmu_official"

    async def get_races(self) -> list[dict]:
        return self.get_races_sync()

    def get_races_sync(self) -> list[dict[str, str | int | None]]:
        try:
            response = requests.get(
                LMU_SCHEDULES_URL,
                headers=REQUEST_HEADERS,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code != 200:
                print(f"LMU official API status code: {response.status_code}")
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            print(f"LMU official API request error: {error}")
            raise
        except ValueError as error:
            print(f"LMU official API JSON parse error: {error}")
            raise

        if not isinstance(payload, dict) or "body" not in payload:
            print("LMU official API returned invalid wrapped payload")
            raise ValueError("invalid LMU API payload")
        data = payload["body"]
        if not isinstance(data, list):
            print("LMU official API returned non-list body payload")
            raise ValueError("invalid LMU API payload")
        print(f"LMU API returned {len(data)} races")

        now_utc = datetime.now(timezone.utc)
        races: list[dict[str, str | int | None]] = []

        for race in data:
            if not isinstance(race, dict):
                continue
            if race.get("raceType") != "Daily Races":
                continue

            times = _extract_time_candidates(race.get("times"))
            future_times = sorted(time_value for time_value in times if time_value >= now_utc)
            if not future_times:
                continue

            next_time = future_times[0].isoformat()
            track, layout = _parse_track(race.get("circuit"))

            raw_classes = race.get("carClasses")
            if isinstance(raw_classes, list):
                class_value = " / ".join(str(item).strip() for item in raw_classes if str(item).strip())
                race_class = class_value or None
            elif raw_classes is None:
                race_class = None
            else:
                race_class = str(raw_classes).strip() or None

            title_value = race.get("series")
            title = str(title_value).strip() if title_value is not None else None
            if title == "":
                title = None

            duration_value = race.get("raceLength")
            duration = str(duration_value).strip() if duration_value is not None else None
            if duration == "":
                duration = None

            races.append(
                {
                    "game": "lmu",
                    "source": "official",
                    "type": "daily",
                    "title": title,
                    "track": track,
                    "layout": layout,
                    "class": race_class,
                    "laps": None,
                    "duration": duration,
                    "tires": None,
                    "car": None,
                    "start_time": next_time,
                    "uid": _build_uid("lmu", title, track),
                }
            )

        return races
