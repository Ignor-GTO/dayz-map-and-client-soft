import re

from PIL import Image


def parse_coordinates(text: str) -> tuple[float, float] | None:
    numbers = re.findall(r"\d+\.?\d*", text.replace(",", "."))
    if len(numbers) >= 2:
        return float(numbers[0]), float(numbers[1])
    return None


def extract_coordinates(image: Image.Image) -> tuple[float, float] | None:
    from ocr_engine import recognize_text

    text = recognize_text(image)
    return parse_coordinates(text)
