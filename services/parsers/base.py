class BaseParser:
    name = "base"

    async def get_races(self) -> list[dict]:
        raise NotImplementedError
