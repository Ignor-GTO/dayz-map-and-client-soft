"""Radiation editor overlay image storage (persisted in DATA_DIR volume)."""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import DATA_DIR

OVERLAY_DIR = DATA_DIR / "uploads" / "radiation"
LEGACY_OVERLAY_DIR = Path(__file__).resolve().parent.parent / "static" / "data" / "radiation"

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
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


async def save_radiation_overlay(slug: str, file: UploadFile) -> str:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 12 MB)")

    delete_overlay_file(slug)
    ensure_overlay_dir()

    out_name = f"{slug}.webp"
    out_path = OVERLAY_DIR / out_name

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        img.save(out_path, format="WEBP", quality=88)
        return overlay_public_url(out_name)
    except Exception:
        ext = ALLOWED_CONTENT_TYPES[file.content_type]
        out_name = f"{slug}_{uuid.uuid4().hex[:8]}{ext}"
        out_path = OVERLAY_DIR / out_name
        out_path.write_bytes(raw)
        return overlay_public_url(out_name)
