import hashlib
import json
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from services.races import get_all_races
from services.subscribers import list_subscribers, remove_subscriber
from services.user_race_settings import (
    aggregated_results_have_any_races,
    filter_races_by_user_settings,
)
from services.week_races_delivery import deliver_filtered_week_to_chat

HASH_FILE = Path("data/last_hash.txt")


def create_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_weekly_races,
        trigger="cron",
        day_of_week="mon",
        hour=10,
        minute=0,
        kwargs={"bot": bot},
    )
    print("Scheduler started")
    return scheduler


def _read_last_hash() -> str | None:
    if not HASH_FILE.exists():
        return None
    try:
        value = HASH_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _write_last_hash(value: str) -> None:
    HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HASH_FILE.write_text(value, encoding="utf-8")


def _collect_source_errors(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in results:
        err = item.get("error")
        if not err:
            continue
        out.append(
            {
                "source": str(item.get("source") or "unknown"),
                "error": str(err),
            },
        )
    return out


def _build_aggregated_week_hash(results: list[dict[str, Any]]) -> str:
    """Fingerprint full normalized week (all parsers) for change detection."""
    payload: list[dict[str, Any]] = []
    for item in sorted(results, key=lambda x: str(x.get("source") or "")):
        payload.append(
            {
                "source": item.get("source"),
                "error": item.get("error"),
                "data": item.get("data"),
            },
        )
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def send_weekly_races(bot: Bot, force: bool = False) -> None:
    print("Checking weekly races...")

    results = await get_all_races()
    races_hash = _build_aggregated_week_hash(results)
    old_hash = _read_last_hash()

    if not force and races_hash == old_hash:
        print("No changes, skipping")
        return

    user_ids = list_subscribers()
    if not user_ids:
        print("Weekly auto-post skipped: no subscribers.")
        return

    print("Sending new weekly update")

    errors = _collect_source_errors(results)
    sent_any = False
    for user_id in user_ids:
        filtered = filter_races_by_user_settings(results, user_id)
        if not aggregated_results_have_any_races(filtered):
            print(f"Weekly update skipped for {user_id}: no races after source filters.")
            continue
        try:
            await deliver_filtered_week_to_chat(
                bot,
                user_id,
                filtered_results=filtered,
                source_errors=errors or None,
            )
            sent_any = True
        except TelegramForbiddenError:
            remove_subscriber(user_id)
            print(f"User blocked bot, removed subscriber: {user_id}")
        except TelegramBadRequest as error:
            print(f"Skip user {user_id} due to bad request: {error}")
        except Exception as error:
            print(f"Failed to send weekly races to {user_id}: {error}")

    if sent_any:
        _write_last_hash(races_hash)
