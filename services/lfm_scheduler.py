"""Expand LFM minified season JSON into concrete race events for the current calendar week."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any

from services.races_logging import ensure_races_logging_configured, logger
from services.time_utils import get_starts_in_minutes

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc, assignment]

BERLIN_TZ_NAME = "Europe/Berlin"


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _parse_lfm_datetime(raw: Any) -> datetime | None:
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


def _week_bounds_berlin(day_in_week: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """Monday 00:00 (inclusive) through the following Monday 00:00 (exclusive), Europe/Berlin."""
    monday = day_in_week - timedelta(days=day_in_week.weekday())
    start = datetime.combine(monday, time.min, tzinfo=tz)
    end = start + timedelta(days=7)
    return start, end


def _dates_in_week(week_start: date) -> list[date]:
    return [week_start + timedelta(days=i) for i in range(7)]


def _iter_daily_starts(
    day: date,
    earliest_h: int,
    latest_h: int,
    every_minutes: int,
    tz: tzinfo,
) -> list[datetime]:
    if every_minutes <= 0:
        return []
    if earliest_h < 0 or earliest_h > 23 or latest_h < 0 or latest_h > 23:
        return []
    if earliest_h > latest_h:
        return []

    day_start = datetime.combine(day, time.min, tzinfo=tz)
    first = day_start.replace(hour=earliest_h, minute=0, second=0, microsecond=0)
    last = day_start.replace(hour=latest_h, minute=59, second=59, microsecond=999999)

    out: list[datetime] = []
    t = first
    while t <= last:
        out.append(t)
        t += timedelta(minutes=every_minutes)
    return out


def _track_name(series: dict[str, Any]) -> str:
    at = series.get("active_track")
    if isinstance(at, dict):
        name = at.get("track_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return ""


def _series_title(series: dict[str, Any]) -> str:
    for key in ("series_name", "short_name", "name"):
        v = series.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _lfm_series_class_label(series: dict[str, Any]) -> str:
    """Human-readable class/car label from raw LFM series (not parser output)."""
    settings = series.get("settings") or {}
    style = (series.get("event_style") or "").strip().lower()

    def _vehicle_class_id() -> str:
        ses = settings.get("season_event_settings") or {}
        dss = ses.get("default_server_settings") or {}
        default = dss.get("default") if isinstance(dss, dict) else None
        if isinstance(default, dict):
            vid = default.get("VehicleClassId")
            if isinstance(vid, str) and vid.strip():
                return vid.strip()
        return ""

    def _from_car_classes_list(raw_cc: object) -> str:
        if not isinstance(raw_cc, list) or not raw_cc:
            return ""
        parts: list[str] = []
        for item in raw_cc:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("class") or item.get("name") or item.get("label")
                if isinstance(name, str) and name.strip():
                    parts.append(name.strip())
        if not parts:
            return ""
        return " / ".join(dict.fromkeys(parts))

    def _from_class_license_req() -> str:
        raw_clr = series.get("class_license_req")
        if not isinstance(raw_clr, list) or not raw_clr:
            return ""
        parts: list[str] = []
        for item in raw_clr:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("class") or item.get("name")
                if isinstance(name, str) and name.strip():
                    parts.append(name.strip())
        if not parts:
            return ""
        return " / ".join(dict.fromkeys(parts))

    def _from_championship() -> str:
        ch = settings.get("championship_settings") or {}
        car_classes = ch.get("car_classes")
        if not isinstance(car_classes, list) or not car_classes:
            return ""
        names: list[str] = []
        for item in car_classes:
            if isinstance(item, dict):
                c = item.get("class")
                if isinstance(c, str) and c.strip():
                    names.append(c.strip())
        if not names:
            return ""
        return " / ".join(dict.fromkeys(names))

    if style == "daily":
        v = _vehicle_class_id()
        if v:
            return v
        cc = series.get("car_class")
        if isinstance(cc, str) and cc.strip():
            return cc.strip()
        s = _from_car_classes_list(series.get("carClasses"))
        if s:
            return s
        s = _from_class_license_req()
        if s:
            return s
        return ""

    s = _from_championship()
    if s:
        return s
    s = _from_class_license_req()
    if s:
        return s
    s = _from_car_classes_list(series.get("carClasses"))
    if s:
        return s
    v = _vehicle_class_id()
    if v:
        return v
    car_class = series.get("car_class")
    if isinstance(car_class, str) and car_class.strip():
        return car_class.strip()
    return ""


def normalize_class(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    low = text.lower()
    if "gt3" in low:
        return "GT3"
    if "gt4" in low:
        return "GT4"
    if "lmp2" in low:
        return "LMP2"
    if "lmp3" in low:
        return "LMP3"
    if "lmdh" in low or "lmh" in low or "hyper" in low or low.startswith("hy "):
        return "Hypercar"
    return text.upper()


def extract_class(event: dict[str, Any]) -> str:
    series = str(event.get("series") or event.get("series_name") or "").lower()
    if not series:
        return "Unknown"

    has_gt3 = "gt3" in series
    has_gt4 = "gt4" in series
    if has_gt3 and has_gt4:
        return "Multiclass"

    if "lmp2" in series and "lmp3" in series:
        return "Multiclass"

    if "hyper" in series and ("gt3" in series or "lmp2" in series):
        return "Multiclass"

    if "mazda" in series:
        return "FIXED: Mazda MX-5"
    if "porsche cup" in series:
        return "FIXED: Porsche Cup"
    if "ferrari" in series:
        return "FIXED: Ferrari 296"
    if "lamborghini super trofeo" in series:
        return "FIXED: Lamborghini ST"

    if "gt3" in series:
        return "GT3"
    if "gt4" in series:
        return "GT4"
    if "lmp2" in series:
        return "LMP2"
    if "lmp3" in series:
        return "LMP3"
    if "hyper" in series or "lmdh" in series or "lmh" in series:
        return "Hyper"
    return "Unknown"


def _extract_car_ids(event: dict[str, Any]) -> list[str]:
    for key in ("car_ids", "carIds", "carids"):
        raw = event.get(key)
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        if isinstance(raw, (str, int)):
            one = str(raw).strip()
            return [one] if one else []
    return []


def _extract_car_lookup_key(car: dict[str, Any]) -> str:
    for key in ("server_value", "serverValue", "id", "car_id", "carId", "value"):
        v = car.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _extract_car_name(car: dict[str, Any]) -> str:
    for key in ("car_name", "name", "model", "label"):
        v = car.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _extract_car_class(car: dict[str, Any]) -> str:
    for key in ("class", "car_class", "class_name"):
        v = car.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _collect_car_rows(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        out: list[dict[str, Any]] = []
        for v in raw.values():
            if isinstance(v, dict):
                out.append(v)
            elif isinstance(v, list):
                out.extend([item for item in v if isinstance(item, dict)])
        return out
    return []


def build_cars_map(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    cars_map: dict[str, dict[str, str]] = {}
    for car in _collect_car_rows(payload.get("cars")):
        k = _extract_car_lookup_key(car)
        if not k:
            continue
        cars_map[k] = {
            "name": _extract_car_name(car),
            "class": _extract_car_class(car),
        }

    series_root = payload.get("series")
    if not isinstance(series_root, dict):
        return cars_map
    for sim_block in series_root.values():
        if not isinstance(sim_block, dict):
            continue
        for car in _collect_car_rows(sim_block.get("cars")):
            k = _extract_car_lookup_key(car)
            if not k:
                continue
            cars_map[k] = {
                "name": _extract_car_name(car),
                "class": _extract_car_class(car),
            }
    return cars_map


def parse_class_from_cars(event: dict[str, Any], cars_map: dict[str, dict[str, str]]) -> str | None:
    car_ids = _extract_car_ids(event)
    if not car_ids:
        return None

    if len(car_ids) == 1:
        one = cars_map.get(car_ids[0], {})
        car_name = one.get("name") if isinstance(one, dict) else ""
        if isinstance(car_name, str) and car_name.strip():
            return f"FIXED: {car_name.strip()}"

    classes: set[str] = set()
    for car_id in car_ids:
        car = cars_map.get(car_id)
        if not isinstance(car, dict):
            continue
        raw_class = car.get("class")
        if not isinstance(raw_class, str) or not raw_class.strip():
            continue
        norm = normalize_class(raw_class)
        if norm:
            classes.add(norm)
    if not classes:
        return None
    if len(classes) == 1:
        return next(iter(classes))
    return "Multiclass"


def resolve_event_class(event: dict[str, Any], cars_map: dict[str, dict[str, str]]) -> str:
    series_name = event.get("series")
    if not isinstance(series_name, str):
        series_name = event.get("series_name")
    if not isinstance(series_name, str):
        series_name = _series_title(event)
    extracted = extract_class({"series": series_name})
    if extracted != "Unknown":
        return extracted
    return (
        parse_class_from_cars(event, cars_map)
        or _lfm_series_class_label(event)
        or "Unknown"
    )


def _weekly_race_times(series: dict[str, Any]) -> list[datetime]:
    times: list[datetime] = []
    seen: set[tuple[int, int, int, int, int, int, int]] = set()

    for raw in (series.get("next_race"),):
        dt = _parse_lfm_datetime(raw)
        if dt is not None:
            k = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond)
            if k not in seen:
                seen.add(k)
                times.append(dt)

    n3 = series.get("next3_races")
    if isinstance(n3, list):
        for item in n3:
            dt = _parse_lfm_datetime(item)
            if dt is None:
                continue
            k = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond)
            if k not in seen:
                seen.add(k)
                times.append(dt)

    return times


_LFM_SIM_ORDER = [
    "Automobilista 2",
    "Le Mans Ultimate",
    "Assetto Corsa Competizione",
    "Assetto Corsa EVO",
    "iRacing",
    "rFactor 2",
    "RaceRoom",
]


def _lfm_requirements_from_series(series: dict[str, Any]) -> dict[str, str] | None:
    out: dict[str, str] = {}
    lic = series.get("min_license")
    if isinstance(lic, str) and lic.strip():
        out["license"] = lic.strip()
    sr = series.get("min_sr")
    if sr is not None and str(sr).strip():
        out["safety"] = str(sr).strip()
    return out if out else None


def _lfm_drivers_from_series(series: dict[str, Any]) -> int | None:
    for key in ("signups", "drivers", "registered_drivers"):
        v = _as_int(series.get(key))
        if v is not None:
            return v
    return None


def _ordered_sims_lfm(sims: set[str]) -> list[str]:
    remaining = set(sims)
    out: list[str] = []
    for name in _LFM_SIM_ORDER:
        if name in remaining:
            out.append(name)
            remaining.discard(name)
    out.extend(sorted(remaining))
    return out


def _enrich_lfm_events(
    events: list[dict[str, Any]],
    ref_local: datetime,
    tz: tzinfo,
) -> list[dict[str, Any]]:
    if not events:
        return events

    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        if not isinstance(ev, dict):
            continue
        sim = ev.get("sim")
        ser = ev.get("series")
        if isinstance(sim, str) and isinstance(ser, str):
            by_key[(sim.strip(), ser.strip())].append(ev)

    min_utc = datetime.min.replace(tzinfo=timezone.utc)
    for evs in by_key.values():
        evs.sort(
            key=lambda e: _parse_lfm_datetime(e.get("startTime")) or min_utc,
        )
        for i, ev in enumerate(evs):
            st = _parse_lfm_datetime(ev.get("startTime"))
            if st is None:
                continue
            st_local = st.astimezone(tz)
            starts_in = get_starts_in_minutes(ref_local, st_local)
            ev["starts_in_minutes"] = starts_in if starts_in <= 0 else starts_in + 1
            if i + 1 < len(evs):
                st2 = _parse_lfm_datetime(evs[i + 1].get("startTime"))
                if st2 is not None:
                    gap = (st2 - st).total_seconds()
                    if gap > 0:
                        ev["every_minutes"] = int(gap // 60)
            elif ev.get("type") != "daily":
                ev.pop("every_minutes", None)

    sims_before = {
        str(ev.get("sim")).strip()
        for ev in events
        if isinstance(ev, dict)
        and isinstance(ev.get("sim"), str)
        and str(ev.get("sim")).strip()
    }
    logger.info(f"[LFM] sims before grouping: {sims_before}")
    logger.info(f"[LFM] total races before grouping: {len(events)}")

    by_sim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in events:
        if isinstance(ev, dict) and isinstance(ev.get("sim"), str):
            by_sim[ev["sim"].strip()].append(ev)

    logger.info(f"[LFM] sims after grouping: {list(by_sim.keys())}")
    logger.info("[LFM] races per sim:")
    for sim, items in by_sim.items():
        logger.info(f"{sim}: {len(items)}")

    out: list[dict[str, Any]] = []
    for sim in _ordered_sims_lfm(set(by_sim.keys())):
        bucket = by_sim.get(sim, [])
        out.extend(bucket)

    return out


def flatten_lfm_week_events(
    payload: dict[str, Any],
    *,
    reference_utc: datetime | None = None,
    timezone_name: str | None = None,
) -> list[dict[str, Any]]:
    """
    Build a flat list of race dicts for the ISO week (Mon–Sun, Europe/Berlin) that contains
    ``reference_utc`` (defaults to now, UTC-aware).
    """
    ensure_races_logging_configured()

    tz_name = timezone_name or BERLIN_TZ_NAME
    if ZoneInfo is None:
        raise RuntimeError("zoneinfo is required (Python 3.9+)")
    tz = ZoneInfo(tz_name)

    ref = reference_utc or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    ref_local = ref.astimezone(tz)
    week_start, week_end = _week_bounds_berlin(ref_local.date(), tz)
    week_dates = _dates_in_week(week_start.date())
    cars_map = build_cars_map(payload)

    events: list[dict[str, Any]] = []

    series_root = payload.get("series")
    if not isinstance(series_root, dict):
        logger.info("[LFM] sims: 0")
        logger.info("[LFM] total series: 0")
        logger.info("[LFM] generated races before week filter: 0")
        logger.info("[LFM] generated races after week filter: 0")
        return events

    sims_count = len(series_root)
    series_total = 0
    for _sim_block in series_root.values():
        if isinstance(_sim_block, dict):
            _sl = _sim_block.get("series")
            if isinstance(_sl, list):
                series_total += len(_sl)

    generated_before = 0

    for sim_block in series_root.values():
        if not isinstance(sim_block, dict):
            continue
        sim_name = sim_block.get("simulation")
        sim = sim_name.strip() if isinstance(sim_name, str) else ""
        series_list = sim_block.get("series")
        if not isinstance(series_list, list):
            continue

        for series in series_list:
            if not isinstance(series, dict):
                continue
            style = series.get("event_style")
            if style not in ("daily", "weekly"):
                continue

            title = _series_title(series)
            track = _track_name(series)
            duration = _as_int(series.get("race_length"))
            if duration is None:
                duration = 0
            cls = resolve_event_class(series, cars_map)
            car_label: str | None = None
            class_label = cls
            if cls.startswith("FIXED:"):
                class_label = "Fixed"
                car_label = cls.replace("FIXED:", "", 1).strip()
            reqs = _lfm_requirements_from_series(series)
            drv = _lfm_drivers_from_series(series)

            if style == "daily":
                settings = series.get("settings")
                ses: dict[str, Any] = {}
                if isinstance(settings, dict):
                    raw_ses = settings.get("season_event_settings")
                    if isinstance(raw_ses, dict):
                        ses = raw_ses

                earliest = _as_int(ses.get("ingame_earliest_racehour"))
                latest = _as_int(ses.get("ingame_latest_racehour"))
                every = _as_int(ses.get("races_every"))
                if earliest is None or latest is None or every is None:
                    continue

                for d in week_dates:
                    for start in _iter_daily_starts(d, earliest, latest, every, tz):
                        generated_before += 1
                        row: dict[str, Any] = {
                            "sim": sim,
                            "source": "lfm",
                            "series": title,
                            "track": track,
                            "class": class_label,
                            "startTime": start.isoformat(),
                            "duration": duration,
                            "type": "daily",
                            "every_minutes": int(every),
                        }
                        if car_label:
                            row["car"] = car_label
                        if drv is not None:
                            row["drivers"] = drv
                        if reqs:
                            row["requirements"] = reqs
                        events.append(row)

            else:  # weekly
                for start in _weekly_race_times(series):
                    generated_before += 1
                    local_start = start.astimezone(tz)
                    row_w: dict[str, Any] = {
                        "sim": sim,
                        "source": "lfm",
                        "series": title,
                        "track": track,
                        "class": class_label,
                        "startTime": local_start.isoformat(),
                        "duration": duration,
                        "type": "weekly",
                    }
                    if car_label:
                        row_w["car"] = car_label
                    if drv is not None:
                        row_w["drivers"] = drv
                    if reqs:
                        row_w["requirements"] = reqs
                    events.append(row_w)

    events = _enrich_lfm_events(events, ref_local, tz)
    logger.info(f"[LFM] sims: {sims_count}")
    logger.info(f"[LFM] total series: {series_total}")
    logger.info(f"[LFM] generated races before week filter: {generated_before}")
    logger.info(f"[LFM] generated races after week filter: {len(events)}")
    return events
