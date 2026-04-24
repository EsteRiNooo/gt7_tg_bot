import re
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from typing import Any

import requests

from services.parsers.base import BaseParser
from services.races_logging import ensure_races_logging_configured, logger
from services.time_utils import get_starts_in_minutes

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

LMU_ALLOWED_RACE_TYPES = frozenset({"Daily Races", "Weekly Races"})


def _format_interval_label(delta_minutes: int) -> str:
    if delta_minutes <= 0:
        return ""
    if delta_minutes % 60 == 0:
        return f"{delta_minutes // 60}h"
    return f"{delta_minutes}m"


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


def _normalize_iso_time(raw_time: str | None) -> datetime | None:
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


def _parse_hh_mm_local(value: str, now_local: datetime) -> datetime | None:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    tz = now_local.tzinfo
    base = datetime.combine(now_local.date(), time(hour, minute), tzinfo=tz)
    if base <= now_local:
        base = base + timedelta(days=1)
    return base


def _extract_future_local_times(raw_times: object, now_local: datetime) -> list[datetime]:
    """Parse times (prefer HH:MM local; fallback ISO), return sorted future datetimes in local tz."""
    candidates: list[datetime] = []
    if not isinstance(raw_times, list):
        return candidates

    for item in raw_times:
        if isinstance(item, str):
            s = item.strip()
            if not s:
                continue
            local_dt = _parse_hh_mm_local(s, now_local)
            if local_dt is not None:
                candidates.append(local_dt)
                continue
            iso_dt = _normalize_iso_time(s)
            if iso_dt is not None:
                candidates.append(iso_dt.astimezone(now_local.tzinfo))
            continue

        if isinstance(item, dict):
            for key in ("time", "startTime", "start", "date", "datetime"):
                raw = item.get(key)
                if isinstance(raw, str):
                    s = raw.strip()
                    local_dt = _parse_hh_mm_local(s, now_local)
                    if local_dt is not None:
                        candidates.append(local_dt)
                        break
                    iso_dt = _normalize_iso_time(s)
                    if iso_dt is not None:
                        candidates.append(iso_dt.astimezone(now_local.tzinfo))
                        break

    future = sorted(t for t in candidates if t >= now_local)
    return future


def _sr_multiplier_display(race: dict[str, Any]) -> str | None:
    """Raw SR multiplier string only — never used to infer tier."""
    for key in ("safetyRank", "safetyRating", "sr"):
        raw = race.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return None


def _extract_tier_from_event(race: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (tier, source_key) from raw LMU fields only (no SR inference)."""
    for key in ("licenseLevel", "driverCategory", "category"):
        value = race.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), key

    candidate_keys = (
        "rank",
        "split",
        "skillLevel",
        "license",
    )
    for key in candidate_keys:
        value = race.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), key

    for parent_key in ("requirements", "entryRequirements", "restriction", "rules"):
        parent = race.get(parent_key)
        if not isinstance(parent, dict):
            continue
        nested = (
            parent.get("licenseLevel")
            or parent.get("driverCategory")
            or parent.get("category")
        )
        if isinstance(nested, str) and nested.strip():
            return nested.strip(), f"{parent_key}.(licenseLevel|driverCategory|category)"
        for key in candidate_keys:
            value = parent.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip(), f"{parent_key}.{key}"
    return None, None


class LMUOfficialParser(BaseParser):
    name = "lmu_official"

    async def get_races(self) -> list[dict]:
        return self.get_races_sync()

    def get_races_sync(self) -> list[dict[str, Any]]:
        ensure_races_logging_configured()
        logger.info("[LMU] start parsing")
        try:
            response = requests.get(
                LMU_SCHEDULES_URL,
                headers=REQUEST_HEADERS,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code != 200:
                print(f"LMU official API status code: {response.status_code}")
            response.raise_for_status()
            logger.info("[LMU] payload received")
            payload = response.json()
        except requests.RequestException as error:
            logger.error(f"[LMU] error: {error}")
            print(f"LMU official API request error: {error}")
            raise
        except ValueError as error:
            logger.error(f"[LMU] error: {error}")
            print(f"LMU official API JSON parse error: {error}")
            raise

        if not isinstance(payload, dict) or "body" not in payload:
            print("LMU official API returned invalid wrapped payload")
            err = ValueError("invalid LMU API payload")
            logger.error(f"[LMU] error: {err}")
            raise err
        data = payload["body"]
        if not isinstance(data, list):
            print("LMU official API returned non-list body payload")
            err = ValueError("invalid LMU API payload")
            logger.error(f"[LMU] error: {err}")
            raise err
        print(f"LMU API returned {len(data)} races")
        print(f"[LMU] RAW races count: {len(data)}")
        for race in data:
            if not isinstance(race, dict):
                print("[LMU RAW] non-dict race:", race)
                continue
            print(
                "[LMU RAW]",
                {
                    "name": race.get("name"),
                    "series": race.get("series"),
                    "track": race.get("track") or race.get("circuit"),
                    "class": race.get("carClass") or race.get("carClasses"),
                    "duration": race.get("duration") or race.get("raceLength"),
                    "skill": race.get("skillLevel"),
                    "license": race.get("license"),
                    "sr": race.get("safetyRating") or race.get("safetyRank"),
                    "start": race.get("startTime") or race.get("times"),
                },
            )

        logger.info(f"[LMU] parsed items: {len(data)}")

        now_local = datetime.now().astimezone()
        races: list[dict[str, Any]] = []
        parsed_races: list[dict[str, Any]] = []

        for race in data:
            print("[LMU RAW BEFORE PARSING]", race)
            print("[LMU RAW EVENT]", race)
            if not isinstance(race, dict):
                print("[LMU SKIPPED] race is not dict:", race)
                continue
            race_type = race.get("raceType")
            if race_type not in LMU_ALLOWED_RACE_TYPES:
                print("[LMU DROP] unsupported raceType", {"raceType": race_type, "race": race})
                continue

            future_times = _extract_future_local_times(race.get("times"), now_local)
            if not future_times:
                print("[LMU DROP] missing/empty future times", race)
                continue

            next_start = future_times[0]
            starts_in = get_starts_in_minutes(now_local, next_start)
            minutes = starts_in if starts_in <= 0 else starts_in + 1
            next_start_in = f"{minutes}m"

            interval: str | None = None
            if len(future_times) >= 2:
                gap_seconds = (future_times[1] - future_times[0]).total_seconds()
                gap_minutes = int(gap_seconds // 60)
                if gap_minutes > 0:
                    label = _format_interval_label(gap_minutes)
                    if label:
                        interval = label

            track, layout = _parse_track(race.get("circuit"))

            raw_classes = race.get("carClasses")
            if isinstance(raw_classes, list):
                class_value = " / ".join(str(item).strip() for item in raw_classes if str(item).strip())
                race_class = class_value or None
            elif raw_classes is None:
                race_class = None
            else:
                race_class = str(raw_classes).strip() or None
            if not race_class:
                print("[LMU DROP] missing carClass", race)
                continue

            title_value = race.get("series")
            title = str(title_value).strip() if title_value is not None else None
            if title == "":
                title = None
            if not title:
                print("[LMU DROP] missing series/title", race)
                continue

            duration_value = race.get("raceLength")
            duration = str(duration_value).strip() if duration_value is not None else None
            if duration == "":
                duration = None
            if not duration:
                print("[LMU DROP] missing duration", race)
                continue

            tier, tier_field = _extract_tier_from_event(race)
            sr_multiplier = _sr_multiplier_display(race)
            safety_rank_value = race.get("safetyRank")
            safety_rank: str | None = None
            if safety_rank_value is not None:
                s_rank = str(safety_rank_value).strip()
                if s_rank:
                    safety_rank = s_rank
            if tier is None:
                tier = "Unknown"
                print("[LMU WARNING] No tier found in event", race)
            requirements: dict[str, str] | None = {}
            requirements["license"] = tier
            if sr_multiplier:
                requirements["safety_raw"] = sr_multiplier
            print(
                f"[LMU DEBUG] tier={tier}, field={tier_field}, sr={sr_multiplier}, raw={race}",
            )
            print(f"[LMU PIPELINE] stage=parser tier={tier}")

            type_norm = "daily" if race_type == "Daily Races" else "weekly"

            parsed = {
                "game": "lmu",
                "source": "lmu_official",
                "type": type_norm,
                "title": title,
                "track": track,
                "layout": layout,
                "class": race_class,
                "laps": None,
                "duration": duration,
                "tires": None,
                "car": None,
                "start_time": next_start.isoformat(),
                "next_start_in": next_start_in,
                "interval": interval,
                "tier": tier,
                "tier_field": tier_field,
                "sr_multiplier": sr_multiplier,
                "safety_rank": safety_rank,
                "requirements": requirements,
                "uid": _build_uid("lmu", title, track),
            }
            print("[LMU PARSED]", parsed)
            parsed_races.append(parsed)
            races.append(parsed)

        print(f"[LMU] FINAL races count: {len(parsed_races)}")
        series_counter = Counter(str(r.get("title") or "") for r in parsed_races)
        print("[LMU SERIES DISTRIBUTION]", dict(series_counter))
        logger.info(f"[LMU] normalized races: {len(races)}")
        if not races:
            logger.warning("[LMU] no races generated")

        return races
