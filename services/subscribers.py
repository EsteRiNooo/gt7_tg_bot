_subscriber_ids: set[int] = set()


def add_subscriber(user_id: int) -> None:
    _subscriber_ids.add(user_id)


def remove_subscriber(user_id: int) -> None:
    _subscriber_ids.discard(user_id)


def list_subscribers() -> list[int]:
    return list(_subscriber_ids)
