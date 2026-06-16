"""Radiation editor overlay image storage (admin alignment background)."""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
OVERLAY_DIR = STATIC_DIR / "data" / "radiation"

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


def overlay_public_url(slug: str, ext: str = ".webp") -> str:
    return f"/data/radiation/{slug}{ext}"


def overlay_local_path(slug: str) -> Path | None:
    ensure_overlay_dir()
    for ext in (".webp", ".png", ".jpg", ".jpeg", ".gif"):
        path = OVERLAY_DIR / f"{slug}{ext}"
        if path.is_file():
            return path
    return None


def delete_overlay_file(slug: str) -> None:
    ensure_overlay_dir()
    for path in OVERLAY_DIR.glob(f"{slug}.*"):
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

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        out_path = OVERLAY_DIR / f"{slug}.webp"
        img.save(out_path, format="WEBP", quality=88)
        return overlay_public_url(slug, ".webp")
    except Exception as exc:
        ext = ALLOWED_CONTENT_TYPES[file.content_type]
        out_name = f"{slug}_{uuid.uuid4().hex[:8]}{ext}"
        out_path = OVERLAY_DIR / out_name
        out_path.write_bytes(raw)
        return f"/data/radiation/{out_name}"
