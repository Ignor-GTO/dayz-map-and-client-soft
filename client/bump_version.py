"""Bump client semver patch version (used in CI before each release build)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION_FILE = ROOT / "VERSION"
VERSION_PY = ROOT / "version.py"
_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def read_version() -> str:
    text = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not _PATTERN.match(text):
        raise ValueError(f"Invalid version in {VERSION_FILE}: {text!r}")
    return text


def write_version(version: str) -> None:
    if not _PATTERN.match(version):
        raise ValueError(f"Invalid version: {version!r}")
    VERSION_FILE.write_text(version + "\n", encoding="utf-8")
    VERSION_PY.write_text(f'__version__ = "{version}"\n', encoding="utf-8")


def bump_patch() -> str:
    major, minor, patch = read_version().split(".")
    version = f"{major}.{minor}.{int(patch) + 1}"
    write_version(version)
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump DayZ Map Client version")
    parser.add_argument("--bump", action="store_true", help="Increment patch version")
    parser.add_argument("--set", metavar="X.Y.Z", help="Set explicit version")
    args = parser.parse_args()

    if args.set:
        write_version(args.set)
        print(args.set)
    elif args.bump:
        print(bump_patch())
    else:
        print(read_version())


if __name__ == "__main__":
    main()
