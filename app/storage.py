from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

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

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    variant INTEGER,
                    meta_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_events_user_type
                    ON events(user_id, event_type);

                CREATE INDEX IF NOT EXISTS idx_events_type_created
                    ON events(event_type, created_at);
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

    async def log_event(
        self,
        user_id: int,
        event_type: str,
        variant: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO events (user_id, event_type, variant, meta_json) VALUES (?, ?, ?, ?)",
                (user_id, event_type, variant, json.dumps(meta) if meta else None),
            )
            await db.commit()

    async def get_aggregate_stats(self) -> dict[str, Any]:
        async with aiosqlite.connect(self.db_path) as db:
            # unique users who ever did something
            cur = await db.execute("SELECT COUNT(DISTINCT user_id) FROM events")
            total_users = int((await cur.fetchone())[0])

            # funnel: unique users per key event
            funnel_events = ("session_start", "task_shown", "answer_start", "answer_submitted", "gemini_ok")
            funnel: dict[str, int] = {}
            for evt in funnel_events:
                cur = await db.execute(
                    "SELECT COUNT(DISTINCT user_id) FROM events WHERE event_type = ?", (evt,)
                )
                funnel[evt] = int((await cur.fetchone())[0])

            # total attempts & avg score
            cur = await db.execute("SELECT COUNT(*), AVG(author_score) FROM attempts")
            row = await cur.fetchone()
            total_attempts = int(row[0] or 0)
            avg_score = float(row[1] or 0)

            # score distribution: 0-1, 1-2, 2-3
            cur = await db.execute(
                """
                SELECT
                    SUM(CASE WHEN author_score < 1 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN author_score >= 1 AND author_score < 2 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN author_score >= 2 AND author_score < 3 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN author_score >= 3 THEN 1 ELSE 0 END)
                FROM attempts
                """
            )
            dist = await cur.fetchone()
            score_dist = {"0–1": int(dist[0] or 0), "1–2": int(dist[1] or 0),
                          "2–3": int(dist[2] or 0), "3": int(dist[3] or 0)}

            # Gemini confidence distribution
            cur = await db.execute(
                """
                SELECT
                    SUM(CASE WHEN confidence < 0.5 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN confidence >= 0.5 AND confidence < 0.8 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN confidence >= 0.8 THEN 1 ELSE 0 END)
                FROM attempts
                """
            )
            conf = await cur.fetchone()
            confidence_dist = {"low<0.5": int(conf[0] or 0), "mid0.5–0.8": int(conf[1] or 0),
                               "high≥0.8": int(conf[2] or 0)}

            # gemini error count
            cur = await db.execute("SELECT COUNT(*) FROM events WHERE event_type = 'gemini_error'")
            gemini_errors = int((await cur.fetchone())[0])

            # cancelled count
            cur = await db.execute("SELECT COUNT(*) FROM events WHERE event_type = 'cancelled'")
            cancellations = int((await cur.fetchone())[0])

            # hardest variants (lowest avg score across all users, min 2 attempts)
            cur = await db.execute(
                """
                SELECT variant, COUNT(*) AS cnt, AVG(author_score) AS avg
                FROM attempts
                GROUP BY variant
                HAVING cnt >= 2
                ORDER BY avg ASC
                LIMIT 5
                """
            )
            hard_variants = [(int(r[0]), int(r[1]), float(r[2])) for r in await cur.fetchall()]

            # format preference: text vs screenshot reads
            cur = await db.execute("SELECT COUNT(*) FROM events WHERE event_type = 'format_text'")
            fmt_text = int((await cur.fetchone())[0])
            cur = await db.execute("SELECT COUNT(*) FROM events WHERE event_type = 'format_screen'")
            fmt_screen = int((await cur.fetchone())[0])

            # answer length stats
            cur = await db.execute(
                "SELECT AVG(LENGTH(student_answer)), MIN(LENGTH(student_answer)), MAX(LENGTH(student_answer)) FROM attempts"
            )
            row = await cur.fetchone()
            answer_len = {"avg": int(row[0] or 0), "min": int(row[1] or 0), "max": int(row[2] or 0)}

        return {
            "total_users": total_users,
            "funnel": funnel,
            "total_attempts": total_attempts,
            "avg_score": avg_score,
            "score_dist": score_dist,
            "confidence_dist": confidence_dist,
            "gemini_errors": gemini_errors,
            "cancellations": cancellations,
            "hard_variants": hard_variants,
            "format_pref": {"text": fmt_text, "screen": fmt_screen},
            "answer_len": answer_len,
        }
