import asyncio
import io

from PIL import Image


def recognize_text(image: Image.Image) -> str:
    try:
        return asyncio.run(_recognize_async(image))
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
