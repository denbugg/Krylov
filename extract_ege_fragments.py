#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract EGE text fragments from a PDF into one PDF.

Default mode: full pages containing each fragment.
Optional mode: visual crop between the start marker and task 23 marker.

Usage:
  python3 extract_ege_fragments.py input.pdf output.pdf
  python3 extract_ege_fragments.py input.pdf output.pdf --mode crop
  python3 extract_ege_fragments.py input.pdf output.pdf --report-only
"""

import argparse
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
        for p in range(start, next_start):
            if has_marker(texts[p], END_MARKERS):
                end = p
                break
        if end is None:
            # Fallback: take pages until the page before the next start marker.
            end = max(start, next_start - 1)
        ranges.append((start, end))
    return ranges, texts


def copy_full_pages(src, ranges, output_path):
    out = fitz.open()
    for n, (start, end) in enumerate(ranges, start=1):
        out.insert_pdf(src, from_page=start, to_page=end)
    if len(out) == 0:
        raise RuntimeError("No pages were selected")
    out.save(output_path, garbage=4, deflate=True)
    out.close()


def copy_cropped_fragments(src, ranges, output_path, margin=4):
    out = fitz.open()
    for frag_no, (start, end) in enumerate(ranges, start=1):
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
    out.save(output_path, garbage=4, deflate=True)
    out.close()


def print_report(ranges):
    if not ranges:
        print("No fragments found.")
        return
    print(f"Found fragments: {len(ranges)}")
    for i, (start, end) in enumerate(ranges, start=1):
        print(f"{i:03d}: pages {start + 1}-{end + 1}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_pdf", help="Source PDF")
    parser.add_argument("output_pdf", nargs="?", default="ege_fragments.pdf", help="Output PDF")
    parser.add_argument("--mode", choices=["pages", "crop"], default="pages", help="pages = full pages, crop = visual crop between markers")
    parser.add_argument("--report-only", action="store_true", help="Only print found page ranges")
    args = parser.parse_args()

    input_path = Path(args.input_pdf)
    if not input_path.exists():
        print(f"Input PDF not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    doc = fitz.open(str(input_path))
    ranges, texts = find_ranges(doc)
    print_report(ranges)

    if not ranges:
        print("Markers were not found in the text layer. If this is a scan, run OCR first.", file=sys.stderr)
        doc.close()
        sys.exit(1)

    if args.report_only:
        doc.close()
        return

    if args.mode == "pages":
        copy_full_pages(doc, ranges, args.output_pdf)
    else:
        copy_cropped_fragments(doc, ranges, args.output_pdf)

    doc.close()
    print(f"Saved: {args.output_pdf}")


if __name__ == "__main__":
    main()
