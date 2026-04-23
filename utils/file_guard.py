from __future__ import annotations

import os


def assert_no_null_bytes(content: bytes, path: str) -> None:
    print(f"[FILE GUARD] Checking {path}")
    if b"\x00" in content:
        raise RuntimeError(f"NULL BYTES DETECTED in {path}")


def safe_write(path: str, content: bytes) -> None:
    assert_no_null_bytes(content, path)
    with open(path, "wb") as file:
        file.write(content)


def validate_python_files(root: str = ".") -> None:
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            with open(path, "rb") as file:
                content = file.read()
            assert_no_null_bytes(content, path)
