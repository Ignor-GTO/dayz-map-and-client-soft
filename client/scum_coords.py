"""Parse SCUM clipboard coordinates: {X=... Y=... Z=...|P=...}."""

from __future__ import annotations

import re

_SCUM_XY = re.compile(
    r"X\s*=\s*(-?\d+(?:[.,]\d+)?)\s*Y\s*=\s*(-?\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)


def parse_scum_clipboard(text: str | None) -> tuple[float, float] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    match = _SCUM_XY.search(raw.replace(",", "."))
    if not match:
        return None
    try:
        x = float(match.group(1))
        y = float(match.group(2))
    except ValueError:
        return None
    if abs(x) > 2_000_000 or abs(y) > 2_000_000:
        return None
    return x, y
