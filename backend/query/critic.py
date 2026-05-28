from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from backend.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CriticResult:
    quality_score: float
    feedback: str  # FR-47b: textual reasoning


class CriticAgent(Protocol):
    def evaluate(self, query: str, answer: str, sources: list) -> CriticResult: ...


class MockCriticAgent:
    """Deterministic critic for local-lite / test mode.

    Score is proportional to number of sources (1.0 base + 0.5 per source, max 4.0).
    Feedback explains the reasoning so the UI / Langfuse trace shows human-readable text.
    """

    def evaluate(self, query: str, answer: str, sources: list) -> CriticResult:
        n = len(sources)
        score = round(1.0 + min(n * 0.5, 3.0), 1)

        if n == 0:
            feedback = (
                "No sources retrieved. The corpus may not contain relevant information "
                "for this query. Consider expanding the knowledge base."
            )
        elif score < 2.0:
            feedback = (
                f"Low quality: only {n} source(s) found. Answer lacks sufficient "
                "supporting evidence. Retry may improve results."
            )
        elif score < 3.0:
            feedback = (
                f"Moderate quality: {n} source(s) retrieved. Answer is partially "
                "supported but could benefit from additional context."
            )
        else:
            feedback = (
                f"Good quality: {n} source(s) retrieved with strong relevance. "
                "Answer is well-supported by the corpus."
            )

        return CriticResult(quality_score=score, feedback=feedback)


def _parse_score_and_feedback(raw: str) -> tuple[float, str]:
    """Extract score and feedback from 'ЧИСЛО | ПОЯСНЕНИЕ' LLM response.

    Handles:
      "3.5 | Ответ ссылается на INS-HR-001, но не раскрывает шаги"  → (3.5, "Ответ ссылается...")
      "3.5"                                                           → (3.5, "")
      "Оценка: 3.5"                                                   → (3.5, "")
    """
    if "|" in raw:
        score_part, feedback_part = raw.split("|", 1)
        score = _parse_score(score_part.strip())
        feedback = feedback_part.strip()
    else:
        score = _parse_score(raw)
        feedback = ""
    return score, feedback


def _parse_score(raw: str) -> float:
    """Extract a numeric score in [1.0, 4.0] from an LLM response string.

    Handles common vLLM output variations:
      - plain number: "3.5"
      - comma decimal (Russian locale): "3,5"
      - text with embedded number: "Оценка: 3.5", "Score: 3.5"
      - markdown bold: "**3.5**"
      - trailing newlines / whitespace (already stripped by caller)

    Raises ValueError only if no number is found at all.
    """
    # Normalise comma-as-decimal-separator (Russian/European locale)
    normalised = raw.replace(",", ".")
    # Try direct parse first (fastest path)
    try:
        return max(1.0, min(4.0, float(normalised)))
    except ValueError:
        pass
    # Regex: find first occurrence of d[.d] in range 1–4
    match = re.search(r"\b([1-4](?:\.\d+)?)\b", normalised)
    if match:
        return max(1.0, min(4.0, float(match.group(1))))
    # Broader fallback: any decimal number in the string
    match = re.search(r"\d+(?:\.\d+)?", normalised)
    if match:
        return max(1.0, min(4.0, float(match.group())))
    raise ValueError(f"[critic] cannot extract numeric score from: {raw!r}")


class VLLMCriticAgent:
    """LLM-based quality critic for gpu-demo mode (llm_backend=vllm).

    Uses the pooled sync httpx.Client (get_pool().http) so the LangGraph
    sync critic node does not open new TCP connections per evaluation call.

    Scoring scale (matches MockCriticAgent for threshold continuity):
      4.0 — full answer, well-supported by sources
      3.0 — partial answer, some relevant sources
      2.0 — weak answer, sources marginally relevant
      1.0 — no answer or no sources retrieved

    Falls back to MockCriticAgent on any vLLM error so the pipeline
    continues — the source-count heuristic will still trigger a retry or
    knowledge_gap if the answer is genuinely poor.
    """

    _SYSTEM_PROMPT = (
        "Ты оцениваешь качество ответа корпоративного AI-ассистента. "
        "Верни ответ строго в формате: ЧИСЛО | ПОЯСНЕНИЕ\n"
        "где ЧИСЛО — оценка от 1.0 до 4.0, ПОЯСНЕНИЕ — одно предложение на русском.\n\n"
        "Шкала:\n"
        "4.0 — полный конкретный ответ, цитирует документы, все ключевые детали есть\n"
        "3.0 — частичный ответ, упоминает документы, но не все детали раскрыты\n"
        "2.0 — слабый ответ, общие слова без ссылок на источники\n"
        "1.0 — нет ответа, «информация не найдена» или источников 0\n\n"
        "Примеры:\n"
        "Вопрос: «Кто отвечает за онбординг?»\n"
        "Ответ: «Согласно INS-HR-001, ответственность несёт HR-менеджер.» Источников: 3\n"
        "→ 4.0 | Конкретный ответ с указанием документа и ответственного лица\n\n"
        "Вопрос: «Какой бюджет на найм в 2026 году?»\n"
        "Ответ: «Информация отсутствует в базе знаний.» Источников: 0\n"
        "→ 1.0 | Ответ отсутствует, релевантных документов не найдено\n\n"
        "Вопрос: «Как проходит код-ревью?»\n"
        "Ответ: «Код-ревью проводится перед мержем. Нужно соблюдать стандарты.» Источников: 2\n"
        "→ 2.0 | Ответ слишком общий, не ссылается на конкретный стандарт"
    )

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(self, query: str, answer: str, sources: list) -> CriticResult:
        from backend.core.connections import get_pool

        n = len(sources)
        source_list = (
            "\n".join(f"- [{s.doc_id}] {s.section_title}" for s in sources[:5])
            if n
            else "Нет источников."
        )
        user_msg = (
            f"Вопрос: {query}\n\n"
            f"Ответ: {answer[:800]}\n\n"
            f"Источники ({n} шт.):\n{source_list}\n\n"
            "Оцени от 1.0 до 4.0. Верни строго в формате: ЧИСЛО | ПОЯСНЕНИЕ"
        )

        try:
            resp = get_pool().http.post(
                f"{self._settings.vllm_host}/v1/chat/completions",
                json={
                    "model": self._settings.vllm_model,
                    "messages": [
                        {"role": "system", "content": self._SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 80,  # score (≤5 tok) + " | " + one Russian sentence (≤70 tok)
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            logger.debug("[critic] vLLM raw response: %r", raw)
            score, feedback = _parse_score_and_feedback(raw)
            if not feedback:
                feedback = f"Оценка {score:.1f} / 4.0 ({n} источн.)"
            logger.info("[critic] vLLM score=%.1f feedback=%r", score, feedback[:60])
            return CriticResult(
                quality_score=round(score, 1),
                feedback=feedback,
            )
        except Exception as exc:
            logger.warning(
                "[critic] vLLM scoring failed (%s) — falling back to source-count heuristic", exc
            )
            return MockCriticAgent().evaluate(query, answer, sources)


def get_critic(settings: Settings) -> CriticAgent:
    """Return the appropriate critic for the active LLM backend.

    vllm  → VLLMCriticAgent  (LLM-scored, uses pooled sync http client)
    mock  → MockCriticAgent   (deterministic source-count heuristic)
    """
    if settings.llm_backend == "vllm":
        return VLLMCriticAgent(settings)
    return MockCriticAgent()
