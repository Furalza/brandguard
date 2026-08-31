"""Generate synthetic test icons for icon-similarity tests.

We do not need real logos to validate perceptual hashing; we need image pairs
with known visual relationships. This produces an official icon, a near-copy, a
recoloured copy (same layout), and an unrelated icon. Kept as a script so the
fixtures are reproducible and no binary blobs live in the repo unexplained.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path("data/mock_icons")


def _canvas(bg="white") -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (128, 128), bg)
    return img, ImageDraw.Draw(img)


def official() -> Image.Image:
    img, d = _canvas()
    d.rectangle([18, 30, 110, 98], fill=(0, 90, 180))
    d.text((34, 52), "OB", fill="white")
    return img


def near_copy() -> Image.Image:
    # Same layout, tiny colour shift: an impersonator's copied icon.
    img, d = _canvas()
    d.rectangle([18, 30, 110, 98], fill=(6, 96, 186))
    d.text((34, 52), "OB", fill="white")
    return img


def recolour() -> Image.Image:
    # Same layout, different colour: tests the colour-insensitivity limit.
    img, d = _canvas()
    d.rectangle([18, 30, 110, 98], fill=(20, 150, 60))
    d.text((34, 52), "OB", fill="white")
    return img


def unrelated() -> Image.Image:
    img, d = _canvas("black")
    d.ellipse([24, 24, 104, 104], fill=(220, 40, 40))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    official().save(OUT / "official.png")
    near_copy().save(OUT / "near_copy.png")
    recolour().save(OUT / "recolour.png")
    unrelated().save(OUT / "unrelated.png")
    print(f"wrote 4 icons to {OUT}")


if __name__ == "__main__":
    main()
