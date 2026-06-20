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
    
    matches = list(_DIGITS.finditer(cleaned))
    if len(matches) < 2:
        if len(matches) == 1:
            # Fallback for single merged number (e.g. 75141111 or 151000879)
            num_str = matches[0].group(0)
            n = len(num_str)
            if 6 <= n <= 10:
                best_split_coords = None
                best_split_score = -9999
                
                # Try all possible split points between 3 and n-3
                for split_idx in range(3, n - 2):
                    xs, ys = num_str[:split_idx], num_str[split_idx:]
                    try:
                        x, y = float(xs), float(ys)
                    except ValueError:
                        continue
                    if not _valid_coord(x, y):
                        continue
                        
                    # Score this split
                    score = 0
                    len_x, len_y = len(xs), len(ys)
                    
                    # 3-5 digits is ideal
                    if 3 <= len_x <= 5 and 3 <= len_y <= 5:
                        score += 100
                    
                    # Penalty for leading zeros in Y unless Y is just 0
                    if ys.startswith("0") and len(ys) > 1:
                        if ys.startswith("00"):
                            score -= 60
                        else:
                            score -= 20
                            
                    # Penalty for leading zeros in X unless X is just 0
                    if xs.startswith("0") and len(xs) > 1:
                        if xs.startswith("00"):
                            score -= 60
                        else:
                            score -= 20
                            
                    # Prefer splits where the lengths are as close as possible
                    score -= abs(len_x - len_y) * 10
                    
                    if score > best_split_score:
                        best_split_score = score
                        best_split_coords = (x, y)
                        
                if best_split_coords and best_split_score >= -50:
                    return best_split_coords
        return None

    best_pair = None
    best_score = -9999

    for i in range(len(matches) - 1):
        m1, m2 = matches[i], matches[i+1]
        xs, ys = m1.group(0), m2.group(0)
        
        try:
            x, y = float(xs), float(ys)
        except ValueError:
            continue
            
        if not _valid_coord(x, y):
            continue
            
        sep_text = cleaned[m1.end():m2.start()]
        
        score = 0
        
        # Evaluate length of coordinates
        len_x, len_y = len(xs), len(ys)
        
        # 3-5 digits is ideal for DayZ coordinates
        if 3 <= len_x <= 5 and 3 <= len_y <= 5:
            score += 100
        elif len_x >= 4 and len_y >= 4:
            score += 80
            
        # Penalty for too short numbers (likely quest counters like 0/1 or dates)
        if len_x == 1 or len_y == 1:
            score -= 150
        elif len_x == 2 or len_y == 2:
            score -= 80
            
        # Penalty for alphabetical or brace characters in separator
        if any(c.isalpha() or c in "()[]" for c in sep_text):
            score -= 50
            
        # Bonus for standard separators
        if any(c in "/-\\–—" for c in sep_text):
            score += 30
        elif sep_text.strip() == "":
            score += 10
            
        if score > best_score:
            best_score = score
            best_pair = (x, y)

    if best_score >= -50:
        return best_pair
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
