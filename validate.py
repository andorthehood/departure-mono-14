#!/usr/bin/env python3
"""Validate canonical YAFF sources and every generated font format."""

from __future__ import annotations

from pathlib import Path

import monobit
from fontTools.pens.pointInsidePen import PointInsidePen
from fontTools.ttLib import TTFont

import build_font


ROOT = Path(__file__).resolve().parent


def bdf_bitmaps(path: Path) -> dict[int, tuple[int, ...]]:
    lines = path.read_text(encoding="ascii").splitlines()
    bitmaps: dict[int, tuple[int, ...]] = {}
    index = 0
    while index < len(lines):
        if not lines[index].startswith("ENCODING "):
            index += 1
            continue
        codepoint = int(lines[index].split()[1])
        while lines[index] != "BITMAP":
            index += 1
        rows = tuple(int(value, 16) for value in lines[index + 1 : index + 15])
        bitmaps[codepoint] = rows
        index += 15
    return bitmaps


def outline_bitmap(glyph_set, glyph_name: str) -> tuple[str, ...]:
    rows: list[str] = []
    for row in range(build_font.CELL_HEIGHT):
        y = build_font.TOP_UNITS - build_font.GRID_UNIT * row - 25
        pixels: list[str] = []
        for column in range(build_font.CELL_WIDTH):
            x = build_font.GRID_UNIT * column + 25
            pen = PointInsidePen(glyph_set, (x, y), evenOdd=False)
            glyph_set[glyph_name].draw(pen)
            pixels.append("@" if pen.getResult() else ".")
        rows.append("".join(pixels))
    return tuple(rows)


def main() -> None:
    glyph_paths = sorted((ROOT / "glyphs").glob("*.yaff"))
    monobit_count = 0
    for path in glyph_paths:
        fonts = monobit.load(path)
        if len(fonts) != 1:
            raise ValueError(f"{path} does not contain exactly one YAFF font")
        monobit_count += len(fonts[0].glyphs)

    glyphs = build_font.load_glyphs(
        ROOT / "glyphs", ROOT / "source" / "glyph-order.txt"
    )
    if monobit_count != len(glyphs):
        raise ValueError("Monobit and the build parser disagree on glyph count")

    encoded = {glyph.codepoint: glyph for glyph in glyphs if glyph.codepoint is not None}
    bdf = bdf_bitmaps(ROOT / "dist" / "DepartureMono14-Regular.bdf")
    if set(bdf) != set(encoded):
        raise ValueError("BDF Unicode coverage differs from YAFF")
    for codepoint, glyph in encoded.items():
        if bdf[codepoint] != tuple(build_font.bitmap_bytes(glyph)):
            raise ValueError(f"BDF differs at U+{codepoint:04X}")

    otf = TTFont(ROOT / "dist" / "DepartureMono14-Regular.otf")
    woff2 = TTFont(ROOT / "dist" / "DepartureMono14-Regular.woff2")
    expected_order = [glyph.name for glyph in glyphs]
    expected_cmap = {glyph.codepoint: glyph.name for glyph in glyphs if glyph.codepoint is not None}
    for label, font in (("OTF", otf), ("WOFF2", woff2)):
        if font["head"].unitsPerEm != build_font.TARGET_UPEM:
            raise ValueError(f"{label} has the wrong units/em")
        if font.getGlyphOrder() != expected_order:
            raise ValueError(f"{label} glyph order differs from YAFF")
        if font.getBestCmap() != expected_cmap:
            raise ValueError(f"{label} Unicode map differs from YAFF")
        if (font["hhea"].ascent, font["hhea"].descent) != (550, -150):
            raise ValueError(f"{label} has the wrong vertical metrics")
        for table_tag in ("GDEF", "GPOS", "GSUB"):
            if table_tag not in font:
                raise ValueError(f"{label} is missing {table_tag}")

    glyph_set = otf.getGlyphSet()
    for glyph in glyphs:
        if outline_bitmap(glyph_set, glyph.name) != glyph.rows:
            raise ValueError(f"OTF outline differs from YAFF glyph {glyph.name}")

    print(f"Validated {len(glyphs)} YAFF glyphs with Monobit")
    print(f"Validated {len(encoded)} BDF characters")
    print("Validated OTF and WOFF2 outlines, metrics, Unicode maps, and layout tables")


if __name__ == "__main__":
    main()
