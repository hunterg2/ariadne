"""Write the home-screen icons under web/public/icons from icon.png (or the
largest frame of icon.ico when that is bigger).

    py -3 scripts/make_icons.py

Vite copies web/public into web/dist as is, so the files end up beside the
page and the manifest (web/public/manifest.webmanifest) points at them:

    icon-192.png            Android and desktop install
    icon-512.png            the large one, also the splash screen
    icon-maskable-512.png   the icon on a solid square with a safe margin, for
                            launchers that cut it into their own shape
    apple-touch-icon.png    180x180, opaque: iOS ignores the manifest icons

Run it again after changing icon.png and commit what it writes.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "public" / "icons"
BACKGROUND = (24, 24, 37, 255)          # --bg of the dark theme (#181825)
SAFE = 0.80                              # maskable: the icon fills this much of the square


def source():
    """The sharpest icon we have."""
    best = Image.open(ROOT / "icon.png").convert("RGBA")
    ico = ROOT / "icon.ico"
    if ico.exists():
        with Image.open(ico) as frames:
            sizes = frames.info.get("sizes") or {frames.size}
            largest = max(sizes)
            if largest[0] > best.size[0]:
                frames.size = largest
                frames.load()
                best = frames.convert("RGBA")
    return best


def square(im, size):
    return im.resize((size, size), Image.LANCZOS)


def on_background(im, size, scale=1.0):
    canvas = Image.new("RGBA", (size, size), BACKGROUND)
    inner = max(1, int(size * scale))
    icon = square(im, inner)
    offset = (size - inner) // 2
    canvas.alpha_composite(icon, (offset, offset))
    return canvas


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    src = source()
    square(src, 192).save(OUT / "icon-192.png", optimize=True)
    square(src, 512).save(OUT / "icon-512.png", optimize=True)
    on_background(src, 512, SAFE).save(OUT / "icon-maskable-512.png", optimize=True)
    on_background(src, 180).convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    for path in sorted(OUT.iterdir()):
        with Image.open(path) as im:
            print(f"[icons] {path.relative_to(ROOT)} {im.size[0]}x{im.size[1]} {im.mode}")


if __name__ == "__main__":
    main()
