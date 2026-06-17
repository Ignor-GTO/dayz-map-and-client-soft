"""Read screenshot images from the Windows clipboard (Win+Shift+S / Snipping Tool)."""

from __future__ import annotations

import io
import os
import struct
from pathlib import Path

from PIL import Image, ImageGrab

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


def _open_path(path: str) -> Image.Image | None:
    try:
        p = Path(path)
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTS:
            return Image.open(p).convert("RGB")
    except Exception:
        return None
    return None


def _dib_to_image(dib: bytes) -> Image.Image | None:
    """Convert CF_DIB clipboard bytes to PIL Image."""
    if len(dib) < 40:
        return None
    try:
        header_size = struct.unpack_from("<I", dib, 0)[0]
        if header_size < 40:
            return None
        width = struct.unpack_from("<i", dib, 4)[0]
        height = struct.unpack_from("<i", dib, 8)[0]
        bits = struct.unpack_from("<H", dib, 14)[0]
        if width <= 0 or height <= 0 or bits not in (24, 32):
            return None
        row_bytes = ((width * bits + 31) // 32) * 4
        pixels_offset = header_size
        rows = []
        for row in range(abs(height)):
            start = pixels_offset + row * row_bytes
            end = start + width * (bits // 8)
            chunk = dib[start:end]
            if len(chunk) < width * (bits // 8):
                break
            rows.append(chunk[: width * 3])
        if not rows:
            return None
        if height > 0:
            rows.reverse()
        raw = b"".join(rows)
        return Image.frombytes("RGB", (width, abs(height)), raw)
    except Exception:
        return None


def _grab_dib_clipboard() -> Image.Image | None:
    import sys

    if sys.platform != "win32":
        return None
    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_DIB = 8
    GMEM_MOVEABLE = 0x0002

    if not user32.OpenClipboard(0):
        return None
    try:
        if not user32.IsClipboardFormatAvailable(CF_DIB):
            return None
        handle = user32.GetClipboardData(CF_DIB)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            size = kernel32.GlobalSize(handle)
            data = ctypes.string_at(ptr, size)
            return _dib_to_image(data)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def grab_clipboard_image(retries: int = 6, delay: float = 0.12) -> Image.Image | None:
    """Return RGB image from clipboard or None. Retries for Win+Shift+S lag."""
    import time

    last: Image.Image | None = None
    for attempt in range(max(1, retries)):
        img = _grab_clipboard_image_once()
        if img is not None:
            last = img
            if attempt > 0 or img.size[0] >= 30:
                return img
        if attempt + 1 < retries:
            time.sleep(delay)
    return last


def _grab_clipboard_image_once() -> Image.Image | None:
    """Return RGB image from clipboard or None."""
    try:
        data = ImageGrab.grabclipboard()
        if isinstance(data, Image.Image):
            return data.convert("RGB")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    img = _open_path(item)
                    if img is not None:
                        return img
                elif hasattr(item, "read"):
                    try:
                        return Image.open(item).convert("RGB")
                    except Exception:
                        continue
        if isinstance(data, bytes):
            return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        pass

    dib = _grab_dib_clipboard()
    if dib is not None:
        return dib.convert("RGB")

    png = _grab_png_clipboard()
    if png is not None:
        return png.convert("RGB")

    # Snipping Tool sometimes leaves only a file path in clipboard text.
    try:
        import sys

        if sys.platform == "win32":
            import ctypes

            user32 = ctypes.windll.user32
            CF_UNICODETEXT = 13
            if user32.OpenClipboard(0):
                try:
                    if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                        handle = user32.GetClipboardData(CF_UNICODETEXT)
                        if handle:
                            ptr = ctypes.windll.kernel32.GlobalLock(handle)
                            if ptr:
                                text = ctypes.wstring_at(ptr)
                                ctypes.windll.kernel32.GlobalUnlock(handle)
                                text = text.strip().strip('"')
                                if os.path.isfile(text):
                                    return _open_path(text)
                finally:
                    user32.CloseClipboard()
    except Exception:
        pass

    return None


def _grab_png_clipboard() -> Image.Image | None:
    import sys

    if sys.platform != "win32":
        return None
    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    fmt = user32.RegisterClipboardFormatW("PNG")
    if not fmt:
        return None
    if not user32.OpenClipboard(0):
        return None
    try:
        if not user32.IsClipboardFormatAvailable(fmt):
            return None
        handle = user32.GetClipboardData(fmt)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            size = kernel32.GlobalSize(handle)
            data = ctypes.string_at(ptr, size)
            return Image.open(io.BytesIO(data))
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def grab_clipboard_text() -> str | None:
    import sys

    if sys.platform != "win32":
        return None
    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_UNICODETEXT = 13
    if not user32.OpenClipboard(0):
        return None
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr).strip()
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def prepare_coord_image(img, monitor_index: int, ocr_region: tuple[int, int, int, int]):
    """Use snip as-is when small; only crop huge full-screen captures."""
    from capture import resolve_monitor
    from PIL import Image, ImageOps

    w, h = img.size
    if w <= 0 or h <= 0:
        return img

    mon = resolve_monitor(monitor_index)
    
    # Determine if it's a full-screen capture
    is_fullscreen = False
    if mon:
        if w >= mon.width * 0.9 and h >= mon.height * 0.9:
            is_fullscreen = True
    else:
        # Fallback threshold
        if w >= 1200 and h >= 700:
            is_fullscreen = True

    if is_fullscreen:
        # Full-screen capture: crop the bottom-left HUD coordinates strip
        rh = min(90, max(40, h // 14))
        rw = min(480, max(180, w // 5))
        crop = img.crop((0, max(0, h - rh - 6), rw, h))
        cw, ch = crop.size
        scale = max(3, min(6, 220 // max(ch, 1)))
        if scale > 1:
            crop = crop.resize((cw * scale, ch * scale), Image.Resampling.LANCZOS)
        return ImageOps.autocontrast(crop.convert("RGB"), cutoff=1)

    # Custom snip: process the entire image as-is
    scale = max(3, min(6, 220 // max(h, 1)))
    out = img.convert("RGB")
    if scale > 1:
        out = out.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
    return ImageOps.autocontrast(out, cutoff=1)


def has_clipboard_image() -> bool:
    import sys
    if sys.platform != "win32":
        return False
    import ctypes
    user32 = ctypes.windll.user32
    CF_DIB = 8
    png_fmt = user32.RegisterClipboardFormatW("PNG")
    
    if user32.IsClipboardFormatAvailable(CF_DIB):
        return True
    if png_fmt and user32.IsClipboardFormatAvailable(png_fmt):
        return True
        
    return False
