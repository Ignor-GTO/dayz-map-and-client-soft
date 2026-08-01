"""Standalone WebView2 overlay process (dev / non-frozen runs)."""

from __future__ import annotations

import sys

from map_overlay import run_overlay_process


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else ""
    return run_overlay_process(url)


if __name__ == "__main__":
    raise SystemExit(main())
