import hashlib
import json
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile, InputMediaPhoto
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from services.formatting import format_full_week
from services.races import get_current_races
from services.subscribers import list_subscribers, remove_subscriber
from services.track_images import find_track_image

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


def _build_race_hash(races: list[dict[str, str | None]]) -> str:
    ordered_races = _ordered_races(races)
    payload = [
        {
            "title": race.get("title"),
            "track": race.get("track"),
            "class": race.get("class"),
            "tires": race.get("tires"),
            "laps": race.get("laps"),
            "car": race.get("car"),
        }
        for race in ordered_races
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _ordered_races(races: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    race_order = {"Race A": 0, "Race B": 1, "Race C": 2}
    return sorted(races, key=lambda race: race_order.get((race.get("title") or "").strip(), 99))


async def send_weekly_races(bot: Bot, force: bool = False) -> None:
    print("Checking weekly races...")

    races = _ordered_races(get_current_races())
    races_hash = _build_race_hash(races)
    old_hash = _read_last_hash()

    if not force and races_hash == old_hash:
        print("No changes, skipping")
        return

    user_ids = list_subscribers()
    if not user_ids:
        print("Weekly auto-post skipped: no subscribers.")
        return

    print("Sending new weekly update")

    sent_any = False
    for user_id in user_ids:
        try:
            await _send_weekly_message(bot=bot, user_id=user_id, races=races)
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


async def _send_weekly_message(
    bot: Bot, user_id: int, races: list[dict[str, str | None]]
) -> None:
    full_text = format_full_week(races)
    image_paths = [find_track_image((race.get("track") or "").strip()) for race in races]
    valid_image_paths = [path for path in image_paths if path]

    if not valid_image_paths:
        await bot.send_message(user_id, full_text, parse_mode="HTML")
        return

    media: list[InputMediaPhoto] = []
    for index, path in enumerate(valid_image_paths):
        photo = FSInputFile(path)
        if index == 0:
            media.append(InputMediaPhoto(media=photo, caption=full_text, parse_mode="HTML"))
        else:
            media.append(InputMediaPhoto(media=photo))

    await bot.send_media_group(user_id, media=media)
