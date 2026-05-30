#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Split EGE PDF fragments into separate PDFs by variant number.

Primary mode: search markers in the embedded PDF text layer.
Fallback: --ocr renders pages and runs Tesseract OCR, then searches markers in OCR text.

Examples, Windows PowerShell:
  py .\extract_ege_variants_ocr_split.py ".\Doschinskii_774_2026.pdf" --report-only --start-variant 10
  py .\extract_ege_variants_ocr_split.py ".\Doschinskii_774_2026.pdf" --ocr --report-only --start-variant 10
  py .\extract_ege_variants_ocr_split.py ".\Doschinskii_774_2026.pdf" --ocr --split-dir ".\variants_texts" --start-variant 10

Dependencies:
  py -m pip install pymupdf pillow pytesseract
  plus installed Tesseract OCR binary with Russian language data.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import fitz  # PyMuPDF
except Exception as exc:  # pragma: no cover
    print("ERROR: PyMuPDF is not installed. Run: py -m pip install pymupdf", file=sys.stderr)
    raise


@dataclass
class Fragment:
    index: int
    variant: int
    start_page: int  # zero-based inclusive
    end_page: int    # zero-based inclusive


def normalize_text(text: str) -> str:
    """Normalize OCR/PDF text for fuzzy marker matching."""
    text = text.lower()
    replacements = {
        "ё": "е",
        "–": "-",
        "—": "-",
        "−": "-",
        "‑": "-",
        "‒": "-",
        "―": "-",
        "«": " ",
        "»": " ",
        "„": " ",
        "“": " ",
        "”": " ",
        "’": " ",
        "`": " ",
        "´": " ",
        "|": " ",
    }
    for a, b in replacements.items():
        text = text.replace(a, b)

    # OCR often confuses digits/letters around task numbers. Keep digits and Cyrillic/Latin letters.
    text = re.sub(r"[^0-9a-zа-я]+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def has_start_marker(norm: str) -> bool:
    # Main exact-ish marker after normalization:
    # "прочитайте текст и выполните задания 23 27"
    if re.search(r"прочита\w*\s+текст\s+и\s+выполн\w*\s+задани\w*\s+23\s+27", norm):
        return True
    # More tolerant: all key pieces on the same page.
    return (
        "прочитайте текст" in norm
        and "выполните задания" in norm
        and re.search(r"\b23\b", norm)
        and re.search(r"\b27\b", norm)
    )


def has_end_marker(norm: str) -> bool:
    # End marker from task 23.
    if re.search(r"\b23\b\s+какие\s+из\s+высказыван\w*\s+соответств\w*\s+содержан\w*\s+текста", norm):
        return True
    # OCR can omit the task number or distort endings.
    return (
        "какие из высказыван" in norm
        and "соответств" in norm
        and "содержан" in norm
        and "текста" in norm
    )


def get_text_layer_by_page(doc: fitz.Document) -> List[str]:
    texts: List[str] = []
    for page in doc:
        try:
            texts.append(page.get_text("text") or "")
        except Exception:
            texts.append("")
    return texts


def configure_tesseract(path: Optional[str]) -> None:
    if not path:
        return
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = path
    except Exception as exc:
        raise RuntimeError("pytesseract is not installed. Run: py -m pip install pytesseract pillow") from exc


def ocr_page_texts(
    doc: fitz.Document,
    lang: str,
    dpi: int,
    tesseract_path: Optional[str] = None,
    pages: Optional[Sequence[int]] = None,
) -> List[str]:
    try:
        from PIL import Image
        import pytesseract
    except Exception as exc:
        raise RuntimeError("OCR mode needs Pillow and pytesseract. Run: py -m pip install pillow pytesseract") from exc

    configure_tesseract(tesseract_path)

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    target_pages = set(pages) if pages is not None else set(range(len(doc)))
    texts = [""] * len(doc)

    print(f"OCR: processing {len(target_pages)} pages at {dpi} dpi, lang={lang} ...", file=sys.stderr)
    for i, page in enumerate(doc):
        if i not in target_pages:
            continue
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        mode = "RGB" if pix.n >= 3 else "L"
        image = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        try:
            text = pytesseract.image_to_string(image, lang=lang)
        except Exception as exc:
            msg = str(exc)
            raise RuntimeError(
                "Tesseract OCR failed. Check that Tesseract is installed and Russian language data is available. "
                f"Original error: {msg}"
            ) from exc
        texts[i] = text or ""
        if (i + 1) % 10 == 0 or i == len(doc) - 1:
            print(f"OCR: {i + 1}/{len(doc)} pages", file=sys.stderr)
    return texts


def find_fragments(texts: Sequence[str], start_variant: int) -> List[Fragment]:
    start_pages: List[int] = []
    end_pages: List[int] = []

    for i, text in enumerate(texts):
        norm = normalize_text(text)
        if has_start_marker(norm):
            start_pages.append(i)
        if has_end_marker(norm):
            end_pages.append(i)

    fragments: List[Fragment] = []
    used_end_pages = set()
    for idx, sp in enumerate(start_pages, start=1):
        ep: Optional[int] = None
        for candidate in end_pages:
            if candidate < sp or candidate in used_end_pages:
                continue
            # Stop before the next start marker if there is one.
            next_start = start_pages[idx] if idx < len(start_pages) else None
            if next_start is not None and candidate >= next_start:
                break
            ep = candidate
            used_end_pages.add(candidate)
            break
        if ep is None:
            # Conservative fallback: stop before next start marker, otherwise same page.
            next_start = start_pages[idx] if idx < len(start_pages) else None
            ep = (next_start - 1) if next_start is not None else sp
        fragments.append(Fragment(idx, start_variant + idx - 1, sp, ep))

    return fragments


def parse_page_ranges(page_ranges: str, start_variant: int) -> List[Fragment]:
    """Parse 1-based ranges like '454-455,456-457,458'."""
    fragments: List[Fragment] = []
    for idx, part in enumerate([p.strip() for p in page_ranges.split(",") if p.strip()], start=1):
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a.strip())
            end = int(b.strip())
        else:
            start = end = int(part)
        if start < 1 or end < start:
            raise ValueError(f"Invalid page range: {part}")
        fragments.append(Fragment(idx, start_variant + idx - 1, start - 1, end - 1))
    return fragments


def stamp_variant(page: fitz.Page, variant: int) -> None:
    rect = fitz.Rect(28, 20, 210, 48)
    page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
    page.insert_textbox(
        rect,
        f"Вариант {variant}",
        fontsize=14,
        fontname="helv",
        color=(0, 0, 0),
        align=fitz.TEXT_ALIGN_LEFT,
        overlay=True,
    )


def write_fragment_pdf(
    src: fitz.Document,
    fragment: Fragment,
    out_path: Path,
    visible_stamp: bool,
) -> None:
    out = fitz.open()
    out.insert_pdf(src, from_page=fragment.start_page, to_page=fragment.end_page)
    if visible_stamp and len(out) > 0:
        stamp_variant(out[0], fragment.variant)
    out.save(str(out_path), garbage=4, deflate=True)
    out.close()


def write_manifest(out_dir: Path, rows: Sequence[Dict[str, str]]) -> None:
    path = out_dir / "manifest.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["fragment", "variant", "source_pages", "output_file"],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(rows)


def print_report(fragments: Sequence[Fragment]) -> None:
    if not fragments:
        print("No fragments found.")
        print("Markers were not found. If the PDF is a scan, run with --ocr or OCR the PDF first.")
        return
    for fr in fragments:
        print(
            f"fragment {fr.index:03d} -> variant {fr.variant}: "
            f"pages {fr.start_page + 1}-{fr.end_page + 1}"
        )
    print(f"Total fragments: {len(fragments)}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Split EGE text fragments into separate PDFs by variant number.")
    parser.add_argument("input_pdf", help="Source PDF file")
    parser.add_argument("output_pdf", nargs="?", help="Optional combined PDF output for all fragments")
    parser.add_argument("--mode", choices=["pages", "crop"], default="pages", help="Extraction mode. OCR fallback supports pages mode.")
    parser.add_argument("--report-only", action="store_true", help="Only print found fragments, do not write PDFs")
    parser.add_argument("--split-dir", help="Directory for separate variant PDFs")
    parser.add_argument("--start-variant", type=int, default=1, help="Number of the first variant")
    parser.add_argument("--prefix", default="variant", help="Output filename prefix")
    parser.add_argument("--digits", type=int, default=2, help="Minimum digits in variant number in filenames")
    parser.add_argument("--visible-stamp", action="store_true", help="Add visible 'Вариант N' stamp to first page")
    parser.add_argument("--ocr", action="store_true", help="Use Tesseract OCR instead of embedded text layer")
    parser.add_argument("--ocr-lang", default="rus", help="Tesseract language, e.g. rus or rus+eng")
    parser.add_argument("--ocr-dpi", type=int, default=200, help="Render DPI for OCR")
    parser.add_argument("--tesseract", help="Path to tesseract.exe if it is not in PATH")
    parser.add_argument("--page-ranges", help="Manual 1-based ranges, e.g. '454-455,456-457'. Bypasses marker detection.")
    args = parser.parse_args(argv)

    src_path = Path(args.input_pdf)
    if not src_path.exists():
        print(f"ERROR: file not found: {src_path}", file=sys.stderr)
        return 2

    src = fitz.open(str(src_path))
    try:
        if args.page_ranges:
            fragments = parse_page_ranges(args.page_ranges, args.start_variant)
        else:
            if args.ocr:
                texts = ocr_page_texts(src, args.ocr_lang, args.ocr_dpi, args.tesseract)
            else:
                texts = get_text_layer_by_page(src)
                total_chars = sum(len(t.strip()) for t in texts)
                if total_chars < max(100, len(src) * 5):
                    print(
                        "WARNING: the PDF text layer looks almost empty. "
                        "Use --ocr or OCR the PDF first.",
                        file=sys.stderr,
                    )
            fragments = find_fragments(texts, args.start_variant)

        print_report(fragments)

        if args.report_only:
            return 0 if fragments else 1
        if not fragments:
            return 1

        if args.split_dir:
            out_dir = Path(args.split_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            rows: List[Dict[str, str]] = []
            for fr in fragments:
                name = f"{args.prefix}-{fr.variant:0{args.digits}d}.pdf"
                out_path = out_dir / name
                write_fragment_pdf(src, fr, out_path, args.visible_stamp)
                rows.append({
                    "fragment": f"{fr.index:03d}",
                    "variant": str(fr.variant),
                    "source_pages": f"{fr.start_page + 1}-{fr.end_page + 1}",
                    "output_file": name,
                })
            write_manifest(out_dir, rows)
            print(f"Wrote {len(fragments)} PDFs to: {out_dir}")
            print(f"Manifest: {out_dir / 'manifest.csv'}")

        if args.output_pdf:
            out = fitz.open()
            for fr in fragments:
                out.insert_pdf(src, from_page=fr.start_page, to_page=fr.end_page)
            out.save(args.output_pdf, garbage=4, deflate=True)
            out.close()
            print(f"Wrote combined PDF: {args.output_pdf}")

        if not args.split_dir and not args.output_pdf:
            print("Nothing written: pass --split-dir or output_pdf, or use --report-only.")

        return 0
    finally:
        src.close()


if __name__ == "__main__":
    raise SystemExit(main())
