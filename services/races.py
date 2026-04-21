from services.parsers.gt7 import GT7Parser
from services.parsers.lfm import LFMParser
from services.parsers.lmu_official import LMUOfficialParser
from services.races_logging import ensure_races_logging_configured

# Unified normalized race dict (from parsers) includes:
#   requirements: dict | None  — optional eligibility fields (e.g. safety, license); default None


async def get_all_races() -> list[dict]:
    ensure_races_logging_configured()
    parsers = [
        GT7Parser(),
        LMUOfficialParser(),
        LFMParser(),
    ]

    results = []

    for parser in parsers:
        try:
            data = await parser.get_races()
            results.append({"source": parser.name, "data": data, "error": None})
        except Exception as error:
            results.append({"source": parser.name, "data": None, "error": str(error)})

    return results


async def get_current_races_with_errors() -> tuple[
    list[dict[str, str | int | None]], list[dict[str, str]]
]:
    results = await get_all_races()
    valid_sources = [result for result in results if result["data"] is not None]
    errors = [
        {
            "source": str(result["source"]),
            "error": str(result["error"]),
        }
        for result in results
        if result["error"]
    ]

    gt7_source = next((result for result in valid_sources if result["source"] == "gt7"), None)
    if gt7_source is not None:
        return gt7_source["data"], errors

    if valid_sources:
        return valid_sources[0]["data"], errors

    return [], errors


async def get_current_races() -> list[dict[str, str | int | None]]:
    races, _ = await get_current_races_with_errors()
    return races
