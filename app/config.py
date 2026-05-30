from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    gemini_api_key: str
    gemini_model: str
    dataset_path: Path
    report_path: Path
    out_dir: Path
    db_path: Path


def get_settings() -> Settings:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not bot_token:
        raise RuntimeError("BOT_TOKEN is empty. Set it in .env")
    if not gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is empty. Set it in .env")

    return Settings(
        bot_token=bot_token,
        gemini_api_key=gemini_api_key,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip(),
        dataset_path=Path(os.getenv("DATASET_PATH", "data/positions.json")),
        report_path=Path(os.getenv("REPORT_PATH", "out/report.json")),
        out_dir=Path(os.getenv("OUT_DIR", "out")),
        db_path=Path(os.getenv("DB_PATH", "bot.sqlite3")),
    )
