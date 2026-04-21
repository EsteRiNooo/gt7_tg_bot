from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, InputMediaPhoto, Message

from scheduler import send_weekly_races
from services.formatting import format_full_week, format_requirements_lines, get_week_range
from services.lfm_series_cards import build_lfm_simulation_messages
from services.races import get_all_races
from services.subscribers import add_subscriber
from services.track_images import find_track_image

router = Router()


def _ordered_races(races: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    race_order = {"Race A": 0, "Race B": 1, "Race C": 2}
    return sorted(races, key=lambda race: race_order.get((race.get("title") or "").strip(), 99))


def _format_gt7_message(races: list[dict[str, str | None]]) -> str:
    full_text = format_full_week(races)
    lines = full_text.splitlines()
    details = lines[3:] if len(lines) >= 3 else []
    gt7_header = [
        "#GT7",
        "🏁 <b>GT7 Weekly Races</b>",
        f"📅 <i>{get_week_range()}</i>",
        "",
    ]
    return "\n".join(gt7_header + details).rstrip()


def _format_lmu_message(races: list[dict[str, str | None]]) -> str:
    lines = ["#LMU", "🏁 Le Mans Ultimate", "📅 Daily & Weekly", ""]

    for index, race in enumerate(races[:5]):
        title = (race.get("title") or "Daily Race").strip()
        track = (race.get("track") or "Unknown track").strip()
        race_class = (race.get("class") or "Unknown class").strip()
        duration = (race.get("duration") or "Unknown").strip()
        next_in = race.get("next_start_in")
        interval = race.get("interval")

        block = [
            f"🏁 {title}",
            f"📍 {track}",
            f"🏎 {race_class}",
            f"⏱ {duration} min",
        ]
        if next_in:
            block.append(f"Starts in: {next_in}")
        if interval:
            block.append(f"Every: {interval}")
        lines.extend(block)
        lines.extend(format_requirements_lines(race, html=False))
        if index < len(races[:5]) - 1:
            lines.extend(["", "──────────", ""])

    return "\n".join(lines).rstrip()


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
    results = await get_all_races()
    gt7_source = next((item for item in results if item.get("source") == "gt7"), None)
    lmu_source = next((item for item in results if item.get("source") == "lmu_official"), None)

    gt7_races = gt7_source.get("data") if gt7_source and gt7_source.get("data") else []
    gt7_races = _ordered_races(gt7_races)
    gt7_text = _format_gt7_message(gt7_races)

    image_paths = [find_track_image((race.get("track") or "").strip()) for race in gt7_races]
    valid_image_paths = [path for path in image_paths if path]

    if not valid_image_paths:
        await message.answer(gt7_text, parse_mode="HTML")
    else:
        media: list[InputMediaPhoto] = []
        for index, path in enumerate(valid_image_paths):
            photo = FSInputFile(path)
            if index == 0:
                media.append(InputMediaPhoto(media=photo, caption=gt7_text, parse_mode="HTML"))
            else:
                media.append(InputMediaPhoto(media=photo))

        await message.answer_media_group(media=media)

    lmu_races = lmu_source.get("data") if lmu_source and lmu_source.get("data") else []
    if lmu_races:
        lmu_text = _format_lmu_message(lmu_races)
        await message.answer(lmu_text)

    lfm_source = next((item for item in results if item.get("source") == "lfm"), None)
    lfm_flat = lfm_source.get("data") if lfm_source and lfm_source.get("data") else []
    for lfm_block in build_lfm_simulation_messages(lfm_flat):
        await message.answer(lfm_block)


@router.message(Command("force_send"))
async def force_send_handler(message: Message) -> None:
    if message.from_user:
        add_subscriber(message.from_user.id)
    await send_weekly_races(bot=message.bot, force=True)
    await message.answer("Weekly update sent.", parse_mode="HTML")
