import re

from PIL import Image

# iZurvive: "15100 / 879", "15100 - 879", snip "15100-879"
_COORD_SEP = re.compile(r"(\d{2,6})\s*[/\-–—]\s*(\d{2,6})")


def parse_coordinates(text: str) -> tuple[float, float] | None:
    cleaned = (
        text.replace(",", ".")
        .replace("O", "0")
        .replace("o", "0")
        .replace("l", "1")
        .replace("I", "1")
        .replace("|", "1")
    )
    match = _COORD_SEP.search(cleaned)
    if match:
        return float(match.group(1)), float(match.group(2))

    numbers = re.findall(r"\d+\.?\d*", cleaned)
    if len(numbers) >= 2:
        return float(numbers[-2]), float(numbers[-1])
    return None


def extract_coordinates(image: Image.Image) -> tuple[float, float] | None:
    coords, _ = extract_coordinates_with_text(image)
    return coords


def extract_coordinates_with_text(image: Image.Image) -> tuple[tuple[float, float] | None, str]:
    from ocr_engine import recognize_text_all

    texts = recognize_text_all(image)
    for text in texts:
        coords = parse_coordinates(text)
        if coords:
            return coords, text
    combined = texts[0] if texts else ""
    return parse_coordinates(combined), combined
