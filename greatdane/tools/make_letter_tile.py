#!/usr/bin/env python3
# Usage: make_letter_tile.py <images/...@2x.png 192px> <favicons/....png 32px>   (needs Pillow + DejaVu Sans Bold)
# Generates the neutral letter tile used for the grokipedia.com default tile (not the site's own mark).
from PIL import Image, ImageDraw, ImageFont
import sys
BG, FG = (74, 85, 104, 255), (255, 255, 255, 255)   # #4a5568 slate, white
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
def tile(n, out):
    im = Image.new("RGBA", (n, n), BG); d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT, int(n * 0.62))
    l, t, r, b = d.textbbox((0, 0), "G", font=f)
    d.text(((n - (r - l)) / 2 - l, (n - (b - t)) / 2 - t), "G", font=f, fill=FG)
    im.save(out, optimize=True)
tile(192, sys.argv[1]); tile(32, sys.argv[2])
