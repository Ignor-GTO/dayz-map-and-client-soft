"""POI description image upload and storage."""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import DATA_DIR

UPLOAD_DIR = DATA_DIR / "uploads" / "poi"
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_BYTES = 5 * 1024 * 1024


def ensure_upload_dir() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR


def _local_path_from_url(url: str | None) -> Path | None:
    if not url or not url.startswith("/uploads/poi/"):
        return None
    name = url.removeprefix("/uploads/poi/")
    if ".." in name or "/" in name:
        return None
    return UPLOAD_DIR / name


def delete_poi_image_file(url: str | None) -> None:
    path = _local_path_from_url(url)
    if path and path.is_file():
        path.unlink(missing_ok=True)


async def save_poi_image(poi_id: int, file: UploadFile) -> str:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 5 MB)")

    ensure_upload_dir()
    out_name = f"{poi_id}_{uuid.uuid4().hex[:12]}.webp"
    out_path = UPLOAD_DIR / out_name

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        max_side = 1200
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if img.mode == "RGBA":
            img.save(out_path, format="WEBP", quality=88, method=4)
        else:
            img.save(out_path, format="WEBP", quality=88, method=4)
    except ImportError:
        ext = ALLOWED_CONTENT_TYPES[file.content_type]
        out_name = f"{poi_id}_{uuid.uuid4().hex[:12]}{ext}"
        out_path = UPLOAD_DIR / out_name
        out_path.write_bytes(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid image file") from exc

    return f"/uploads/poi/{out_name}"
