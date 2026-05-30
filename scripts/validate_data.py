from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POSITIONS = ROOT / "data" / "positions.json"
REPORT = ROOT / "out" / "report.json"
OUT = ROOT / "out"


def main() -> None:
    positions = json.loads(POSITIONS.read_text(encoding="utf-8"))
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    variants = {int(x["variant"]): x for x in positions.get("variants", [])}
    report_items = {int(x["number"]): x for x in report.get("ok", [])}

    print(f"positions variants: {len(variants)}")
    print(f"report items:       {len(report_items)}")

    missing_in_report = sorted(set(variants) - set(report_items))
    missing_in_positions = sorted(set(report_items) - set(variants))

    if missing_in_report:
        print("Missing in report:", missing_in_report)
    if missing_in_positions:
        print("Missing in positions:", missing_in_positions)

    missing_texts = []
    missing_screens = []

    for number, item in sorted(report_items.items()):
        text_file = item.get("text_file", "")
        screenshot = item.get("screenshot", "")

        if not text_file or not (OUT / "texts" / text_file).exists():
            missing_texts.append(number)
        if not screenshot or not (OUT / "screens" / screenshot).exists():
            missing_screens.append(number)

    print(f"missing texts:      {len(missing_texts)}")
    if missing_texts:
        print(missing_texts)

    print(f"missing screens:    {len(missing_screens)}")
    if missing_screens:
        print(missing_screens)

    if len(variants) == 50 and len(report_items) == 50 and not missing_in_report and not missing_in_positions:
        print("DATASET_MAP_OK")
    else:
        print("DATASET_MAP_HAS_PROBLEMS")

    if not missing_texts and not missing_screens:
        print("OUT_FILES_OK")
    else:
        print("OUT_FILES_MISSING_COPY_TEXTS_AND_SCREENS")


if __name__ == "__main__":
    main()
