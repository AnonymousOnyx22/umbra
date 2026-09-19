"""Draw the umbra ghost as a multi-size .ico for the Windows shortcut.

Run: python tools/make_icon.py [out.ico]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

BODY = (139, 116, 232, 255)     # #8b74e8
RIM = (185, 167, 255, 255)      # #b9a7ff
EYE = (18, 16, 30, 255)
CLEAR = (0, 0, 0, 0)

SUPERSAMPLE = 8
SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw_ghost(size: int) -> Image.Image:
    s = size * SUPERSAMPLE
    img = Image.new("RGBA", (s, s), CLEAR)
    d = ImageDraw.Draw(img)

    margin = s * 0.11
    left, right = margin, s - margin
    width = right - left
    top = margin
    bottom = s - margin
    hem = bottom - width * 0.16   # where the scallops start

    # Dome + body.
    d.pieslice([left, top, right, top + width], 180, 360, fill=BODY)
    d.rectangle([left, top + width / 2, right, hem], fill=BODY)
    d.rectangle([left, hem - 1, right, bottom], fill=BODY)

    # Scalloped hem: punch three notches out of the bottom edge.
    notch = width / 3
    for i in range(3):
        cx = left + notch * i
        d.pieslice(
            [cx, bottom - notch * 0.85, cx + notch, bottom + notch * 0.85],
            180, 360, fill=CLEAR,
        )

    # Rim light along the top of the dome.
    rim = s * 0.035
    d.arc([left + rim, top + rim, right - rim, top + width - rim],
          195, 345, fill=RIM, width=int(rim * 1.6))

    # Eyes.
    eye_w = width * 0.155
    eye_h = eye_w * 1.35
    eye_y = top + width * 0.46
    for cx in (left + width * 0.30, left + width * 0.70):
        d.ellipse([cx - eye_w / 2, eye_y, cx + eye_w / 2, eye_y + eye_h], fill=EYE)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("assets/umbra.ico")
    out.parent.mkdir(parents=True, exist_ok=True)
    frames = [draw_ghost(n) for n in SIZES]
    frames[-1].save(out, format="ICO", sizes=[(n, n) for n in SIZES])
    print(f"wrote {out} ({', '.join(str(n) for n in SIZES)})")


if __name__ == "__main__":
    main()
