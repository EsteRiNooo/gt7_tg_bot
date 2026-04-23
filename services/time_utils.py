from datetime import datetime


def get_starts_in_minutes(now: datetime, start: datetime) -> int:
    return int((start - now).total_seconds() // 60)


def get_interval_minutes(times: list[datetime]) -> int | None:
    if len(times) < 2:
        return None
    return int((times[1] - times[0]).total_seconds() // 60)


def get_next_start(times: list[datetime], now: datetime) -> datetime:
    future = [t for t in times if t >= now]
    if future:
        return future[0]
    return times[0]


def format_minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60
    mins = minutes % 60

    if hours < 24:
        return f"{hours}h{mins}m" if mins else f"{hours}h"

    days = hours // 24
    hours = hours % 24

    if mins:
        return f"{days}d{hours}h{mins}m"
    if hours:
        return f"{days}d{hours}h"
    return f"{days}d"


def format_starts_in(minutes: int) -> str:
    if minutes <= 0:
        return "now"
    return format_minutes(minutes)
