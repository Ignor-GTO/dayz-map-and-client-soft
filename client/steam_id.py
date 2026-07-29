"""Detect local Steam account SteamID64 (Windows)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

# SteamID64 = SteamID3 + this constant
_STEAM_ID64_BASE = 76561197960265728

_MOST_RECENT_BLOCK = re.compile(
    r'"(\d{15,20})"\s*\{([^}]*)\}',
    re.IGNORECASE | re.DOTALL,
)
_MOST_RECENT_FLAG = re.compile(r'"MostRecent"\s*"1"', re.IGNORECASE)


def steamid3_to_steamid64(account_id: int) -> str:
    return str(_STEAM_ID64_BASE + int(account_id))


def _steam_install_path() -> Path | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            path, _ = winreg.QueryValueEx(key, "SteamPath")
            p = Path(str(path).replace("/", "\\"))
            if p.is_dir():
                return p
    except Exception:
        pass
    for candidate in (
        Path(r"C:\Program Files (x86)\Steam"),
        Path(r"C:\Program Files\Steam"),
    ):
        if candidate.is_dir():
            return candidate
    return None


def detect_steam_id_from_registry() -> str | None:
    """Active Steam user from HKCU\\Software\\Valve\\Steam\\ActiveProcess\\ActiveUser (SteamID3)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess") as key:
            active_user, _ = winreg.QueryValueEx(key, "ActiveUser")
        account_id = int(active_user)
        if account_id <= 0:
            return None
        return steamid3_to_steamid64(account_id)
    except Exception:
        return None


def detect_steam_id_from_loginusers() -> str | None:
    """MostRecent=1 account from Steam\\config\\loginusers.vdf."""
    steam = _steam_install_path()
    if not steam:
        return None
    vdf = steam / "config" / "loginusers.vdf"
    if not vdf.is_file():
        return None
    try:
        text = vdf.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    most_recent: str | None = None
    fallback: str | None = None
    for match in _MOST_RECENT_BLOCK.finditer(text):
        sid = match.group(1)
        body = match.group(2)
        if not fallback:
            fallback = sid
        if _MOST_RECENT_FLAG.search(body):
            most_recent = sid
            break
    return most_recent or fallback


def detect_local_steam_id() -> tuple[str | None, str]:
    """
    Return (steam_id64, source_label).
    Prefers the currently active Steam session, then MostRecent login.
    """
    sid = detect_steam_id_from_registry()
    if sid:
        return sid, "Steam ActiveProcess"
    sid = detect_steam_id_from_loginusers()
    if sid:
        return sid, "loginusers.vdf"
    return None, "not found"
