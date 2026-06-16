import re

from PIL import Image

# iZurvive: "15100 / 879", "15100 - 879", snip "15100-879"
_COORD_SEP = re.compile(r"(\d{2,6})\s*[/\-–—]\s*(\d{1,6})")
_DIGITS = re.compile(r"\d+")


def _valid_coord(x: float, y: float) -> bool:
    return 0 <= x <= 20480 and 0 <= y <= 20480


def parse_coordinates(text: str) -> tuple[float, float] | None:
    cleaned = (
        text.replace(",", ".")
        .replace("O", "0")
        .replace("o", "0")
        .replace("l", "1")
        .replace("I", "1")
        .replace("|", "1")
        .replace("S", "5")
        .replace("s", "5")
    )
    best: tuple[float, float] | None = None
    best_score = -1

    for match in _COORD_SEP.finditer(cleaned):
        xs, ys = match.group(1), match.group(2)
        x, y = float(xs), float(ys)
        if not _valid_coord(x, y):
            continue
        score = len(xs) * 10 + len(ys) * 10
        # DayZ player strip: X and Y are usually 4–5 digits; short Y after long X = truncation.
        if len(xs) >= 4:
            if len(ys) < 4:
                score -= 25 * (4 - len(ys))
            if y < 500:
                score -= 20
        if score > best_score:
            best_score = score
            best = (x, y)

    if best is not None:
        return best

    numbers = _DIGITS.findall(cleaned)
    if len(numbers) >= 2:
        x, y = float(numbers[-2]), float(numbers[-1])
        if _valid_coord(x, y):
            return x, y
    return None


def extract_coordinates(image: Image.Image) -> tuple[float, float] | None:
    coords, _ = extract_coordinates_with_text(image)
    return coords


def extract_coordinates_with_text(image: Image.Image) -> tuple[tuple[float, float] | None, str]:
    from ocr_engine import recognize_text_all

    texts = recognize_text_all(image)
    best_coords: tuple[float, float] | None = None
    best_score = -1
    best_text = ""

    for text in texts:
        coords = parse_coordinates(text)
        if not coords:
            continue
        score = len(str(int(coords[0]))) + len(str(int(coords[1])))
        if score > best_score:
            best_score = score
            best_coords = coords
            best_text = text

    if best_coords:
        return best_coords, best_text
    combined = " | ".join(texts)
    return parse_coordinates(combined), combined
