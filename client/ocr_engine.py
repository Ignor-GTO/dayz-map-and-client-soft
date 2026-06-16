import asyncio
import io
import threading
import uuid  # noqa: F401 — required by winrt in PyInstaller builds

try:
    import winrt.windows.foundation.collections  # noqa: F401 — PyInstaller
except ImportError:
    pass

from PIL import Image

from ocr_fallback import preprocess_coordinate_region, recognize_text as recognize_text_fallback
from ocr_setup import diagnose, format_setup_message, list_ocr_languages, open_ocr_language_settings

_ocr_loop: asyncio.AbstractEventLoop | None = None
_ocr_thread: threading.Thread | None = None
_ocr_lock = threading.Lock()
_windows_engine = None
_engine_lock = threading.Lock()
_backend_name: str | None = None
_use_windows = False

_FALLBACK_LANGS = (
    "ru-RU",
    "ru",
    "en-US",
    "en-GB",
    "en",
    "uk-UA",
    "de-DE",
    "pl-PL",
)


def ocr_setup_message(installed: list[str] | None = None) -> str:
    return format_setup_message()


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


def _iter_recognizer_languages(OcrEngine):
    if hasattr(OcrEngine, "get_available_recognizer_languages"):
        return list(OcrEngine.get_available_recognizer_languages())
    return list(OcrEngine.available_recognizer_languages)


def _create_windows_ocr_engine():
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is not None:
        return engine

    for tag in _FALLBACK_LANGS:
        try:
            lang = Language(tag)
            if OcrEngine.is_language_supported(lang):
                engine = OcrEngine.try_create_from_language(lang)
                if engine is not None:
                    return engine
        except Exception:
            continue

    for lang in _iter_recognizer_languages(OcrEngine):
        try:
            engine = OcrEngine.try_create_from_language(lang)
            if engine is not None:
                return engine
        except Exception:
            continue

    raise RuntimeError(ocr_setup_message(list_ocr_languages()))


def ensure_ocr_backend() -> str:
    """Initialize OCR backend. Windows OCR if available, else bundled fallback."""
    global _windows_engine, _backend_name, _use_windows
    with _engine_lock:
        if _backend_name is not None:
            return _backend_name

        try:
            _windows_engine = _create_windows_ocr_engine()
            tag = _windows_engine.recognizer_language.language_tag
            _backend_name = f"Windows OCR ({tag})"
            _use_windows = True
        except Exception:
            _windows_engine = None
            _backend_name = "встроенный OCR"
            _use_windows = False
        return _backend_name


def get_backend_name() -> str:
    return ensure_ocr_backend()


def uses_windows_ocr() -> bool:
    ensure_ocr_backend()
    return _use_windows


def get_ocr_engine():
    ensure_ocr_backend()
    if not _use_windows or _windows_engine is None:
        raise RuntimeError(ocr_setup_message(list_ocr_languages()))
    return _windows_engine


def get_diagnostics():
    diag = diagnose()
    diag.can_use_windows_ocr = uses_windows_ocr()
    return diag


async def _recognize_windows_async(image: Image.Image) -> str:
    from winrt.windows.graphics.imaging import BitmapDecoder
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

    engine = get_ocr_engine()
    result = await engine.recognize_async(bitmap)
    return "\n".join(line.text for line in result.lines)


def recognize_text(image: Image.Image) -> str:
    prepared = preprocess_coordinate_region(image)
    backend = ensure_ocr_backend()

    if _use_windows:
        try:
            loop = _ensure_ocr_loop()
            future = asyncio.run_coroutine_threadsafe(_recognize_windows_async(prepared), loop)
            return future.result(timeout=30)
        except Exception as exc:
            raise RuntimeError(f"{backend} error: {exc}") from exc

    try:
        return recognize_text_fallback(prepared)
    except Exception as exc:
        raise RuntimeError(f"{backend} error: {exc}") from exc
