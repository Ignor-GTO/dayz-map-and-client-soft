import asyncio
import io
import threading
import uuid  # noqa: F401 — required by winrt in PyInstaller builds

try:
    import winrt.windows.foundation.collections  # noqa: F401 — PyInstaller
except ImportError:
    pass

from PIL import Image

_ocr_loop: asyncio.AbstractEventLoop | None = None
_ocr_thread: threading.Thread | None = None
_ocr_lock = threading.Lock()
_engine = None
_engine_lock = threading.Lock()

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
    langs = ", ".join(installed) if installed else "нет"
    return (
        "Windows OCR недоступен — не установлен языковой пакет распознавания.\n\n"
        "1. Параметры → Время и язык → Язык и регион\n"
        "2. Нажмите «Русский» → «Языковые параметры»\n"
        "3. Скачайте «Оптическое распознавание символов» (OCR)\n\n"
        "Для английского: English → Language options → Optical character recognition.\n"
        "После загрузки перезапустите клиент и нажмите «Проверка OCR».\n\n"
        f"Установленные OCR-языки: {langs}"
    )


def open_ocr_language_settings() -> None:
    import os

    os.startfile("ms-settings:regionlanguage")


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


def list_ocr_languages() -> list[str]:
    try:
        from winrt.windows.media.ocr import OcrEngine

        langs = _iter_recognizer_languages(OcrEngine)
        return [lang.language_tag for lang in langs]
    except Exception:
        return []


def _iter_recognizer_languages(OcrEngine):
    if hasattr(OcrEngine, "get_available_recognizer_languages"):
        return list(OcrEngine.get_available_recognizer_languages())
    return list(OcrEngine.available_recognizer_languages)


def _create_ocr_engine():
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

    installed = list_ocr_languages()
    raise RuntimeError(ocr_setup_message(installed))


def get_ocr_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = _create_ocr_engine()
        return _engine


def recognize_text(image: Image.Image) -> str:
    try:
        loop = _ensure_ocr_loop()
        future = asyncio.run_coroutine_threadsafe(_recognize_async(image), loop)
        return future.result(timeout=30)
    except Exception as exc:
        raise RuntimeError(f"Windows OCR error: {exc}") from exc


async def _recognize_async(image: Image.Image) -> str:
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
