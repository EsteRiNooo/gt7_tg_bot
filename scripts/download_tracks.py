import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from utils.file_guard import safe_write

TRACK_LIST_URL = "https://gran-turismo.fandom.com/wiki/Gran_Turismo_7/Track_List"
ASSETS_DIR = Path("assets/tracks")
MAPPING_FILE = Path("assets/tracks_mapping.py")
REQUEST_TIMEOUT_SECONDS = 15

LAYOUT_WORDS = (
    "full course",
    "short course",
    "east",
    "west",
    "north",
    "south",
    "reverse",
    "layout",
    "clockwise",
    "counterclockwise",
)


def normalize_filename(track_name: str) -> str:
    value = track_name.lower()
    value = re.sub(r"[^a-z0-9\s]+", "", value)
    value = re.sub(r"\s+", "_", value).strip("_")
    return f"{value}.png"


def to_base_track_name(name: str) -> str:
    value = re.sub(r"\(.*?\)", "", name).strip()
    value = re.sub(r"\s*[-:]\s*(full course|short course|east|west|north|south|reverse).*", "", value, flags=re.IGNORECASE).strip()
    return value


def looks_like_layout(name: str) -> bool:
    lowered = name.lower()
    return any(word in lowered for word in LAYOUT_WORDS)


def extract_track_name(row: BeautifulSoup) -> str | None:
    cell = row.find("th") or row.find("td")
    if cell is None:
        return None

    name = cell.get_text(" ", strip=True)
    if not name:
        return None

    name = re.sub(r"\s+", " ", name).strip()
    return name


def extract_image_url(row: BeautifulSoup) -> str | None:
    img = row.find("img")
    if img is None:
        return None

    src = img.get("data-src") or img.get("src")
    if not src:
        return None

    if src.startswith("data:"):
        return None

    return urljoin(TRACK_LIST_URL, src)


def download_image(session: requests.Session, image_url: str, target_path: Path) -> bool:
    try:
        response = session.get(image_url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"Skip image download (error): {image_url} -> {error}")
        return False

    try:
        target_path.write_bytes(response.content)
    except OSError as error:
        print(f"Skip image write (error): {target_path} -> {error}")
        return False

    return True


def save_mapping(mapping: dict[str, str]) -> None:
    lines = ["TRACK_IMAGES = {"]
    for track_name, path in sorted(mapping.items(), key=lambda item: item[0].lower()):
        lines.append(f'    "{track_name}": "{path}",')
    lines.append("}")
    lines.append("")
    payload = "\n".join(lines).encode("utf-8")
    safe_write(str(MAPPING_FILE), payload)


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    try:
        response = session.get(TRACK_LIST_URL, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"Failed to fetch track list page: {error}")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.select("table.wikitable tr")

    mapping: dict[str, str] = {}
    skipped: list[str] = []

    for row in rows:
        raw_name = extract_track_name(row)
        if raw_name is None:
            continue

        base_name = to_base_track_name(raw_name)
        if not base_name:
            skipped.append(raw_name)
            continue

        if looks_like_layout(raw_name):
            skipped.append(raw_name)
            continue

        if base_name in mapping:
            continue

        image_url = extract_image_url(row)
        if image_url is None:
            skipped.append(base_name)
            continue

        filename = normalize_filename(base_name)
        local_path = ASSETS_DIR / filename

        if not download_image(session, image_url, local_path):
            skipped.append(base_name)
            continue

        mapping[base_name] = str(local_path).replace("\\", "/")

    save_mapping(mapping)

    print(f"Downloaded tracks count: {len(mapping)}")
    print(f"Skipped tracks: {len(skipped)}")
    if skipped:
        print("Skipped list:")
        for name in skipped:
            print(f"- {name}")


if __name__ == "__main__":
    main()
