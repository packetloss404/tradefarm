"""Render the TradeFarm favicon at multiple sizes and pack them into favicon.ico.

Mirrors web/public/favicon.svg: 3x3 grid of dots on a rounded-square bg,
diagonal (BL -> TR) lit emerald.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

BG = (9, 9, 11, 255)            # zinc-950
DOT_OFF = (63, 63, 70, 255)     # zinc-700
DOT_ON = (52, 211, 153, 255)    # emerald-400

OUT = Path(__file__).resolve().parent.parent / "web" / "public" / "favicon.ico"


def _draw(px: int) -> Image.Image:
    """Render the logo at (px, px)."""
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded-square background occupying the full canvas.
    radius = max(1, px // 5)
    d.rounded_rectangle((0, 0, px - 1, px - 1), radius=radius, fill=BG)

    # 3x3 dot grid centered in the canvas at 25/50/75% positions.
    cols_rows = [0.25, 0.5, 0.75]
    dot_r = max(1, int(px * 0.07))  # ~2.2px at 32px canvas
    # Diagonal from bottom-left to top-right = (0,2), (1,1), (2,0).
    lit = {(0, 2), (1, 1), (2, 0)}

    for iy, fy in enumerate(cols_rows):
        for ix, fx in enumerate(cols_rows):
            cx = fx * px
            cy = fy * px
            color = DOT_ON if (ix, iy) in lit else DOT_OFF
            d.ellipse(
                (cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r),
                fill=color,
            )
    return img


def main() -> None:
    sizes = [16, 24, 32, 48, 64]
    frames = [_draw(s) for s in sizes]
    # Pillow accepts a single Image; additional sizes go via `sizes=` param.
    frames[0].save(
        OUT,
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )
    print(f"wrote {OUT} with sizes {sizes}")

    # Also dump the 64px as a standalone PNG for use as a preview image.
    png_out = OUT.parent / "logo-mark.png"
    _draw(256).save(png_out, "PNG")
    print(f"wrote {png_out} (256x256)")


if __name__ == "__main__":
    main()
