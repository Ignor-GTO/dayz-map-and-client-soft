"""Radiation editor overlay image storage (persisted in DATA_DIR volume)."""

from __future__ import annotations

import io
import logging
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

OVERLAY_DIR = DATA_DIR / "uploads" / "radiation"
LEGACY_OVERLAY_DIR = Path(__file__).resolve().parent.parent / "static" / "data" / "radiation"

EXT_FALLBACK = {
    ".jpg": ".jpg",
    ".jpeg": ".jpg",
    ".png": ".png",
    ".webp": ".webp",
    ".gif": ".gif",
    ".bmp": ".bmp",
    ".tif": ".tif",
    ".tiff": ".tif",
}
MAX_BYTES = 20 * 1024 * 1024


def ensure_overlay_dir() -> Path:
    OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
    return OVERLAY_DIR


def overlay_public_url(filename: str) -> str:
    return f"/uploads/radiation/{filename}"


def overlay_local_path_from_url(url: str | None) -> Path | None:
    if not url:
        return None
    if url.startswith("/uploads/radiation/"):
        name = url.removeprefix("/uploads/radiation/").split("?")[0]
        if ".." in name or "/" in name:
            return None
        return OVERLAY_DIR / name
    if url.startswith("/data/radiation/"):
        name = url.removeprefix("/data/radiation/").split("?")[0]
        if ".." in name or "/" in name:
            return None
        legacy = LEGACY_OVERLAY_DIR / name
        return legacy if legacy.is_file() else None
    return None


def delete_overlay_file(slug: str) -> None:
    ensure_overlay_dir()
    for path in OVERLAY_DIR.glob(f"{slug}.*"):
        if path.is_file():
            path.unlink(missing_ok=True)
    if LEGACY_OVERLAY_DIR.is_dir():
        for path in LEGACY_OVERLAY_DIR.glob(f"{slug}.*"):
            if path.is_file():
                path.unlink(missing_ok=True)


def _ext_from_filename(filename: str | None) -> str:
    if not filename:
        return ".png"
    lower = filename.lower()
    for ext in EXT_FALLBACK:
        if lower.endswith(ext):
            return EXT_FALLBACK[ext]
    return ".png"


async def save_radiation_overlay(slug: str, file: UploadFile) -> str:
    raw = await file.read()
    filename = file.filename or "overlay"
    declared = (file.content_type or "").split(";")[0].strip().lower()

    if not raw:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Файл слишком большой (макс. 20 МБ)")

    delete_overlay_file(slug)
    ensure_overlay_dir()

    out_name = f"{slug}.webp"
    out_path = OVERLAY_DIR / out_name

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        img.load()
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        img.save(out_path, format="WEBP", quality=88)
        return overlay_public_url(out_name)
    except ImportError:
        logger.warning("Pillow unavailable, saving radiation overlay as original bytes")
    except Exception as exc:
        logger.warning("Radiation overlay decode failed for %s (%s): %s", slug, filename, exc)
        hint = ""
        lower = filename.lower()
        if declared in ("image/heic", "image/heif") or lower.endswith((".heic", ".heif")):
            hint = " HEIC не поддерживается — сохраните как PNG или JPG."
        raise HTTPException(
            status_code=400,
            detail=f"Не удалось прочитать изображение «{filename}» ({declared or 'тип не указан'}).{hint}",
        ) from exc

    ext = _ext_from_filename(filename)
    out_name = f"{slug}_{uuid.uuid4().hex[:8]}{ext}"
    out_path = OVERLAY_DIR / out_name
    out_path.write_bytes(raw)
    return overlay_public_url(out_name)
