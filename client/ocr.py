import re

from PIL import Image

# iZurvive: "15100 / 879" or "My X/Y: 15100 / 879"
_COORD_SLASH = re.compile(r"(\d{2,6})\s*/\s*(\d{2,6})")


def parse_coordinates(text: str) -> tuple[float, float] | None:
    cleaned = text.replace(",", ".").replace("O", "0").replace("o", "0")
    match = _COORD_SLASH.search(cleaned)
    if match:
        return float(match.group(1)), float(match.group(2))

    numbers = re.findall(r"\d+\.?\d*", cleaned)
    if len(numbers) >= 2:
        return float(numbers[-2]), float(numbers[-1])
    return None


def extract_coordinates(image: Image.Image) -> tuple[float, float] | None:
    from ocr_engine import recognize_text

    text = recognize_text(image)
    coords = parse_coordinates(text)
    return coords


def extract_coordinates_with_text(image: Image.Image) -> tuple[tuple[float, float] | None, str]:
    from ocr_engine import recognize_text

    text = recognize_text(image)
    return parse_coordinates(text), text
