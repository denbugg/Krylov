# -*- coding: utf-8 -*-
"""
capture_4ege_text_screens.py

Автоматически:
1) открывает страницу со списком вариантов 1–50;
2) собирает ссылки под цифровыми кнопками;
3) переходит в каждую ссылку;
4) пытается нажать раскрывающийся блок "Текст";
5) извлекает фрагмент от "Текст:" до "Напишите сочинение...";
6) сохраняет PNG-скриншот этого фрагмента;
7) складывает PNG, TXT и JSON-карту ссылок в ZIP.

Запуск:
  py -m pip install playwright
  py -m playwright install chromium
  py capture_4ege_text_screens.py --url "https://4ege.ru/russkiy/76504-sochinenija-k-sborniku-ra-doschinskogo-50-variantov-ege-2026.html?ysclid=mpst3c2my6359558868"

Результат:
  out/4ege_doschinsky_text_screens.zip
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


DEFAULT_URL = "https://4ege.ru/russkiy/76504-sochinenija-k-sborniku-ra-doschinskogo-50-variantov-ege-2026.html?ysclid=mpst3c2my6359558868"


@dataclass
class VariantLink:
    number: int
    title: str
    url: str


def safe_name(value: str, max_len: int = 90) -> str:
    value = re.sub(r"[^\wа-яА-ЯёЁ.-]+", "_", value, flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("_.")
    return value[:max_len] or "file"


def normalize_lines(text: str) -> str:
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[ \t\xa0]+", " ", line).strip()
        if line:
            lines.append(line)
        elif lines and lines[-1] != "":
            lines.append("")
    # убираем длинные пачки пустых строк
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def close_overlays(page) -> None:
    """Аккуратно закрывает типовые всплывающие элементы, если они есть."""
    selectors = [
        "text=✖",
        "text=×",
        "text=Закрыть",
        "text=Понятно",
        "text=Согласен",
        "text=Принять",
        ".mfp-close",
        ".modal .close",
        ".popup .close",
        "[aria-label='Close']",
        "[aria-label='Закрыть']",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=500):
                loc.click(timeout=800)
                page.wait_for_timeout(300)
        except Exception:
            pass


def collect_links(page, index_url: str) -> List[VariantLink]:
    page.goto(index_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1200)
    close_overlays(page)

    raw = page.locator("a").evaluate_all(
        """
        els => els.map(a => ({
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href || ''
        }))
        """
    )

    links: Dict[int, str] = {}
    for item in raw:
        text = (item.get("text") or "").strip()
        href = (item.get("href") or "").strip()
        if re.fullmatch(r"[1-9]|[1-4][0-9]|50", text) and "/sochinen" in href:
            n = int(text)
            links.setdefault(n, href)

    missing = [n for n in range(1, 51) if n not in links]
    if missing:
        raise RuntimeError(
            "Не удалось собрать все ссылки 1–50. "
            f"Отсутствуют номера: {missing}. "
            "Возможно, изменилась верстка страницы или сайт временно отдал неполную страницу."
        )

    return [VariantLink(n, "", links[n]) for n in range(1, 51)]


def try_open_text_spoiler(page) -> None:
    """
    Пытается раскрыть блок 'Текст', если он свернут.
    На некоторых страницах текст уже присутствует в DOM и виден сразу.
    """
    candidates = [
        "text=/^\\s*Текст\\s*$/i",
        "text=/^\\s*Текст:\\s*$/i",
        "a:has-text('Текст')",
        "button:has-text('Текст')",
        ".spoiler-title:has-text('Текст')",
        ".title_spoiler:has-text('Текст')",
        "[onclick*='spoiler']:has-text('Текст')",
        "[onclick*='ShowOrHide']:has-text('Текст')",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=600):
                loc.click(timeout=1200)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def best_content_text(page) -> str:
    """
    Берет самый короткий контейнер, где одновременно есть 'Текст' и 'Напишите сочинение'.
    Это обычно основная статья, а не вся страница с меню и футером.
    """
    selectors = [
        "article",
        "#dle-content",
        ".fullstory",
        ".full-story",
        ".fullnews",
        ".full-news",
        ".story",
        ".entry",
        ".entry-content",
        ".news",
        ".basecont",
        "main",
        "body",
    ]

    candidates: List[str] = []
    for sel in selectors:
        try:
            loc = page.locator(sel)
            count = min(loc.count(), 20)
            for i in range(count):
                txt = loc.nth(i).inner_text(timeout=1500)
                if "Текст" in txt and "Напишите сочинение" in txt:
                    candidates.append(txt)
        except Exception:
            pass

    if not candidates:
        try:
            return page.locator("body").inner_text(timeout=4000)
        except Exception:
            return ""

    return min(candidates, key=len)


def extract_source_text(full_text: str) -> str:
    text = normalize_lines(full_text)

    # Основной вариант: от "Текст:" до задания на сочинение.
    patterns = [
        r"(?:^|\n)\s*Текст:?\s*\n?(.*?)(?=\n\s*Напишите\s+сочинение)",
        r"(?:^|\n)\s*Текст:?\s*\n?(.*?)(?=\n\s*Как[^\n]{0,160}\?\s*$)",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return normalize_lines(m.group(1))

    # Запасной вариант: после "Текст:" до первого блока сочинения.
    m = re.search(r"Текст:?\s*(.*)", text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        tail = m.group(1)
        tail = re.split(
            r"\n\s*(?:Напишите\s+сочинение|По\s+мнению\s+писателя|Приведу\s+примеры|Таким\s+образом)",
            tail,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        return normalize_lines(tail)

    raise RuntimeError("Не найден фрагмент исходного текста на странице.")


def get_title(page) -> str:
    title = ""
    try:
        h1 = page.locator("h1").first
        if h1.count():
            title = h1.inner_text(timeout=1200).strip()
    except Exception:
        pass
    if not title:
        try:
            title = page.title().strip()
        except Exception:
            title = "Без названия"
    return normalize_lines(title).split("\n")[0]


def render_text_screenshot(browser, number: int, title: str, url: str, text: str, png_path: Path) -> None:
    """
    Делает чистый PNG-скриншот фрагмента.
    Это не скрин всей страницы с рекламой и меню, а именно раскрытого текстового блока.
    """
    page = browser.new_page(viewport={"width": 1180, "height": 900}, device_scale_factor=1)
    escaped_title = html.escape(title)
    escaped_url = html.escape(url)
    paragraphs = []
    for block in re.split(r"\n\s*\n", text.strip()):
        block = block.strip()
        if not block:
            continue
        paragraphs.append(f"<p>{html.escape(block).replace(chr(10), '<br>')}</p>")

    body = "\n".join(paragraphs) or "<p>Текст не извлечен.</p>"
    page.set_content(f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Вариант {number}: текст</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 34px;
    background: #f4f4f4;
    font-family: Arial, Helvetica, sans-serif;
    color: #111;
  }}
  .card {{
    width: 1040px;
    margin: 0 auto;
    background: #fff;
    border: 1px solid #d6d6d6;
    border-radius: 14px;
    padding: 30px 34px;
    box-shadow: 0 8px 28px rgba(0,0,0,.08);
  }}
  .variant {{
    font-size: 18px;
    line-height: 1.35;
    color: #666;
    margin-bottom: 8px;
  }}
  h1 {{
    font-size: 28px;
    line-height: 1.25;
    margin: 0 0 10px;
  }}
  .url {{
    font-size: 13px;
    line-height: 1.35;
    color: #777;
    word-break: break-all;
    border-bottom: 1px solid #e8e8e8;
    padding-bottom: 18px;
    margin-bottom: 22px;
  }}
  .label {{
    font-size: 22px;
    font-weight: 700;
    margin: 0 0 16px;
  }}
  p {{
    font-size: 20px;
    line-height: 1.55;
    margin: 0 0 16px;
  }}
</style>
</head>
<body>
  <div class="card">
    <div class="variant">Вариант {number}</div>
    <h1>{escaped_title}</h1>
    <div class="url">{escaped_url}</div>
    <div class="label">Текст:</div>
    {body}
  </div>
</body>
</html>""", wait_until="load")
    page.screenshot(path=str(png_path), full_page=True)
    page.close()


def process_variant(browser, variant: VariantLink, out_dir: Path) -> Dict[str, str]:
    page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
    page.goto(variant.url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1000)
    close_overlays(page)
    try_open_text_spoiler(page)
    page.wait_for_timeout(500)

    title = get_title(page)
    full_text = best_content_text(page)
    source_text = extract_source_text(full_text)

    stem = f"{variant.number:02d}_{safe_name(title, 70)}"
    txt_path = out_dir / "texts" / f"{stem}.txt"
    png_path = out_dir / "screens" / f"{stem}.png"

    txt_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.parent.mkdir(parents=True, exist_ok=True)

    txt_path.write_text(
        f"Вариант {variant.number}\n{title}\n{variant.url}\n\nТекст:\n{source_text}\n",
        encoding="utf-8",
    )
    render_text_screenshot(browser, variant.number, title, variant.url, source_text, png_path)
    page.close()

    return {
        "number": str(variant.number),
        "title": title,
        "url": variant.url,
        "text_file": str(txt_path.name),
        "screenshot": str(png_path.name),
    }


def make_zip(out_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out_dir.rglob("*")):
            if p.is_file() and p != zip_path:
                z.write(p, p.relative_to(out_dir))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL, help="Страница со списком вариантов 1–50.")
    parser.add_argument("--out", default="out", help="Папка результата.")
    parser.add_argument("--headful", action="store_true", help="Показать браузер во время работы.")
    parser.add_argument("--slow", type=int, default=0, help="Замедление Playwright в миллисекундах.")
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "screens").mkdir(parents=True, exist_ok=True)
    (out_dir / "texts").mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, str]] = []
    errors: List[Dict[str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headful, slow_mo=args.slow)
        page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
        print("Собираю ссылки 1–50...")
        variants = collect_links(page, args.url)
        page.close()

        mapping = {str(v.number): v.url for v in variants}
        (out_dir / "links_1_50.json").write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        for v in variants:
            print(f"[{v.number:02d}/50] {v.url}")
            try:
                item = process_variant(browser, v, out_dir)
                results.append(item)
            except Exception as exc:
                errors.append({"number": str(v.number), "url": v.url, "error": repr(exc)})
                print(f"  ОШИБКА: {exc}", file=sys.stderr)

        browser.close()

    report = {"ok": results, "errors": errors}
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    zip_path = out_dir / "4ege_doschinsky_text_screens.zip"
    make_zip(out_dir, zip_path)

    print("")
    print(f"Готово: {zip_path}")
    print(f"Скриншотов: {len(results)}")
    print(f"Ошибок: {len(errors)}")
    if errors:
        print("См. out/report.json")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
