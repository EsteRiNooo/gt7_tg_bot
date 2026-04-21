from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, InputMediaPhoto, Message

from scheduler import send_weekly_races
from services.formatting import append_source_errors, format_full_week
from services.races import get_current_races_with_errors
from services.subscribers import add_subscriber
from services.track_images import find_track_image

router = Router()


def _ordered_races(races: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    race_order = {"Race A": 0, "Race B": 1, "Race C": 2}
    return sorted(races, key=lambda race: race_order.get((race.get("title") or "").strip(), 99))


@router.message(Command("start"))
async def start_handler(message: Message) -> None:
    if message.from_user:
        add_subscriber(message.from_user.id)

    await message.answer(
        "Hi! I am your GT7 weekly races bot.\n"
        "Use /current to see this week's races."
    )


@router.message(Command("current"))
async def current_handler(message: Message) -> None:
    races, errors = await get_current_races_with_errors()
    races = _ordered_races(races)
    full_text = format_full_week(races)
    full_text = append_source_errors(full_text, errors)

    image_paths = [find_track_image((race.get("track") or "").strip()) for race in races]
    valid_image_paths = [path for path in image_paths if path]

    if not valid_image_paths:
        await message.answer(full_text, parse_mode="HTML")
        return

    media: list[InputMediaPhoto] = []
    for index, path in enumerate(valid_image_paths):
        photo = FSInputFile(path)
        if index == 0:
            media.append(InputMediaPhoto(media=photo, caption=full_text, parse_mode="HTML"))
        else:
            media.append(InputMediaPhoto(media=photo))

    await message.answer_media_group(media=media)


@router.message(Command("force_send"))
async def force_send_handler(message: Message) -> None:
    if message.from_user:
        add_subscriber(message.from_user.id)
    await send_weekly_races(bot=message.bot, force=True)
    await message.answer("Weekly update sent.", parse_mode="HTML")
