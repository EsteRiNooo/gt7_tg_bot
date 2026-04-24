"""Per-user toggles for race sources (GT7, LMU, LFM by sim). Stored in user_settings.json."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "user_settings.json"
_lock = threading.RLock()

# (settings_key, button label)
TOGGLE_SOURCE_DEFS: list[tuple[str, str]] = [
    ("gt7", "GT7"),
    ("lmu_official", "LMU Official"),
    ("lfm_lmu", "LFM LMU"),
    ("lfm_acc", "LFM ACC"),
    ("lfm_ac", "LFM AC"),
    ("lfm_ams2", "LFM AMS2"),
    ("lfm_raceroom", "LFM RaceRoom"),
    ("lfm_acevo", "LFM ACEVO"),
]

DEFAULT_SOURCE_TOGGLES: dict[str, bool] = {key: True for key, _ in TOGGLE_SOURCE_DEFS}

KNOWN_TOGGLE_KEYS: frozenset[str] = frozenset(DEFAULT_SOURCE_TOGGLES)

# LFM API / flatten uses these simulation names on events (see lfm_scheduler / lfm_series_cards).
LFM_SIM_NAME_BY_KEY: dict[str, str] = {
    "lfm_acc": "Assetto Corsa Competizione",
    "lfm_ac": "Assetto Corsa",
    "lfm_ams2": "Automobilista 2",
    "lfm_raceroom": "RaceRoom",
    "lfm_acevo": "Assetto Corsa EVO",
}

SETTINGS_SCREEN_HTML = (
    "⚙️ <b>Источники гонок</b>\n\n"
    "Нажми на источник, чтобы включить или выключить его.\n"
    "✅ — показывается в «Показать гонки» / /current\n"
    "❌ — скрыт"
)

EMPTY_FILTERED_RACES_MESSAGE = (
    "По твоим текущим настройкам гонок не найдено.\n\n"
    "Попробуй включить больше источников в ⚙️ Настройках."
)

# get_all_races() bucket "source" -> user setting key that toggles the whole bucket (None = row-level only).
AGGREGATE_SOURCE_TO_BUCKET_SETTING_KEY: dict[str, str | None] = {
    "gt7": "gt7",
    "lmu_official": "lmu_official",
    "lfm": None,
}


def _load_file() -> dict[str, Any]:
    if not _SETTINGS_PATH.exists():
        return {}
    try:
        raw = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_file(data: dict[str, Any]) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SETTINGS_PATH.with_suffix(".json.tmp")
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    with _lock:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(_SETTINGS_PATH)


def get_merged_settings(user_id: int | None) -> dict[str, bool]:
    """All known keys present; missing user or file -> defaults (all on)."""
    out = dict(DEFAULT_SOURCE_TOGGLES)
    if user_id is None:
        return out
    with _lock:
        all_users = _load_file()
        row = all_users.get(str(user_id))
    if not isinstance(row, dict):
        return out
    for key in DEFAULT_SOURCE_TOGGLES:
        if key in row:
            out[key] = bool(row[key])
    # legacy: "lmu" -> lmu_official (before split LMU Official / LFM LMU)
    if "lmu_official" not in row and "lmu" in row:
        out["lmu_official"] = bool(row["lmu"])
    return out


def toggle_source(user_id: int, key: str) -> dict[str, bool]:
    if key not in KNOWN_TOGGLE_KEYS:
        return get_merged_settings(user_id)
    with _lock:
        all_users = _load_file()
        uid_s = str(user_id)
        prev = all_users.get(uid_s)
        row = dict(DEFAULT_SOURCE_TOGGLES)
        if isinstance(prev, dict):
            for k in DEFAULT_SOURCE_TOGGLES:
                if k in prev:
                    row[k] = bool(prev[k])
            if "lmu_official" not in prev and "lmu" in prev:
                row["lmu_official"] = bool(prev["lmu"])
        row[key] = not bool(row.get(key, True))
        all_users[uid_s] = {k: row[k] for k in DEFAULT_SOURCE_TOGGLES}
        _write_file(all_users)
    return row


def filter_races_by_user_settings(
    aggregated_results: list[dict[str, Any]],
    user_id: int | None,
) -> list[dict[str, Any]]:
    """
    Filter normalized output of ``get_all_races()`` after aggregation, before formatting.
    - gt7 / lmu_official: whole list cleared when the matching setting is off.
    - lfm: per-event rules via ``filter_lfm_flat_by_settings`` (LFM LMU, ACC, …).
    """
    settings = get_merged_settings(user_id)
    out: list[dict[str, Any]] = []
    for item in aggregated_results:
        row = dict(item)
        src = str(row.get("source") or "")
        data = row.get("data")
        if data is None:
            out.append(row)
            continue
        bucket_key = AGGREGATE_SOURCE_TO_BUCKET_SETTING_KEY.get(src)
        if bucket_key is not None:
            if not settings.get(bucket_key, True):
                row["data"] = []
            else:
                row["data"] = list(data)
        elif src == "lfm":
            row["data"] = filter_lfm_flat_by_settings(list(data), settings)
        else:
            row["data"] = list(data)
        out.append(row)
    return out


def aggregated_results_have_any_races(results: list[dict[str, Any]]) -> bool:
    for item in results:
        data = item.get("data")
        if isinstance(data, list) and len(data) > 0:
            return True
    return False


def filter_lfm_flat_by_settings(
    flat_events: list[dict[str, Any]],
    settings: dict[str, bool],
) -> list[dict[str, Any]]:
    """After aggregation: lfm_lmu vs lfm by sim toggles; unknown sims if any named LFM sim is on."""
    sim_to_key = {name: key for key, name in LFM_SIM_NAME_BY_KEY.items()}
    any_named_lfm_sim = any(settings.get(k, True) for k in LFM_SIM_NAME_BY_KEY)
    out: list[dict[str, Any]] = []
    for ev in flat_events:
        if not isinstance(ev, dict):
            continue
        src = str(ev.get("source") or "").strip()
        if src == "lfm_lmu":
            if settings.get("lfm_lmu", True):
                out.append(ev)
            continue
        if src != "lfm":
            continue
        sim = str(ev.get("sim") or "").strip()
        # Legacy rows: LMU-in-LFM used source "lfm" before lfm_lmu existed.
        if sim == "Le Mans Ultimate":
            if settings.get("lfm_lmu", True):
                out.append(ev)
            continue
        setting_key = sim_to_key.get(sim)
        if setting_key is not None:
            if settings.get(setting_key, True):
                out.append(ev)
        elif any_named_lfm_sim:
            out.append(ev)
    return out
