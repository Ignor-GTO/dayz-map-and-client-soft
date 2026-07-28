"""Parse SCUM clipboard coordinates: {X=... Y=... Z=...|P=...}."""

from __future__ import annotations

import re

# Prefer position X/Y before optional pitch block (|P=... Y=...).
_SCUM_XY = re.compile(
    r"\{?\s*X\s*[=:]\s*(-?\d+(?:[.,]\d+)?)\s*[,;\s]+Y\s*[=:]\s*(-?\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)


def parse_scum_clipboard(text: str | None) -> tuple[float, float] | None:
    """Parse e.g. `{X=-777383.500 Y=-840118.938 Z=10486.375|P=326.487885 Y=27.3 R=0}`."""
    raw = (text or "").strip()
    if not raw:
        return None
    # Normalize NBSP / odd spaces from some paste paths
    normalized = (
        raw.replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace(",", ".")
    )
    match = _SCUM_XY.search(normalized)
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


def looks_like_client_log(text: str | None) -> bool:
    """True when clipboard holds ScumMapClient log instead of SCUM coords."""
    raw = (text or "").strip()
    if not raw:
        return False
    return ("[Клиент]" in raw and "SCUM v" in raw) or (
        raw.startswith("[") and "Права:" in raw and "F1" in raw
    )
