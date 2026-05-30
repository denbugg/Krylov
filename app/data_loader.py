from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class VariantTask:
    variant: int
    problem: str
    author_position: str
    topic: str
    title: str = ""
    url: str = ""
    text_file: str = ""
    screenshot: str = ""


class TaskRepository:
    def __init__(self, dataset_path: Path, report_path: Path, out_dir: Path):
        self.dataset_path = dataset_path
        self.report_path = report_path
        self.out_dir = out_dir
        self.tasks: Dict[int, VariantTask] = self._load()

    def _load(self) -> Dict[int, VariantTask]:
        with self.dataset_path.open("r", encoding="utf-8") as f:
            positions = json.load(f)

        if "variants" not in positions:
            raise ValueError(f"{self.dataset_path} must contain key 'variants'")

        report_by_number = {}
        if self.report_path.exists():
            with self.report_path.open("r", encoding="utf-8") as f:
                report = json.load(f)
            for item in report.get("ok", []):
                try:
                    num = int(item["number"])
                except (KeyError, ValueError, TypeError):
                    continue
                report_by_number[num] = item

        tasks: Dict[int, VariantTask] = {}
        for item in positions["variants"]:
            variant = int(item["variant"])
            report_item = report_by_number.get(variant, {})
            tasks[variant] = VariantTask(
                variant=variant,
                problem=item.get("problem", "").strip(),
                author_position=item.get("author_position", "").strip(),
                topic=item.get("topic", "").strip(),
                title=report_item.get("title", "").strip(),
                url=report_item.get("url", "").strip(),
                text_file=report_item.get("text_file", "").strip(),
                screenshot=report_item.get("screenshot", "").strip(),
            )

        return dict(sorted(tasks.items()))

    def get(self, variant: int) -> VariantTask:
        if variant not in self.tasks:
            raise KeyError(f"Variant {variant} not found")
        return self.tasks[variant]

    def all(self) -> List[VariantTask]:
        return list(self.tasks.values())

    def text_path(self, task: VariantTask) -> Path:
        return self.out_dir / "texts" / task.text_file

    def screenshot_path(self, task: VariantTask) -> Path:
        return self.out_dir / "screens" / task.screenshot

    def has_text(self, task: VariantTask) -> bool:
        return bool(task.text_file) and self.text_path(task).exists()

    def has_screenshot(self, task: VariantTask) -> bool:
        return bool(task.screenshot) and self.screenshot_path(task).exists()
