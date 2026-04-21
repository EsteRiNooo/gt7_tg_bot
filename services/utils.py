def is_single_car(race: dict | str | list | None) -> bool:
    if isinstance(race, dict):
        car = race.get("car")
    else:
        car = race

    if not car:
        return False

    if isinstance(car, str):
        return True

    if isinstance(car, list) and len(car) == 1:
        return True

    return False
