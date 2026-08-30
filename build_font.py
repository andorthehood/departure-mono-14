#!/usr/bin/env python3
"""Build BDF, OTF, and WOFF2 files exclusively from canonical YAFF glyphs."""

from __future__ import annotations

import argparse
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont


TARGET_UPEM = 700
GRID_UNIT = 50
CELL_WIDTH = 7
CELL_HEIGHT = 14
ASCENT = 11
DESCENT = 3
ADVANCE_UNITS = 350
TOP_UNITS = 550

FAMILY_NAME = "Departure Mono 14"
FULL_NAME = "Departure Mono 14 Regular"
POSTSCRIPT_NAME = "DepartureMono14-Regular"
VERSION = "1.500.14"
COPYRIGHT = "Copyright 2022-2024 Helena Zhang; modified under SIL OFL 1.1"

UNICODE_LABEL = re.compile(r"^u\+([0-9A-Fa-f]+):$")
TAG_LABEL = re.compile(r'^"([^"\\]+)":$')


@dataclass(frozen=True)
class Glyph:
    name: str
    codepoint: int | None
    rows: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--glyphs", type=Path, default=here / "glyphs")
    parser.add_argument(
        "--glyph-order", type=Path, default=here / "source" / "glyph-order.txt"
    )
    parser.add_argument(
        "--layout", type=Path, default=here / "source" / "opentype-layout.ttx"
    )
    parser.add_argument(
        "--license", type=Path, default=here / "OFL.txt"
    )
    parser.add_argument("--output", type=Path, default=here / "dist")
    return parser.parse_args()


def parse_yaff_file(path: Path) -> list[Glyph]:
    lines = path.read_text(encoding="utf-8").splitlines()
    glyphs: list[Glyph] = []
    pending_codepoint: int | None = None
    pending_name: str | None = None
    index = 0

    while index < len(lines):
        line = lines[index]
        unicode_match = UNICODE_LABEL.match(line)
        tag_match = TAG_LABEL.match(line)
        if unicode_match:
            pending_codepoint = int(unicode_match.group(1), 16)
            index += 1
            continue
        if tag_match:
            pending_name = tag_match.group(1)
            index += 1
            continue

        stripped = line.strip()
        if line.startswith((" ", "\t")) and stripped and set(stripped) <= {".", "@"}:
            rows: list[str] = []
            while index < len(lines):
                candidate = lines[index].strip()
                if not candidate or not set(candidate) <= {".", "@"}:
                    break
                rows.append(candidate)
                index += 1

            if pending_name is None:
                raise ValueError(f"{path}: bitmap has no glyph-name tag")
            if len(rows) != CELL_HEIGHT or any(len(row) != CELL_WIDTH for row in rows):
                raise ValueError(f"{path}: {pending_name} is not {CELL_WIDTH}x{CELL_HEIGHT}")
            glyphs.append(Glyph(pending_name, pending_codepoint, tuple(rows)))
            pending_codepoint = None
            pending_name = None
            continue
        index += 1

    if pending_codepoint is not None or pending_name is not None:
        raise ValueError(f"{path}: dangling glyph label")
    return glyphs


def load_glyphs(glyph_directory: Path, glyph_order_path: Path) -> list[Glyph]:
    by_name: dict[str, Glyph] = {}
    by_codepoint: dict[int, str] = {}
    for path in sorted(glyph_directory.glob("*.yaff")):
        for glyph in parse_yaff_file(path):
            if glyph.name in by_name:
                raise ValueError(f"Duplicate glyph name: {glyph.name}")
            if glyph.codepoint is not None and glyph.codepoint in by_codepoint:
                raise ValueError(f"Duplicate Unicode code point: U+{glyph.codepoint:04X}")
            by_name[glyph.name] = glyph
            if glyph.codepoint is not None:
                by_codepoint[glyph.codepoint] = glyph.name

    order = [line.strip() for line in glyph_order_path.read_text().splitlines() if line.strip()]
    if set(order) != set(by_name):
        missing = sorted(set(order) - set(by_name))
        extra = sorted(set(by_name) - set(order))
        raise ValueError(f"Glyph order/source mismatch; missing={missing}, extra={extra}")
    if not order or order[0] != ".notdef":
        raise ValueError("Glyph order must begin with .notdef")
    return [by_name[name] for name in order]


def bitmap_bytes(glyph: Glyph) -> list[int]:
    return [
        sum((1 << (7 - column)) for column, pixel in enumerate(row) if pixel == "@")
        for row in glyph.rows
    ]


def safe_bdf_name(glyph: Glyph) -> str:
    clean_name = re.sub(r"[^A-Za-z0-9_.-]", "_", glyph.name)
    return clean_name if glyph.codepoint is None else f"u{glyph.codepoint:04X}_{clean_name}"


def write_bdf(glyphs: list[Glyph], destination: Path) -> int:
    encoded = sorted(
        (glyph for glyph in glyphs if glyph.codepoint is not None),
        key=lambda glyph: glyph.codepoint,
    )
    encoded_codepoints = {glyph.codepoint for glyph in encoded}
    properties = [
        'FOUNDRY "misc"',
        f'FAMILY_NAME "{FAMILY_NAME}"',
        'WEIGHT_NAME "Regular"',
        'SLANT "R"',
        'SETWIDTH_NAME "Normal"',
        'ADD_STYLE_NAME ""',
        'PIXEL_SIZE 14',
        'POINT_SIZE 140',
        'RESOLUTION_X 75',
        'RESOLUTION_Y 75',
        'SPACING "C"',
        'AVERAGE_WIDTH 70',
        'CHARSET_REGISTRY "ISO10646"',
        'CHARSET_ENCODING "1"',
        f'FONT_ASCENT {ASCENT}',
        f'FONT_DESCENT {DESCENT}',
        f'COPYRIGHT "{COPYRIGHT}"',
    ]
    if 0xFFFD in encoded_codepoints:
        properties.append("DEFAULT_CHAR 65533")

    lines = [
        "STARTFONT 2.1",
        "COMMENT Exact 7x14 bitmap build from canonical YAFF glyph sources",
        "FONT -misc-departure-mono-14-medium-r-normal--14-140-75-75-c-70-iso10646-1",
        "SIZE 14 75 75",
        f"FONTBOUNDINGBOX {CELL_WIDTH} {CELL_HEIGHT} 0 -{DESCENT}",
        f"STARTPROPERTIES {len(properties)}",
        *properties,
        "ENDPROPERTIES",
        f"CHARS {len(encoded)}",
    ]
    for glyph in encoded:
        lines.extend(
            [
                f"STARTCHAR {safe_bdf_name(glyph)}",
                f"ENCODING {glyph.codepoint}",
                "SWIDTH 500 0",
                f"DWIDTH {CELL_WIDTH} 0",
                f"BBX {CELL_WIDTH} {CELL_HEIGHT} 0 -{DESCENT}",
                "BITMAP",
                *(f"{row:02X}" for row in bitmap_bytes(glyph)),
                "ENDCHAR",
            ]
        )
    lines.append("ENDFONT")
    destination.write_text("\n".join(lines) + "\n", encoding="ascii")
    return len(encoded)


def rectangles(glyph: Glyph) -> list[tuple[int, int, int, int]]:
    """Return non-overlapping pixel-run rectangles as x0, y0, x1, y1."""
    active: dict[tuple[int, int], int] = {}
    result: list[tuple[int, int, int, int]] = []
    for row_index, row in enumerate(glyph.rows + ("." * CELL_WIDTH,)):
        runs: list[tuple[int, int]] = []
        column = 0
        while column < CELL_WIDTH:
            if row[column] == ".":
                column += 1
                continue
            start = column
            while column < CELL_WIDTH and row[column] == "@":
                column += 1
            runs.append((start, column))

        current = set(runs)
        for run, start_row in list(active.items()):
            if run in current:
                continue
            x0, x1 = (value * GRID_UNIT for value in run)
            y1 = TOP_UNITS - start_row * GRID_UNIT
            y0 = TOP_UNITS - row_index * GRID_UNIT
            result.append((x0, y0, x1, y1))
            del active[run]
        for run in runs:
            active.setdefault(run, row_index)
    return result


def charstring_for_glyph(glyph: Glyph):
    pen = T2CharStringPen(ADVANCE_UNITS, None)
    for x0, y0, x1, y1 in rectangles(glyph):
        pen.moveTo((x0, y0))
        pen.lineTo((x1, y0))
        pen.lineTo((x1, y1))
        pen.lineTo((x0, y1))
        pen.closePath()
    return pen.getCharString()


def left_side_bearing(glyph: Glyph) -> int:
    inked_columns = [
        column
        for row in glyph.rows
        for column, pixel in enumerate(row)
        if pixel == "@"
    ]
    return min(inked_columns) * GRID_UNIT if inked_columns else 0


def build_outline_variant(
    glyphs: list[Glyph], layout_path: Path, otf_destination: Path, woff2_destination: Path
) -> None:
    glyph_order = [glyph.name for glyph in glyphs]
    character_map = {
        glyph.codepoint: glyph.name for glyph in glyphs if glyph.codepoint is not None
    }
    metrics = {
        glyph.name: (ADVANCE_UNITS, left_side_bearing(glyph)) for glyph in glyphs
    }
    charstrings = {glyph.name: charstring_for_glyph(glyph) for glyph in glyphs}

    builder = FontBuilder(TARGET_UPEM, isTTF=False)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(character_map)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=550, descent=-150, lineGap=0)
    builder.setupNameTable(
        {
            "familyName": FAMILY_NAME,
            "styleName": "Regular",
            "uniqueFontIdentifier": f"{VERSION};OFL;{POSTSCRIPT_NAME}",
            "fullName": FULL_NAME,
            "psName": POSTSCRIPT_NAME,
            "version": f"Version {VERSION}",
            "copyright": COPYRIGHT,
        }
    )
    builder.setupOS2(
        sTypoAscender=550,
        sTypoDescender=-150,
        sTypoLineGap=0,
        usWinAscent=550,
        usWinDescent=150,
        sxHeight=300,
        sCapHeight=400,
        usWeightClass=400,
        usWidthClass=5,
        fsType=0,
    )
    builder.setupPost(
        italicAngle=0,
        underlinePosition=-55,
        underlineThickness=30,
        isFixedPitch=1,
        keepGlyphNames=True,
    )
    builder.setupCFF(
        POSTSCRIPT_NAME,
        {
            "version": VERSION,
            "FullName": FULL_NAME,
            "FamilyName": FAMILY_NAME,
            "Weight": "Regular",
            "Notice": COPYRIGHT,
            "isFixedPitch": 1,
            "ItalicAngle": 0,
            "UnderlinePosition": -55,
            "UnderlineThickness": 30,
        },
        charstrings,
        {},
    )
    builder.setupMaxp()
    builder.font["head"].fontRevision = 1.50014
    builder.font.importXML(layout_path)
    builder.save(otf_destination)

    webfont = TTFont(otf_destination)
    webfont.flavor = "woff2"
    webfont.save(woff2_destination, reorderTables=True)
    webfont.close()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    glyphs = load_glyphs(args.glyphs.resolve(), args.glyph_order.resolve())
    bdf_path = output / "DepartureMono14-Regular.bdf"
    encoded_count = write_bdf(glyphs, bdf_path)
    otf_path = output / "DepartureMono14-Regular.otf"
    woff2_path = output / "DepartureMono14-Regular.woff2"
    build_outline_variant(glyphs, args.layout.resolve(), otf_path, woff2_path)
    if args.license.exists():
        shutil.copyfile(args.license, output / "OFL.txt")
    print(f"Loaded {len(glyphs)} YAFF glyphs ({encoded_count} Unicode-encoded)")
    print(f"Built {bdf_path.name}, {otf_path.name}, and {woff2_path.name}")


if __name__ == "__main__":
    main()
