"""Rasterise SVGs to PNG on a white background: python svg2png.py <width_px> file.svg ..."""
import sys

import pymupdf

width = int(sys.argv[1])
for path in sys.argv[2:]:
    doc = pymupdf.open(path)
    page = doc[0]
    zoom = width / page.rect.width
    page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).save(path[:-4] + ".png")
    print(path[:-4] + ".png")
