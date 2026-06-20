import sys
import os
from PIL import Image

# Add client folder to path
sys.path.append(r"d:\projects\dayz_map_and_client_soft\client")

from ocr_preprocess import preprocess_variants

img_path = r"C:\Users\IgnorGTO\.gemini\antigravity-ide\brain\c037bc71-8081-40c5-b6d1-bcb7f310edfc\media__1781988880038.png"

if not os.path.exists(img_path):
    print("Image not found:", img_path)
    sys.exit(1)

img = Image.open(img_path)
print("Image size:", img.size)

variants = preprocess_variants(img)
print(f"Preprocess variants generated: {len(variants)}")

for i, var in enumerate(variants):
    var.save(f"variant_{i}.png")
    print(f"Saved variant_{i}.png, size={var.size}")
