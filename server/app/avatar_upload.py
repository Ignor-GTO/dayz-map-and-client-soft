"""User profile avatar upload and storage."""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import DATA_DIR

UPLOADS_ROOT = DATA_DIR / "uploads"
AVATAR_UPLOAD_DIR = UPLOADS_ROOT / "avatars"
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_BYTES = 2 * 1024 * 1024  # 2 MB
AVATAR_SIZE = 256


def ensure_avatar_upload_dir() -> Path:
    UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)
    AVATAR_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOADS_ROOT


def _local_path_from_url(url: str | None) -> Path | None:
    if not url or not url.startswith("/uploads/avatars/"):
        return None
    name = url.removeprefix("/uploads/avatars/")
    if ".." in name or "/" in name:
        return None
    return AVATAR_UPLOAD_DIR / name


def delete_avatar_file(url: str | None) -> None:
    path = _local_path_from_url(url)
    if path and path.is_file():
        path.unlink(missing_ok=True)


async def save_avatar_image(user_id: int, file: UploadFile) -> str:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 2 MB)")

    ensure_avatar_upload_dir()
    out_name = f"{user_id}_{uuid.uuid4().hex[:12]}.webp"
    out_path = AVATAR_UPLOAD_DIR / out_name

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        img.thumbnail((AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS)
        img.save(out_path, format="WEBP", quality=85, method=4)
    except ImportError:
        ext = ALLOWED_CONTENT_TYPES[file.content_type]
        out_name = f"{user_id}_{uuid.uuid4().hex[:12]}{ext}"
        out_path = AVATAR_UPLOAD_DIR / out_name
        out_path.write_bytes(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid image file") from exc

    return f"/uploads/avatars/{out_name}"
