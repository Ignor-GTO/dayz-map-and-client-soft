import sys
import asyncio
import io
from PIL import Image

sys.path.append(r"d:\projects\dayz_map_and_client_soft\client")

from ocr_preprocess import preprocess_variants

img_path = r"C:\Users\IgnorGTO\.gemini\antigravity-ide\brain\c037bc71-8081-40c5-b6d1-bcb7f310edfc\media__1781988880038.png"
img = Image.open(img_path)

async def test_winrt():
    try:
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
        
        print("Imported WinRT successfully!")
        
        engine = None
        for tag in ["ru-RU", "ru", "en-US", "en"]:
            try:
                lang = Language(tag)
                if OcrEngine.is_language_supported(lang):
                    engine = OcrEngine.try_create_from_language(lang)
                    if engine is not None:
                        print(f"Created engine for: {tag}")
                        break
            except Exception as e:
                print(f"Failed tag {tag}: {e}")
                
        if engine is None:
            print("Failed to create OcrEngine for any fallback tag")
            return
            
        # Test OCR on all preprocess variants
        variants = preprocess_variants(img)
        for i, var in enumerate(variants):
            buf = io.BytesIO()
            var.convert("RGB").save(buf, format="BMP")
            raw = buf.getvalue()

            stream = InMemoryRandomAccessStream()
            writer = DataWriter(stream)
            writer.write_bytes(raw)
            await writer.store_async()
            await writer.flush_async()
            stream.seek(0)

            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()

            result = await engine.recognize_async(bitmap)
            lines = [line.text for line in result.lines]
            print(f"Variant {i} text: {lines}")
            
    except Exception as e:
        print("Exception in WinRT test:", e)

asyncio.run(test_winrt())
