from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


def _abs(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else _PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    bot_token: str
    gemini_api_key: str
    gemini_model: str
    dataset_path: Path
    report_path: Path
    out_dir: Path
    db_path: Path
    admin_user_id: int | None


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
        dataset_path=_abs(os.getenv("DATASET_PATH", "data/positions.json")),
        report_path=_abs(os.getenv("REPORT_PATH", "out/report.json")),
        out_dir=_abs(os.getenv("OUT_DIR", "out")),
        db_path=_abs(os.getenv("DB_PATH", "bot.sqlite3")),
        admin_user_id=int(os.getenv("ADMIN_USER_ID")) if os.getenv("ADMIN_USER_ID") else None,
    )
