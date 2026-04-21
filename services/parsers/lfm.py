import requests

from services.lfm_scheduler import flatten_lfm_week_events
from services.parsers.base import BaseParser
from services.races_logging import ensure_races_logging_configured, logger

LFM_MINIFIED_SEASON_URL = (
    "https://api3.lowfuelmotorsport.com/api/v2/seasons/getMinifiedSeasonBySim"
)
REQUEST_TIMEOUT_SECONDS = 10
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/115.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class LFMParser(BaseParser):
    name = "lfm"

    async def get_races(self) -> list[dict]:
        return self.get_races_sync()

    def get_races_sync(self) -> list[dict]:
        ensure_races_logging_configured()
        logger.info("[LFM] start parsing")
        try:
            response = requests.get(
                LFM_MINIFIED_SEASON_URL,
                headers=REQUEST_HEADERS,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            logger.info("[LFM] payload received")
            payload = response.json()
        except requests.RequestException as error:
            logger.error(f"[LFM] error: {error}")
            raise
        except ValueError as error:
            logger.error(f"[LFM] error: {error}")
            raise

        if not isinstance(payload, dict):
            logger.info("[LFM] parsed items: 0")
            races = flatten_lfm_week_events({})
            logger.info(f"[LFM] normalized races: {len(races)}")
            if not races:
                logger.warning("[LFM] no races generated")
            return races

        series_root = payload.get("series")
        series_count = 0
        if isinstance(series_root, dict):
            for sim_block in series_root.values():
                if isinstance(sim_block, dict):
                    sl = sim_block.get("series")
                    if isinstance(sl, list):
                        series_count += len(sl)

        logger.info(f"[LFM] parsed items: {series_count}")
        races = flatten_lfm_week_events(payload)
        logger.info(f"[LFM] normalized races: {len(races)}")
        if not races:
            logger.warning("[LFM] no races generated")
        return races
