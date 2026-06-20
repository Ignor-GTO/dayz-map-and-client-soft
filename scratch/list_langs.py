try:
    from winrt.windows.media.ocr import OcrEngine
    print("Available OCR languages:")
    print([l.language_tag for l in OcrEngine.available_recognizer_languages])
except Exception as e:
    print("Error:", e)
