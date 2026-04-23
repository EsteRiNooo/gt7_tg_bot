import os
import sys


def find_null_byte_files(root: str = ".") -> list[str]:
    bad: list[str] = []
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            with open(path, "rb") as file:
                content = file.read()
            if b"\x00" in content:
                bad.append(path)
    return bad


def main() -> int:
    bad_files = find_null_byte_files(".")
    if not bad_files:
        print("OK: no null bytes found in Python files.")
        return 0

    print("ERROR: null bytes found in Python files:")
    for path in bad_files:
        print(path)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
