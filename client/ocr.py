import os
import re

import pytesseract
from PIL import Image, ImageEnhance, ImageGrab, ImageOps


def setup_tesseract(path: str) -> None:
    if path and os.path.exists(path):
        pytesseract.pytesseract.tesseract_cmd = path


def preprocess(image: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(image)
    enhanced = ImageEnhance.Contrast(gray).enhance(2.5)
    return enhanced.point(lambda p: 255 if p > 140 else 0)


def extract_coordinates(image: Image.Image) -> tuple[float, float] | None:
    processed = preprocess(image)
    text = pytesseract.image_to_string(
        processed,
        config="--psm 6 --oem 3 -c tessedit_char_whitelist=0123456789.,",
    )
    numbers = re.findall(r"\d+\.?\d*", text.replace(",", "."))
    if len(numbers) >= 2:
        return float(numbers[0]), float(numbers[1])
    return None


def ocr_from_screen(region: tuple[int, int, int, int]) -> tuple[float, float] | None:
    screen = ImageGrab.grab(bbox=region)
    return extract_coordinates(screen)
