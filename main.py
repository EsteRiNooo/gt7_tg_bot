import asyncio
from pathlib import Path

from aiogram import Bot, Dispatcher

from services.races_logging import ensure_races_logging_configured
from utils.file_guard import validate_python_files

from config import BOT_TOKEN
from scheduler import create_scheduler


def validate_project() -> None:
    validate_python_files(str(Path(__file__).resolve().parent))


validate_project()

from bot.handlers import router


async def main() -> None:
    ensure_races_logging_configured()
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise ValueError("Set your Telegram bot token in config.py")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    scheduler = create_scheduler(bot)
    scheduler.start()

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
