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

CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/pjpeg": ".jpg",
    "image/png": ".png",
    "image/x-png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_BYTES = 12 * 1024 * 1024


def ensure_overlay_dir() -> Path:
    OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
    return OVERLAY_DIR


def overlay_public_url(filename: str) -> str:
    return f"/uploads/radiation/{filename}"


def overlay_local_path_from_url(url: str | None) -> Path | None:
    if not url:
        return None
    if url.startswith("/uploads/radiation/"):
        name = url.removeprefix("/uploads/radiation/")
        if ".." in name or "/" in name:
            return None
        return OVERLAY_DIR / name
    if url.startswith("/data/radiation/"):
        name = url.removeprefix("/data/radiation/")
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


def _ext_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    lower = filename.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if lower.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return None


def _detect_image_type(raw: bytes, file: UploadFile) -> str:
    declared = (file.content_type or "").split(";")[0].strip().lower()
    if declared in CONTENT_TYPE_EXT:
        return declared

    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"

    ext = _ext_from_filename(file.filename)
    if ext == ".png":
        return "image/png"
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".webp":
        return "image/webp"
    if ext == ".gif":
        return "image/gif"

    if declared in ("", "application/octet-stream", "binary/octet-stream"):
        raise HTTPException(
            status_code=400,
            detail="Не удалось определить тип изображения. Используйте PNG, JPG, WEBP или GIF.",
        )

    raise HTTPException(
        status_code=400,
        detail=f"Неподдерживаемый тип файла: {declared or 'unknown'}",
    )


async def save_radiation_overlay(slug: str, file: UploadFile) -> str:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Файл слишком большой (макс. 12 МБ)")

    content_type = _detect_image_type(raw, file)
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
        logger.warning("WEBP convert failed for %s: %s", slug, exc)

    ext = CONTENT_TYPE_EXT.get(content_type) or _ext_from_filename(file.filename) or ".png"
    out_name = f"{slug}_{uuid.uuid4().hex[:8]}{ext}"
    out_path = OVERLAY_DIR / out_name
    out_path.write_bytes(raw)
    return overlay_public_url(out_name)
