"""Image preprocessing for iZurvive / DayZ coordinate strip (lime text on dark panel)."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

# Bottom-left strip with "My X/Y: 15100 / 879" on 1920x1080 (numbers only).
IZURVIVE_OCR_REGION = (210, 915, 330, 945)
# Wider strip including the "My X/Y:" label.
IZURVIVE_OCR_REGION_FULL = (12, 915, 280, 945)


def preprocess_coordinate_region(image: Image.Image) -> Image.Image:
    """Isolate bright lime/yellow coordinate digits on a dark overlay background."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]

    # iZurvive coords: #c8d84a-like lime on dark blue-gray panel.
    signal = np.maximum(green, red * 0.92) - blue * 0.88
    signal = np.clip(signal, 0, 255)

    if float(signal.max()) < 8:
        gray = image.convert("L")
    else:
        thresh = max(32.0, float(np.percentile(signal, 70)) * 0.55)
        binary = np.where(signal > thresh, 255, 0).astype(np.uint8)
        gray = Image.fromarray(binary, mode="L")

    gray = ImageOps.autocontrast(gray, cutoff=1)
    width, height = gray.size
    scale = max(3, min(6, 180 // max(height, 1)))
    if scale > 1:
        gray = gray.resize((width * scale, height * scale), Image.Resampling.LANCZOS)
    gray = ImageEnhance.Contrast(gray).enhance(1.4)
    return gray.convert("RGB")
