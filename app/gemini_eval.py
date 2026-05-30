from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict

import aiohttp


SYSTEM_PROMPT = """Ты проверяешь формулировку авторской позиции в сочинении ЕГЭ по русскому языку.

Твоя задача — сравнить ответ ученика с эталонной авторской позицией по смыслу.
Не требуй дословного совпадения.
Не оценивай стиль сочинения, грамотность и аргумент.
Оценивай только то, понял ли ученик позицию автора по проблеме.

Шкала:
0 — мимо: позиция неверна, подмена проблемы, противоречие эталону.
1 — частично: есть одна близкая подтема, но мысль слишком общая, неполная или уводит в сторону.
2 — в целом верно: смысл близкий, но есть заметная неполнота или неточность.
3 — полное смысловое попадание.

Можно ставить вещественную оценку: 0.0, 0.5, 1.5, 2.5 и т. п.
Не завышай оценку за общие слова.
Если ответ ученика слишком общий, но не противоречит эталону, обычно это 1–2 балла.
Если ответ передаёт главное смысловое ядро, это 2.5–3 балла.

Верни только JSON:
{
  "score": 0.0,
  "label": "miss | partial | mostly_correct | correct",
  "confidence": 0.0,
  "matched_points": [],
  "missing_points": [],
  "wrong_points": [],
  "feedback": "",
  "safe_revision": ""
}
"""


@dataclass(frozen=True)
class AuthorPositionResult:
    score: float
    label: str
    confidence: float
    matched_points: list[str]
    missing_points: list[str]
    wrong_points: list[str]
    feedback: str
    safe_revision: str
    raw: Dict[str, Any]


def _clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(3.0, score))


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise ValueError("Gemini did not return JSON")
    return json.loads(match.group(0))


async def evaluate_author_position(
    *,
    api_key: str,
    model: str,
    topic: str,
    problem: str,
    canonical_position: str,
    student_answer: str,
) -> AuthorPositionResult:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    user_payload = {
        "topic": topic,
        "problem": problem,
        "canonical_author_position": canonical_position,
        "student_answer": student_answer,
    }

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": SYSTEM_PROMPT + "\n\nВходные данные:\n" + json.dumps(user_payload, ensure_ascii=False, indent=2)}
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=45)) as resp:
            if resp.status >= 400:
                error_text = await resp.text()
                raise RuntimeError(f"Gemini API error {resp.status}: {error_text[:1000]}")
            data = await resp.json()

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected Gemini response: {data}") from exc

    parsed = _extract_json(text)

    return AuthorPositionResult(
        score=_clamp_score(parsed.get("score")),
        label=str(parsed.get("label", "unknown")),
        confidence=max(0.0, min(1.0, float(parsed.get("confidence", 0.0) or 0.0))),
        matched_points=list(parsed.get("matched_points", []) or []),
        missing_points=list(parsed.get("missing_points", []) or []),
        wrong_points=list(parsed.get("wrong_points", []) or []),
        feedback=str(parsed.get("feedback", "")).strip(),
        safe_revision=str(parsed.get("safe_revision", "")).strip(),
        raw=parsed,
    )
