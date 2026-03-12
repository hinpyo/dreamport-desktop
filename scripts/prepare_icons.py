from __future__ import annotations

import shutil
from collections import deque
from pathlib import Path
from typing import Dict, Sequence

from PIL import Image, ImageDraw, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = PROJECT_ROOT / "assets"
SOURCE_PNG = ASSETS_DIR / "oscar_icon.png"
RUNTIME_PNG = ASSETS_DIR / "oscar_icon_runtime.png"
MAC_PREVIEW_PNG = ASSETS_DIR / "oscar_icon_macos.png"
HEADER_PNG = ASSETS_DIR / "dreamport_header_icon.png"
ICO_ICON = ASSETS_DIR / "oscar_icon.ico"
ICNS_ICON = ASSETS_DIR / "oscar_icon.icns"
MAC_ICONSET_DIR = ASSETS_DIR / "macos.iconset"

WINDOWS_ICON_SIZES: Sequence[tuple[int, int]] = (
    (256, 256),
    (128, 128),
    (64, 64),
    (48, 48),
    (40, 40),
    (32, 32),
    (24, 24),
    (20, 20),
    (16, 16),
)

MAC_ICONSET_SIZES: Dict[str, int] = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}



def remove_connected_white_background(image: Image.Image, *, threshold: int = 245) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    visited = bytearray(width * height)
    queue = deque()

    def is_background(x: int, y: int) -> bool:
        r, g, b, a = pixels[x, y]
        return a > 0 and r >= threshold and g >= threshold and b >= threshold

    def enqueue(x: int, y: int) -> None:
        index = y * width + x
        if visited[index]:
            return
        visited[index] = 1
        if is_background(x, y):
            queue.append((x, y))

    for x in range(width):
        enqueue(x, 0)
        enqueue(x, height - 1)
    for y in range(height):
        enqueue(0, y)
        enqueue(width - 1, y)

    while queue:
        x, y = queue.popleft()
        pixels[x, y] = (255, 255, 255, 0)
        if x > 0:
            enqueue(x - 1, y)
        if x < width - 1:
            enqueue(x + 1, y)
        if y > 0:
            enqueue(x, y - 1)
        if y < height - 1:
            enqueue(x, y + 1)

    return rgba



def trim_transparency(image: Image.Image) -> Image.Image:
    bbox = image.getbbox()
    if bbox is None:
        return image
    return image.crop(bbox)



def fit_into_canvas(image: Image.Image, canvas_size: int, target_ratio: float, y_offset: int = 0) -> Image.Image:
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    trimmed = trim_transparency(image)
    max_side = int(canvas_size * target_ratio)
    trimmed.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    x = (canvas_size - trimmed.width) // 2
    y = (canvas_size - trimmed.height) // 2 + y_offset
    canvas.alpha_composite(trimmed, (x, y))
    return canvas



def create_windows_master(image: Image.Image) -> Image.Image:
    return fit_into_canvas(image, canvas_size=1024, target_ratio=0.88)



def create_header_icon(image: Image.Image) -> Image.Image:
    header_master = fit_into_canvas(image, canvas_size=192, target_ratio=0.94)
    shadow = Image.new("RGBA", (192, 192), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse((26, 134, 166, 176), fill=(10, 24, 56, 28))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    shadow.alpha_composite(header_master)
    return shadow



def _shadowed_rounded_rect(size: int, rect_size: int, radius: int) -> Image.Image:
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    left = (size - rect_size) // 2
    top = (size - rect_size) // 2 + 16
    right = left + rect_size
    bottom = top + rect_size
    shadow_draw.rounded_rectangle((left, top, right, bottom), radius=radius, fill=(15, 22, 38, 100))
    return shadow.filter(ImageFilter.GaussianBlur(38))



def _white_card(size: int, rect_size: int, radius: int) -> Image.Image:
    card = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    left = (size - rect_size) // 2
    top = (size - rect_size) // 2
    right = left + rect_size
    bottom = top + rect_size
    draw.rounded_rectangle((left, top, right, bottom), radius=radius, fill=(255, 255, 255, 255))
    return card



def create_macos_master(image: Image.Image) -> Image.Image:
    size = 1024
    background = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    background.alpha_composite(_shadowed_rounded_rect(size=size, rect_size=864, radius=196))
    background.alpha_composite(_white_card(size=size, rect_size=860, radius=192))
    art = fit_into_canvas(image, canvas_size=size, target_ratio=0.70, y_offset=-4)
    background.alpha_composite(art)
    return background



def write_iconset(master: Image.Image) -> None:
    if MAC_ICONSET_DIR.exists():
        shutil.rmtree(MAC_ICONSET_DIR)
    MAC_ICONSET_DIR.mkdir(parents=True, exist_ok=True)

    for filename, size in MAC_ICONSET_SIZES.items():
        master.resize((size, size), Image.Resampling.LANCZOS).save(MAC_ICONSET_DIR / filename)



def main() -> int:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    if not SOURCE_PNG.exists():
        raise FileNotFoundError(f"Source icon not found: {SOURCE_PNG}")

    with Image.open(SOURCE_PNG) as source:
        rgba = source.convert("RGBA")
        artwork = remove_connected_white_background(rgba)
        windows_master = create_windows_master(artwork)
        macos_master = create_macos_master(artwork)
        header_icon = create_header_icon(artwork)

        windows_master.save(RUNTIME_PNG)
        macos_master.save(MAC_PREVIEW_PNG)
        header_icon.save(HEADER_PNG)
        windows_master.save(ICO_ICON, sizes=list(WINDOWS_ICON_SIZES))
        macos_master.save(ICNS_ICON)
        write_iconset(macos_master)

    print(f"Prepared icons from PNG source: {SOURCE_PNG}")
    print(f"- Runtime PNG  : {RUNTIME_PNG}")
    print(f"- Header PNG   : {HEADER_PNG}")
    print(f"- macOS master : {MAC_PREVIEW_PNG}")
    print(f"- Windows ICO  : {ICO_ICON}")
    print(f"- macOS ICNS   : {ICNS_ICON}")
    print(f"- macOS iconset: {MAC_ICONSET_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
