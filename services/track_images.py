import re
from pathlib import Path

TRACKS_DIR = Path(__file__).resolve().parents[1] / "assets" / "tracks"
REMOVED_WORDS = ("international speedway", "circuit")


def normalize(track_name: str) -> str:
    value = track_name.lower().strip()
    for word in REMOVED_WORDS:
        value = value.replace(word, "")
    value = re.sub(r"[^a-z0-9\s-]+", "", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-")


def _load_track_files() -> list[Path]:
    if not TRACKS_DIR.exists():
        return []
    return [path for path in TRACKS_DIR.iterdir() if path.is_file()]


def find_track_image(track_name: str) -> str | None:
    files = _load_track_files()
    if not files:
        return None

    normalized_track = normalize(track_name)
    if not normalized_track:
        return None

    normalized_files: list[tuple[str, Path]] = []
    for path in files:
        stem = path.stem.lower().replace("_", "-")
        stem = re.sub(r"[^a-z0-9-]+", "", stem)
        normalized_files.append((stem, path))

    for stem, path in normalized_files:
        if stem == normalized_track:
            return str(path)

    for stem, path in normalized_files:
        if normalized_track in stem or stem in normalized_track:
            return str(path)

    return None
