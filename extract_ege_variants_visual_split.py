#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Split a scanned/image PDF into separate variant PDFs using visual reference crops.

The script searches rendered pages for two images:
  - start reference: beginning of the desired fragment
  - end reference: beginning of the next task / end boundary

Typical usage on Windows PowerShell:
  py .\extract_ege_variants_visual_split.py ".\Doschinskii_774_2026.pdf" \
    --start-ref ".\start_ref.png" --end-ref ".\end_ref.png" \
    --split-dir ".\variants_texts" --start-variant 10 --visible-stamp

Dependencies:
  py -m pip install pymupdf pillow numpy opencv-python
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import fitz  # PyMuPDF
except Exception as exc:  # pragma: no cover
    print("ERROR: PyMuPDF is not installed. Run: py -m pip install pymupdf", file=sys.stderr)
    raise

try:
    import cv2
    import numpy as np
except Exception as exc:  # pragma: no cover
    print("ERROR: OpenCV/numpy are not installed. Run: py -m pip install numpy opencv-python", file=sys.stderr)
    raise


@dataclass
class Match:
    page_index: int          # zero-based
    score: float
    x_px: int
    y_px: int
    w_px: int
    h_px: int
    scale: float
    image_w_px: int
    image_h_px: int

    @property
    def page_num(self) -> int:
        return self.page_index + 1


@dataclass
class Fragment:
    index: int
    variant: int
    start: Match
    end: Match

    @property
    def start_page(self) -> int:
        return self.start.page_num

    @property
    def end_page(self) -> int:
        return self.end.page_num


def normalize_text_for_filename(value: str) -> str:
    value = re.sub(r"[^\w\-.]+", "-", value, flags=re.UNICODE)
    value = re.sub(r"-+", "-", value).strip("-._")
    return value or "file"


def parse_page_number(value: Optional[int], page_count: int, default: int) -> int:
    if value is None:
        return default
    if value < 1 or value > page_count:
        raise ValueError(f"Page number {value} is outside 1..{page_count}")
    return value


def render_page_gray(doc: fitz.Document, page_index: int, dpi: int) -> np.ndarray:
    page = doc.load_page(page_index)
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 1:
        gray = arr
    else:
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    return gray


def load_ref_gray(path: Path) -> np.ndarray:
    if not path.exists():
        raise FileNotFoundError(f"Reference image not found: {path}")
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Cannot read reference image: {path}")
    return img


def make_scales(start: float, end: float, step: float) -> List[float]:
    if start <= 0 or end <= 0 or step <= 0:
        raise ValueError("Scale range values must be positive")
    if start > end:
        start, end = end, start
    values = []
    current = start
    while current <= end + 1e-9:
        values.append(round(current, 4))
        current += step
    if 1.0 not in values:
        values.append(1.0)
    return sorted(set(values))


def best_template_match(
    page_gray: np.ndarray,
    ref_gray: np.ndarray,
    page_index: int,
    scales: Sequence[float],
    search_band: Optional[Tuple[float, float]] = None,
) -> Optional[Match]:
    """Return best template match on the page. search_band is (top,bottom) fractions of page height."""
    source = page_gray
    y_offset = 0
    if search_band is not None:
        top_f, bottom_f = search_band
        h = page_gray.shape[0]
        y0 = max(0, min(h - 1, int(h * top_f)))
        y1 = max(y0 + 1, min(h, int(h * bottom_f)))
        source = page_gray[y0:y1, :]
        y_offset = y0

    best: Optional[Match] = None
    src_h, src_w = source.shape[:2]

    for scale in scales:
        new_w = max(1, int(round(ref_gray.shape[1] * scale)))
        new_h = max(1, int(round(ref_gray.shape[0] * scale)))
        if new_w >= src_w or new_h >= src_h:
            continue
        resized = cv2.resize(ref_gray, (new_w, new_h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        # TM_CCOEFF_NORMED is reasonably robust for text fragments.
        result = cv2.matchTemplate(source, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if best is None or max_val > best.score:
            best = Match(
                page_index=page_index,
                score=float(max_val),
                x_px=int(max_loc[0]),
                y_px=int(max_loc[1] + y_offset),
                w_px=int(new_w),
                h_px=int(new_h),
                scale=float(scale),
                image_w_px=int(page_gray.shape[1]),
                image_h_px=int(page_gray.shape[0]),
            )
    return best


def find_matches(
    doc: fitz.Document,
    ref_gray: np.ndarray,
    dpi: int,
    threshold: float,
    scales: Sequence[float],
    from_page: int,
    to_page: int,
    search_band: Optional[Tuple[float, float]],
    label: str,
    verbose: bool,
) -> Dict[int, Match]:
    matches: Dict[int, Match] = {}
    for page_num in range(from_page, to_page + 1):
        page_index = page_num - 1
        gray = render_page_gray(doc, page_index, dpi)
        match = best_template_match(gray, ref_gray, page_index, scales, search_band=search_band)
        if match is not None and verbose:
            print(f"{label}: page {page_num}: score={match.score:.3f}, scale={match.scale:.3f}, y={match.y_px}")
        if match is not None and match.score >= threshold:
            matches[page_index] = match
    return matches


def build_fragments(
    start_matches: Dict[int, Match],
    end_matches: Dict[int, Match],
    start_variant: int,
) -> List[Fragment]:
    starts = sorted(start_matches.values(), key=lambda m: (m.page_index, m.y_px))
    ends = sorted(end_matches.values(), key=lambda m: (m.page_index, m.y_px))
    fragments: List[Fragment] = []
    end_pos = 0

    for start in starts:
        while end_pos < len(ends) and (ends[end_pos].page_index, ends[end_pos].y_px) < (start.page_index, start.y_px):
            end_pos += 1
        if end_pos >= len(ends):
            break
        end = ends[end_pos]
        # If there is another start before this end, this start is likely a false positive.
        fragments.append(Fragment(index=len(fragments) + 1, variant=start_variant + len(fragments), start=start, end=end))
        end_pos += 1

    return fragments


def pdf_rect_from_px(page: fitz.Page, match: Match, mode: str) -> fitz.Rect:
    rect = page.rect
    x_scale = rect.width / match.image_w_px
    y_scale = rect.height / match.image_h_px
    if mode == "top":
        y = match.y_px * y_scale
        return fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + y)
    if mode == "from_top":
        y = match.y_px * y_scale
        return fitz.Rect(rect.x0, rect.y0 + y, rect.x1, rect.y1)
    if mode == "after_marker":
        y = (match.y_px + match.h_px) * y_scale
        return fitz.Rect(rect.x0, rect.y0 + y, rect.x1, rect.y1)
    if mode == "to_marker":
        y = match.y_px * y_scale
        return fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + y)
    raise ValueError(mode)


def sane_clip(rect: fitz.Rect, min_height: float = 20.0) -> Optional[fitz.Rect]:
    rect = fitz.Rect(rect)
    if rect.width <= 1 or rect.height < min_height:
        return None
    return rect


def insert_clipped_page(out: fitz.Document, src: fitz.Document, page_index: int, clip: fitz.Rect) -> None:
    clip = fitz.Rect(clip)
    new_page = out.new_page(width=clip.width, height=clip.height)
    new_page.show_pdf_page(fitz.Rect(0, 0, clip.width, clip.height), src, page_index, clip=clip)


def add_stamp(page: fitz.Page, text: str) -> None:
    # Use a built-in font to avoid external font dependencies. Cyrillic rendering depends on viewer/font support,
    # so keep ASCII fallback if needed.
    box = fitz.Rect(24, 18, min(page.rect.width - 24, 220), 46)
    page.draw_rect(box, color=(0, 0, 0), fill=(1, 1, 1), overlay=True)
    try:
        page.insert_textbox(box, text, fontsize=12, fontname="helv", color=(0, 0, 0), align=0, overlay=True)
    except Exception:
        page.insert_textbox(box, text.encode("ascii", "ignore").decode("ascii") or "Variant", fontsize=12, fontname="helv", color=(0, 0, 0), align=0, overlay=True)


def export_pages_fragment(src: fitz.Document, fragment: Fragment, out_path: Path, visible_stamp: bool) -> None:
    out = fitz.open()
    out.insert_pdf(src, from_page=fragment.start.page_index, to_page=fragment.end.page_index)
    if visible_stamp and len(out) > 0:
        add_stamp(out[0], f"Variant {fragment.variant}")
    out.save(out_path, garbage=4, deflate=True)
    out.close()


def export_crop_fragment(src: fitz.Document, fragment: Fragment, out_path: Path, visible_stamp: bool, include_start_marker: bool) -> None:
    out = fitz.open()
    s_idx = fragment.start.page_index
    e_idx = fragment.end.page_index

    for page_index in range(s_idx, e_idx + 1):
        page = src.load_page(page_index)
        page_rect = page.rect

        if s_idx == e_idx:
            y_scale = page_rect.height / fragment.start.image_h_px
            y0_px = fragment.start.y_px if include_start_marker else fragment.start.y_px + fragment.start.h_px
            y1_px = fragment.end.y_px
            y0 = y0_px * y_scale
            y1 = y1_px * y_scale
            clip = sane_clip(fitz.Rect(page_rect.x0, page_rect.y0 + y0, page_rect.x1, page_rect.y0 + y1))
        elif page_index == s_idx:
            clip = pdf_rect_from_px(page, fragment.start, "from_top" if include_start_marker else "after_marker")
            clip = sane_clip(clip)
        elif page_index == e_idx:
            clip = pdf_rect_from_px(page, fragment.end, "to_marker")
            clip = sane_clip(clip)
        else:
            clip = sane_clip(page_rect)

        if clip is not None:
            insert_clipped_page(out, src, page_index, clip)

    if visible_stamp and len(out) > 0:
        add_stamp(out[0], f"Variant {fragment.variant}")
    out.save(out_path, garbage=4, deflate=True)
    out.close()


def write_manifest(path: Path, fragments: Sequence[Fragment], filenames: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "fragment_index",
            "variant",
            "start_page",
            "end_page",
            "start_score",
            "end_score",
            "start_scale",
            "end_scale",
            "filename",
        ])
        for frag, filename in zip(fragments, filenames):
            writer.writerow([
                frag.index,
                frag.variant,
                frag.start_page,
                frag.end_page,
                f"{frag.start.score:.4f}",
                f"{frag.end.score:.4f}",
                f"{frag.start.scale:.4f}",
                f"{frag.end.scale:.4f}",
                filename,
            ])


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Split scanned PDF into variant PDFs using visual start/end reference images.")
    parser.add_argument("input_pdf", help="Input PDF file")
    parser.add_argument("--start-ref", required=True, help="Image crop that marks the beginning of a fragment")
    parser.add_argument("--end-ref", required=True, help="Image crop that marks the end boundary of a fragment")
    parser.add_argument("--split-dir", default="variants_texts", help="Output directory for separate PDFs")
    parser.add_argument("--start-variant", type=int, default=1, help="Number of the first variant")
    parser.add_argument("--prefix", default="variant", help="Output filename prefix")
    parser.add_argument("--digits", type=int, default=0, help="Zero padding for variant number, e.g. 2 -> variant-10 stays 10, variant-01 for 1")
    parser.add_argument("--mode", choices=["pages", "crop"], default="pages", help="pages = full pages, crop = cut by visual boundaries")
    parser.add_argument("--visible-stamp", action="store_true", help="Stamp Variant N on the first page of every output PDF")
    parser.add_argument("--exclude-start-marker", action="store_true", help="In crop mode, start after the start reference instead of including it")
    parser.add_argument("--report-only", action="store_true", help="Only print detected fragments; do not write PDFs")
    parser.add_argument("--dpi", type=int, default=180, help="Render DPI used for visual search")
    parser.add_argument("--threshold", type=float, default=0.55, help="Template-match threshold, typical 0.50..0.75")
    parser.add_argument("--scale-min", type=float, default=0.55, help="Minimum scale for reference image matching")
    parser.add_argument("--scale-max", type=float, default=1.80, help="Maximum scale for reference image matching")
    parser.add_argument("--scale-step", type=float, default=0.05, help="Scale step for reference image matching")
    parser.add_argument("--from-page", type=int, default=None, help="First page to scan, 1-based")
    parser.add_argument("--to-page", type=int, default=None, help="Last page to scan, 1-based")
    parser.add_argument("--start-band", default="0,1", help="Vertical search band for start marker as top,bottom fractions, e.g. 0,0.5")
    parser.add_argument("--end-band", default="0,1", help="Vertical search band for end marker as top,bottom fractions, e.g. 0.4,1")
    parser.add_argument("--verbose", action="store_true", help="Print match scores for every scanned page")

    args = parser.parse_args(argv)

    input_pdf = Path(args.input_pdf)
    if not input_pdf.exists():
        print(f"Input PDF not found: {input_pdf}", file=sys.stderr)
        return 2

    try:
        start_band = tuple(float(x.strip()) for x in args.start_band.split(",", 1))
        end_band = tuple(float(x.strip()) for x in args.end_band.split(",", 1))
        if len(start_band) != 2 or len(end_band) != 2:
            raise ValueError
        if not (0 <= start_band[0] < start_band[1] <= 1 and 0 <= end_band[0] < end_band[1] <= 1):
            raise ValueError
    except Exception:
        print("Bands must be two fractions in 0..1, for example --start-band 0,0.6 --end-band 0.4,1", file=sys.stderr)
        return 2

    doc = fitz.open(input_pdf)
    try:
        page_count = len(doc)
        from_page = parse_page_number(args.from_page, page_count, 1)
        to_page = parse_page_number(args.to_page, page_count, page_count)
        if from_page > to_page:
            print("from-page cannot be greater than to-page", file=sys.stderr)
            return 2

        start_ref = load_ref_gray(Path(args.start_ref))
        end_ref = load_ref_gray(Path(args.end_ref))
        scales = make_scales(args.scale_min, args.scale_max, args.scale_step)

        if args.verbose:
            print(f"Scanning pages {from_page}-{to_page} of {page_count}, dpi={args.dpi}, threshold={args.threshold}")
            print(f"Scales: {scales[0]}..{scales[-1]} step ~{args.scale_step}")

        start_matches = find_matches(
            doc, start_ref, args.dpi, args.threshold, scales, from_page, to_page, start_band, "START", args.verbose
        )
        end_matches = find_matches(
            doc, end_ref, args.dpi, args.threshold, scales, from_page, to_page, end_band, "END", args.verbose
        )

        fragments = build_fragments(start_matches, end_matches, args.start_variant)

        if not fragments:
            print("No fragments found.")
            print("Try one or more of these:")
            print("  1) crop cleaner reference images from the PDF page itself")
            print("  2) lower threshold, for example: --threshold 0.45")
            print("  3) widen scale range: --scale-min 0.35 --scale-max 2.50")
            print("  4) add --verbose and inspect match scores")
            print("  5) limit pages if you know the range: --from-page 454 --to-page 463")
            return 1

        for frag in fragments:
            print(
                f"fragment {frag.index:03d} -> variant {frag.variant}: "
                f"pages {frag.start_page}-{frag.end_page}; "
                f"start_score={frag.start.score:.3f}; end_score={frag.end.score:.3f}"
            )

        if args.report_only:
            return 0

        out_dir = Path(args.split_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        filenames: List[str] = []

        for frag in fragments:
            num = str(frag.variant).zfill(args.digits) if args.digits > 0 else str(frag.variant)
            filename = normalize_text_for_filename(f"{args.prefix}-{num}.pdf")
            out_path = out_dir / filename
            if args.mode == "pages":
                export_pages_fragment(doc, frag, out_path, args.visible_stamp)
            else:
                export_crop_fragment(doc, frag, out_path, args.visible_stamp, include_start_marker=not args.exclude_start_marker)
            filenames.append(filename)
            print(f"written: {out_path}")

        write_manifest(out_dir / "manifest.csv", fragments, filenames)
        print(f"manifest: {out_dir / 'manifest.csv'}")
        return 0
    finally:
        doc.close()


if __name__ == "__main__":
    raise SystemExit(main())
