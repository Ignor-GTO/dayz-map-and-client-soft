import asyncio
import io
import threading
import uuid  # noqa: F401 — required by winrt in PyInstaller builds

from PIL import Image

_ocr_loop: asyncio.AbstractEventLoop | None = None
_ocr_thread: threading.Thread | None = None
_ocr_lock = threading.Lock()


def _ensure_ocr_loop() -> asyncio.AbstractEventLoop:
    global _ocr_loop, _ocr_thread
    with _ocr_lock:
        if _ocr_loop is None or not _ocr_loop.is_running():
            ready = threading.Event()

            def run_loop() -> None:
                global _ocr_loop
                _ocr_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(_ocr_loop)
                ready.set()
                _ocr_loop.run_forever()

            _ocr_thread = threading.Thread(target=run_loop, name="ocr-loop", daemon=True)
            _ocr_thread.start()
            ready.wait(timeout=5)
            if _ocr_loop is None:
                raise RuntimeError("Failed to start OCR event loop")
    return _ocr_loop


def recognize_text(image: Image.Image) -> str:
    try:
        loop = _ensure_ocr_loop()
        future = asyncio.run_coroutine_threadsafe(_recognize_async(image), loop)
        return future.result(timeout=30)
    except Exception as exc:
        raise RuntimeError(f"Windows OCR error: {exc}") from exc


async def _recognize_async(image: Image.Image) -> str:
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="BMP")
    raw = buf.getvalue()

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(raw)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)

    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        from winrt.windows.globalization import Language

        engine = OcrEngine.try_create_from_language(Language("en"))
    if engine is None:
        raise RuntimeError("Windows OCR engine unavailable")

    result = await engine.recognize_async(bitmap)
    return "\n".join(line.text for line in result.lines)
