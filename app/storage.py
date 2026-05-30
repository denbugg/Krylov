from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import aiosqlite


@dataclass(frozen=True)
class LatestScore:
    variant: int
    topic: str
    author_score: float
    updated_at: str


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    variant INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    problem TEXT NOT NULL,
                    student_answer TEXT NOT NULL,
                    author_score REAL NOT NULL,
                    label TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    feedback TEXT NOT NULL,
                    safe_revision TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS latest_scores (
                    user_id INTEGER NOT NULL,
                    variant INTEGER NOT NULL,
                    attempt_id INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    author_score REAL NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, variant)
                );

                CREATE INDEX IF NOT EXISTS idx_attempts_user_created
                    ON attempts(user_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_latest_user_score
                    ON latest_scores(user_id, author_score);
                """
            )
            await db.commit()

    async def save_attempt(
        self,
        *,
        user_id: int,
        variant: int,
        topic: str,
        problem: str,
        student_answer: str,
        author_score: float,
        label: str,
        confidence: float,
        feedback: str,
        safe_revision: str,
        raw: dict,
    ) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                INSERT INTO attempts (
                    user_id, variant, topic, problem, student_answer,
                    author_score, label, confidence, feedback, safe_revision, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    variant,
                    topic,
                    problem,
                    student_answer,
                    author_score,
                    label,
                    confidence,
                    feedback,
                    safe_revision,
                    json.dumps(raw, ensure_ascii=False),
                ),
            )
            attempt_id = cur.lastrowid
            await db.execute(
                """
                INSERT INTO latest_scores (
                    user_id, variant, attempt_id, topic, author_score, updated_at
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, variant)
                DO UPDATE SET
                    attempt_id = excluded.attempt_id,
                    topic = excluded.topic,
                    author_score = excluded.author_score,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, variant, attempt_id, topic, author_score),
            )
            await db.commit()
            return int(attempt_id)

    async def get_done_variants(self, user_id: int) -> set[int]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT variant FROM latest_scores WHERE user_id = ?", (user_id,))
            rows = await cur.fetchall()
        return {int(row[0]) for row in rows}

    async def get_latest_scores(self, user_id: int) -> list[LatestScore]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                SELECT variant, topic, author_score, updated_at
                FROM latest_scores
                WHERE user_id = ?
                ORDER BY author_score ASC, updated_at ASC
                """,
                (user_id,),
            )
            rows = await cur.fetchall()
        return [
            LatestScore(
                variant=int(row[0]),
                topic=str(row[1]),
                author_score=float(row[2]),
                updated_at=str(row[3]),
            )
            for row in rows
        ]

    async def get_last_topic(self, user_id: int) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                SELECT topic
                FROM attempts
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (user_id,),
            )
            row = await cur.fetchone()
        return str(row[0]) if row else None

    async def get_attempt_count(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM attempts WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
        return int(row[0] or 0)

    async def get_topic_stats(self, user_id: int) -> list[tuple[str, int, float]]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                SELECT topic, COUNT(*) AS cnt, AVG(author_score) AS avg_score
                FROM latest_scores
                WHERE user_id = ?
                GROUP BY topic
                ORDER BY avg_score ASC, cnt DESC
                """,
                (user_id,),
            )
            rows = await cur.fetchall()
        return [(str(row[0]), int(row[1]), float(row[2])) for row in rows]
