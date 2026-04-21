from services.parsers.gt7 import GT7Parser


async def get_all_races() -> list[dict]:
    parsers = [
        GT7Parser(),
    ]

    results = []

    for parser in parsers:
        try:
            data = await parser.get_races()
            results.append({"source": parser.name, "data": data, "error": None})
        except Exception as error:
            results.append({"source": parser.name, "data": None, "error": str(error)})

    return results


def get_current_races() -> list[dict[str, str | int | None]]:
    return GT7Parser().get_races_sync()
