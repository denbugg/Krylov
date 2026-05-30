#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract EGE text fragments from a PDF.

Main modes:
  1) Merge all found fragments into one PDF.
  2) Split fragments into separate PDFs and name them by variant number.

Default extraction mode: full pages containing each fragment.
Optional extraction mode: visual crop between the start marker and task 23 marker.

Examples:
  python3 extract_ege_fragments.py input.pdf --split-dir out --start-variant 10
  python3 extract_ege_fragments.py input.pdf --split-dir out --start-variant 10 --mode crop
  python3 extract_ege_fragments.py input.pdf merged.pdf
  python3 extract_ege_fragments.py input.pdf --report-only --start-variant 10
"""

import argparse
import csv
import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("PyMuPDF is not installed. Run: python3 -m pip install pymupdf", file=sys.stderr)
    sys.exit(2)

START_MARKERS = [
    "прочитайте текст и выполните задания",
    "прочитайте текст",
]

END_MARKERS = [
    "23. какие из высказываний соответствуют содержанию текста",
    "какие из высказываний соответствуют содержанию текста",
    "какие из высказываний",
]

START_SEARCH_TERMS = ["Прочитайте текст", "Прочитайте", "прочитайте"]
END_SEARCH_TERMS = ["Какие из высказываний", "высказываний", "23."]

DEFAULT_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def normalize_text(s: str) -> str:
    s = s.lower().replace("ё", "е")
    s = s.replace("–", "-").replace("—", "-").replace("−", "-")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def has_marker(page_text: str, markers) -> bool:
    t = normalize_text(page_text)
    return any(m in t for m in markers)


def find_marker_rect(page, terms, prefer="first"):
    rects = []
    for term in terms:
        try:
            found = page.search_for(term)
        except Exception:
            found = []
        if found:
            rects.extend(found)
            break
    if not rects:
        return None
    rects = sorted(rects, key=lambda r: (r.y0, r.x0))
    return rects[0] if prefer == "first" else rects[-1]


def find_ranges(doc):
    texts = [page.get_text("text") or "" for page in doc]
    start_pages = [i for i, text in enumerate(texts) if has_marker(text, START_MARKERS)]
    if not start_pages:
        return [], texts

    ranges = []
    for idx, start in enumerate(start_pages):
        next_start = start_pages[idx + 1] if idx + 1 < len(start_pages) else len(doc)
        end = None
        for pno in range(start, next_start):
            if has_marker(texts[pno], END_MARKERS):
                end = pno
                break
        if end is None:
            # Fallback: take pages until the page before the next start marker.
            end = max(start, next_start - 1)
        ranges.append((start, end))
    return ranges, texts


def make_fragment_doc(src, start, end, mode="pages", margin=4):
    out = fitz.open()

    if mode == "pages":
        out.insert_pdf(src, from_page=start, to_page=end)
        return out

    for pno in range(start, end + 1):
        page = src[pno]
        clip = fitz.Rect(page.rect)

        if pno == start:
            r = find_marker_rect(page, START_SEARCH_TERMS, prefer="first")
            if r is not None:
                clip.y0 = min(page.rect.y1, r.y1 + margin)

        if pno == end:
            r = find_marker_rect(page, END_SEARCH_TERMS, prefer="first")
            if r is not None:
                clip.y1 = max(page.rect.y0, r.y0 - margin)

        if clip.y1 - clip.y0 < 20 or clip.x1 - clip.x0 < 20:
            # If crop became invalid, do not silently create an empty page.
            continue

        new_page = out.new_page(width=clip.width, height=clip.height)
        new_page.show_pdf_page(new_page.rect, src, pno, clip=clip)

    if len(out) == 0:
        raise RuntimeError("No cropped pages were created; try --mode pages")
    return out


def find_fontfile():
    for item in DEFAULT_FONT_CANDIDATES:
        path = Path(item)
        if path.exists():
            return str(path)
    return None


def stamp_first_page(doc, label):
    if len(doc) == 0:
        return
    page = doc[0]
    rect = fitz.Rect(24, 18, min(page.rect.x1 - 24, 260), 50)
    fontfile = find_fontfile()
    kwargs = {
        "fontsize": 13,
        "align": fitz.TEXT_ALIGN_LEFT,
    }
    if fontfile:
        kwargs["fontfile"] = fontfile
        kwargs["fontname"] = "dejavu"
    try:
        page.insert_textbox(rect, label, **kwargs)
    except Exception:
        # Fallback: avoid failing extraction only because visible stamping failed.
        page.insert_textbox(rect, str(label).encode("ascii", "ignore").decode("ascii"), fontsize=13)


def save_fragment(src, start, end, output_path, mode="pages", stamp_label=None):
    out = make_fragment_doc(src, start, end, mode=mode)
    if stamp_label:
        stamp_first_page(out, stamp_label)
    out.save(str(output_path), garbage=4, deflate=True)
    page_count = len(out)
    out.close()
    return page_count


def save_merged(src, ranges, output_path, mode="pages"):
    out = fitz.open()
    for start, end in ranges:
        fragment = make_fragment_doc(src, start, end, mode=mode)
        out.insert_pdf(fragment)
        fragment.close()
    if len(out) == 0:
        raise RuntimeError("No pages were selected")
    out.save(str(output_path), garbage=4, deflate=True)
    page_count = len(out)
    out.close()
    return page_count


def format_variant_name(prefix, variant_no, digits):
    if digits > 0:
        return f"{prefix}-{variant_no:0{digits}d}.pdf"
    return f"{prefix}-{variant_no}.pdf"


def print_report(ranges, start_variant=1):
    if not ranges:
        print("No fragments found.")
        return
    print(f"Found fragments: {len(ranges)}")
    for i, (start, end) in enumerate(ranges, start=1):
        variant_no = start_variant + i - 1
        print(f"fragment {i:03d} -> variant {variant_no}: pages {start + 1}-{end + 1}")


def write_manifest(output_dir, rows):
    manifest_path = output_dir / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["fragment_no", "variant_no", "first_page", "last_page", "pages_count", "filename"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return manifest_path


def split_to_files(src, ranges, output_dir, start_variant=1, prefix="variant", digits=2, mode="pages", visible_stamp=False):
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []

    for idx, (start, end) in enumerate(ranges, start=1):
        variant_no = start_variant + idx - 1
        filename = format_variant_name(prefix, variant_no, digits)
        output_path = output_dir / filename
        stamp_label = f"Вариант {variant_no}" if visible_stamp else None
        pages_count = save_fragment(src, start, end, output_path, mode=mode, stamp_label=stamp_label)
        rows.append({
            "fragment_no": idx,
            "variant_no": variant_no,
            "first_page": start + 1,
            "last_page": end + 1,
            "pages_count": pages_count,
            "filename": filename,
        })
        print(f"Saved variant {variant_no}: {output_path}")

    manifest_path = write_manifest(output_dir, rows)
    print(f"Saved manifest: {manifest_path}")
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_pdf", help="Source PDF")
    parser.add_argument("output_pdf", nargs="?", help="Merged output PDF. Not needed with --split-dir")
    parser.add_argument("--split-dir", help="Directory for separate variant PDFs")
    parser.add_argument("--start-variant", type=int, default=1, help="First variant number for split files and reports")
    parser.add_argument("--prefix", default="variant", help="Output filename prefix, for example variant or variant_text")
    parser.add_argument("--digits", type=int, default=2, help="Zero-padding width for variant numbers; use 0 to disable")
    parser.add_argument("--mode", choices=["pages", "crop"], default="pages", help="pages = full pages, crop = visual crop between markers")
    parser.add_argument("--visible-stamp", action="store_true", help="Add visible 'Вариант N' label to the first page of each separate PDF")
    parser.add_argument("--report-only", action="store_true", help="Only print found page ranges")
    args = parser.parse_args()

    input_path = Path(args.input_pdf)
    if not input_path.exists():
        print(f"Input PDF not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if args.digits < 0:
        print("--digits must be >= 0", file=sys.stderr)
        sys.exit(1)

    doc = fitz.open(str(input_path))
    ranges, texts = find_ranges(doc)
    print_report(ranges, start_variant=args.start_variant)

    if not ranges:
        print("Markers were not found in the text layer. If this is a scan, run OCR first.", file=sys.stderr)
        doc.close()
        sys.exit(1)

    if args.report_only:
        doc.close()
        return

    try:
        if args.split_dir:
            split_to_files(
                doc,
                ranges,
                Path(args.split_dir),
                start_variant=args.start_variant,
                prefix=args.prefix,
                digits=args.digits,
                mode=args.mode,
                visible_stamp=args.visible_stamp,
            )
        else:
            output_pdf = Path(args.output_pdf or "ege_fragments.pdf")
            pages_count = save_merged(doc, ranges, output_pdf, mode=args.mode)
            print(f"Saved merged PDF: {output_pdf} ({pages_count} pages)")
    finally:
        doc.close()


if __name__ == "__main__":
    main()
