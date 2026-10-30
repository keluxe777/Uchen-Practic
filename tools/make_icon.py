"""Рисует иконку программы assets/icon.ico: python tools/make_icon.py"""

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def draw(size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 256
    d.rounded_rectangle([8 * s, 8 * s, 248 * s, 248 * s], radius=52 * s, fill="#3b5bdb")
    white = "#ffffff"
    # микрофон
    d.rounded_rectangle([70 * s, 40 * s, 122 * s, 140 * s], radius=26 * s, fill=white)
    d.arc([50 * s, 80 * s, 142 * s, 170 * s], start=0, end=180, fill=white, width=int(10 * s))
    d.rectangle([91 * s, 168 * s, 101 * s, 196 * s], fill=white)
    d.rounded_rectangle([66 * s, 192 * s, 126 * s, 204 * s], radius=6 * s, fill=white)
    # строки текста справа
    for i, width in enumerate((70, 56, 70, 44)):
        y = (70 + i * 34) * s
        d.rounded_rectangle([150 * s, y, (150 + width) * s, y + 14 * s], radius=7 * s, fill=white)
    return img


if __name__ == "__main__":
    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    icon = draw()
    icon.save(os.path.join(ROOT, "assets", "icon.ico"),
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.save(os.path.join(ROOT, "assets", "icon.png"))
    print("готово: assets/icon.ico")
