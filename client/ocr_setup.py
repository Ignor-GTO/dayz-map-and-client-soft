"""Windows OCR diagnostics and optional language-pack installation."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

_OCR_CAPABILITY_TAGS = (
    "ru-RU",
    "en-US",
    "en-GB",
    "uk-UA",
    "de-DE",
    "pl-PL",
)


@dataclass
class OcrDiagnostics:
    windows_languages: list[str] = field(default_factory=list)
    ocr_installed: list[str] = field(default_factory=list)
    ocr_missing_for_user_langs: list[str] = field(default_factory=list)
    ocr_capabilities: list[tuple[str, str]] = field(default_factory=list)
    can_use_windows_ocr: bool = False
    capability_query_ok: bool = False


def get_windows_languages() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        from winrt.windows.system.userprofile import GlobalizationPreferences

        return list(GlobalizationPreferences.languages)
    except Exception:
        pass
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-WinUserLanguageList).LanguageTag -join ','",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return [t.strip() for t in proc.stdout.strip().split(",") if t.strip()]
    except Exception:
        pass
    return []


def list_ocr_languages() -> list[str]:
    try:
        from winrt.windows.media.ocr import OcrEngine

        if hasattr(OcrEngine, "get_available_recognizer_languages"):
            langs = list(OcrEngine.get_available_recognizer_languages())
        else:
            langs = list(OcrEngine.available_recognizer_languages)
        return [lang.language_tag for lang in langs]
    except Exception:
        return []


def _query_ocr_capabilities() -> list[tuple[str, str]]:
    if sys.platform != "win32":
        return []
    script = (
        "Get-WindowsCapability -Online | "
        "Where-Object { $_.Name -like 'Language.OCR*' } | "
        "Select-Object Name, State | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        import json

        data = json.loads(proc.stdout)
        if isinstance(data, dict):
            data = [data]
        return [(item.get("Name", ""), item.get("State", "")) for item in data if item.get("Name")]
    except Exception:
        return []


def _missing_ocr_for_user_langs(user_langs: list[str], installed: list[str]) -> list[str]:
    missing: list[str] = []
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
    except Exception:
        return missing

    installed_set = set(installed)
    for tag in user_langs:
        try:
            lang = Language(tag)
            if OcrEngine.is_language_supported(lang) and tag not in installed_set:
                missing.append(tag)
        except Exception:
            continue
    return missing


def diagnose() -> OcrDiagnostics:
    windows_langs = get_windows_languages()
    ocr_installed = list_ocr_languages()
    capabilities = _query_ocr_capabilities()
    missing = _missing_ocr_for_user_langs(windows_langs, ocr_installed)
    return OcrDiagnostics(
        windows_languages=windows_langs,
        ocr_installed=ocr_installed,
        ocr_missing_for_user_langs=missing,
        ocr_capabilities=capabilities,
        can_use_windows_ocr=bool(ocr_installed),
        capability_query_ok=bool(capabilities),
    )


def format_setup_message(diag: OcrDiagnostics | None = None) -> str:
    diag = diag or diagnose()
    lines = [
        "Windows OCR не настроен — языковой пакет распознавания не скачан.",
        "",
        f"Языки Windows: {', '.join(diag.windows_languages) or 'не определены'}",
        f"OCR в системе: {', '.join(diag.ocr_installed) or 'нет'}",
    ]
    if diag.ocr_missing_for_user_langs:
        lines.append(
            "Нужно скачать OCR для: "
            + ", ".join(diag.ocr_missing_for_user_langs)
        )
    lines.extend(
        [
            "",
            "Это отдельный компонент, не путать с языком интерфейса.",
            "",
            "Через Параметры (обычно без админа):",
            "1. Время и язык → Язык и регион",
            "2. Русский → Языковые параметры",
            "3. «Оптическое распознавание символов» → Скачать",
            "",
            "Клиент всё равно работает через встроенный OCR.",
            "Windows OCR быстрее — установите при желании.",
        ]
    )
    return "\n".join(lines)


def open_ocr_language_settings() -> None:
    import os

    os.startfile("ms-settings:regionlanguage")


def _install_tags(diag: OcrDiagnostics) -> list[str]:
    tags = list(diag.ocr_missing_for_user_langs)
    for tag in _OCR_CAPABILITY_TAGS:
        if tag not in tags:
            tags.append(tag)
    return tags[:4]


def install_ocr_packs_admin(diag: OcrDiagnostics | None = None) -> bool:
    """Launch elevated PowerShell to install missing OCR language capabilities."""
    if sys.platform != "win32":
        return False

    diag = diag or diagnose()
    tags = _install_tags(diag)
    tag_list = ", ".join(f'"{t}"' for t in tags)
    script = f"""
$ErrorActionPreference = 'Continue'
$tags = @({tag_list})
Write-Host 'DayZ Map Client — установка OCR' -ForegroundColor Cyan
foreach ($tag in $tags) {{
  $caps = Get-WindowsCapability -Online | Where-Object {{
    $_.Name -like "Language.OCR*$tag*" -and $_.State -ne 'Installed'
  }}
  foreach ($cap in $caps) {{
    Write-Host "Установка $($cap.Name)..." -ForegroundColor Yellow
    $result = $cap | Add-WindowsCapability -Online
    Write-Host $result.RestartNeeded
  }}
}}
Write-Host ''
Write-Host 'Готово. Перезапустите DayZ Map Client и нажмите Проверка OCR.' -ForegroundColor Green
Read-Host 'Enter для закрытия'
"""
    ps1 = Path(tempfile.gettempdir()) / "dayz_map_install_ocr.ps1"
    ps1.write_text(script, encoding="utf-8")

    import ctypes

    params = (
        "-NoProfile -ExecutionPolicy Bypass -File "
        f'"{ps1}"'
    )
    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        "powershell.exe",
        params,
        None,
        1,
    )
    return result > 32
