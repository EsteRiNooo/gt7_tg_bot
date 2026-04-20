import re

import requests
from bs4 import BeautifulSoup

DAILIES_URL = "https://www.dg-edge.com/events/dailies"
REQUEST_TIMEOUT_SECONDS = 10
DATE_RANGE_RE = re.compile(
    r"\d{1,2}\s+[A-Za-z]+\s+\d{4}\s*-\s*\d{1,2}\s+[A-Za-z]+\s+\d{4}"
)

def is_single_car(car: str) -> bool:
    value = car.lower()
    blocked_tokens = ("gr.", "cars", "group", "multiple")
    return not any(token in value for token in blocked_tokens)


def _fallback_races() -> list[dict[str, str | int | None]]:
    return [
        {
            "title": "Race A",
            "track": "Tsukuba",
            "class": "Road Cars",
            "car": None,
            "tires": None,
            "laps": None,
        },
        {
            "title": "Race B",
            "track": "Spa",
            "class": "Gr.4",
            "car": None,
            "tires": None,
            "laps": None,
        },
        {
            "title": "Race C",
            "track": "Suzuka",
            "class": "Gr.3",
            "car": None,
            "tires": None,
            "laps": None,
        },
    ]


def get_current_races() -> list[dict[str, str | int | None]]:
    print("=== FETCHING REAL DATA ===")

    try:
        response = requests.get(
            DAILIES_URL,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        response.raise_for_status()
        print("Status code:", response.status_code)
        print(response.text[:1000])
    except requests.RequestException as e:
        print("Request error:", e)
        print("FALLBACK TRIGGERED")
        return _fallback_races()

    try:
        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select('a[href^="/events/dailies/"]')
        print("Found race cards:", len(cards))
        if len(cards) == 0:
            print("No race cards found. Selectors likely incorrect.")

        races: list[dict[str, str | int | None]] = []
        seen_titles: set[str] = set()

        for card in cards:
            card_text = " ".join(card.stripped_strings).strip()
            title_match = re.search(r"Daily\s*([ABC])", card_text, flags=re.IGNORECASE)
            if title_match is None:
                continue

            title = f"Race {title_match.group(1).upper()}"
            if title in seen_titles:
                continue

            href = card.get("href", "")
            if not href:
                continue

            detail_url = f"https://www.dg-edge.com{href}"
            detail_response = requests.get(
                detail_url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                },
            )
            detail_response.raise_for_status()
            detail_soup = BeautifulSoup(detail_response.text, "html.parser")

            track_node = detail_soup.find("h2")
            track = track_node.get_text(strip=True) if track_node else "Unknown track"

            bop_link = detail_soup.select_one('a[href^="/database/bop/"]')
            if bop_link:
                class_match = re.search(r"(GR\.\d)", bop_link.get_text(" ", strip=True))
                car_class = class_match.group(1) if class_match else "Unknown class"
            else:
                car_class = "Road Cars"

            car_name: str | None = None
            tires: str | None = None
            laps: int | None = None
            text_lines = [line.strip() for line in detail_soup.stripped_strings if line.strip()]

            laps_icon = detail_soup.select_one("svg.fa-flag-checkered")
            if laps_icon is not None and laps_icon.parent is not None:
                laps_text = laps_icon.parent.get_text(" ", strip=True)
                laps_match = re.search(r"\b(\d+)\b", laps_text)
                if laps_match:
                    try:
                        laps = int(laps_match.group(1))
                    except ValueError:
                        laps = None

            date_index = next(
                (i for i, line in enumerate(text_lines) if DATE_RANGE_RE.search(line)),
                -1,
            )
            if date_index > 0:
                candidate = text_lines[date_index - 1]
                is_tire_compound = re.fullmatch(r"[A-Z]{2,3}", candidate) is not None
                if (
                    candidate != track
                    and not is_tire_compound
                    and "daily" not in candidate.lower()
                    and "week" not in candidate.lower()
                ):
                    car_name = candidate

                for line in text_lines[date_index + 1 :]:
                    line_clean = re.sub(r"\s+", " ", line).strip()
                    tire_tokens = re.findall(r"\b[SCRMH]{2}\b", line_clean)
                    if not tire_tokens:
                        continue
                    if tires is None:
                        tires = " / ".join(tire_tokens)

            races.append(
                {
                    "title": title,
                    "track": track,
                    "class": car_class,
                    "car": car_name,
                    "tires": tires,
                    "laps": laps,
                }
            )
            seen_titles.add(title)

            if len(races) == 3:
                break

        if len(races) == 3:
            race_order = {"Race A": 0, "Race B": 1, "Race C": 2}
            races.sort(key=lambda race: race_order.get((race.get("title") or ""), 99))
            return races

        print("FALLBACK TRIGGERED")
        return _fallback_races()
    except Exception as e:
        print("Parsing error:", e)
        print("FALLBACK TRIGGERED")
        return _fallback_races()
