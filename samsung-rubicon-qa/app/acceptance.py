"""Acceptance gate for extracted answers in the Rubicon harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import AppConfig
from app.error_taxonomy import (
    CARRYOVER_CONTAMINATION,
    CTA_LEAK,
    INVALID_ANSWER,
    LOW_CONFIDENCE_EXTRACTION,
    QUESTION_REPETITION,
    TOPIC_MISMATCH,
    TRUNCATED_ANSWER,
    UI_NOISE_LEAK,
    determine_primary_error_category,
)


@dataclass(slots=True)
class AcceptanceDecision:
    accepted: bool
    acceptance_status: str
    extraction_status: str
    rejection_reasons: list[str] = field(default_factory=list)
    primary_error_category: str = "(none)"
    keyword_coverage_score: float = 0.0
    reason: str = ""
    fix_suggestion: str = ""


def _reason_text(reasons: list[str]) -> str:
    if not reasons:
        return "Harness acceptance gate accepted the cleaned answer"
    return f"Harness acceptance gate rejected answer: {'|'.join(reasons)}"


def _fix_text(reasons: list[str]) -> str:
    if QUESTION_REPETITION in reasons:
        return "질문 반복 후보를 버리고 실제 답변 본문만 채택하세요."
    if CARRYOVER_CONTAMINATION in reasons or TOPIC_MISMATCH in reasons:
        return "이전 케이스 문맥을 제거하고 현재 질문 기준으로 DOM 재추출하세요."
    if TRUNCATED_ANSWER in reasons:
        return "응답 안정화를 한 번 더 기다린 뒤 완결된 후보만 채택하세요."
    return "정리된 본문이 길이와 키워드 기준을 만족하는 후보만 채택하세요."


def assess_answer_acceptance(
    question: str,
    dom_payload: dict[str, Any],
    config: AppConfig,
) -> AcceptanceDecision:
    cleaned_answer = str(dom_payload.get("cleaned_answer") or "")
    raw_answer = str(dom_payload.get("raw_answer") or "")
    keyword_coverage_score = float(dom_payload.get("keyword_coverage_score", 0.0) or 0.0)
    reasons: list[str] = []

    if bool(dom_payload.get("question_repetition_detected", False)):
        reasons.append(QUESTION_REPETITION)
    if bool(dom_payload.get("truncated_detected", False)):
        reasons.append(TRUNCATED_ANSWER)
    if bool(dom_payload.get("carryover_detected", False)) or bool(dom_payload.get("stale_answer_detected", False)):
        reasons.append(CARRYOVER_CONTAMINATION)
    if bool(dom_payload.get("topic_mismatch_detected", False)):
        reasons.append(TOPIC_MISMATCH)
    if not cleaned_answer:
        reasons.append(INVALID_ANSWER)
    if len(cleaned_answer) < config.acceptance_min_length:
        reasons.append(LOW_CONFIDENCE_EXTRACTION)
    if keyword_coverage_score < config.acceptance_keyword_threshold:
        reasons.append(LOW_CONFIDENCE_EXTRACTION)
    if raw_answer and cleaned_answer and raw_answer.startswith(cleaned_answer) is False and bool(dom_payload.get("ui_noise_stripped", False)):
        reasons.append(UI_NOISE_LEAK)
    if bool(dom_payload.get("cta_stripped", False)):
        reasons.append(CTA_LEAK)

    deduped_reasons: list[str] = []
    for reason in reasons:
        if reason not in deduped_reasons:
            deduped_reasons.append(reason)

    accepted = not any(reason in deduped_reasons for reason in [
        QUESTION_REPETITION,
        TRUNCATED_ANSWER,
        CARRYOVER_CONTAMINATION,
        TOPIC_MISMATCH,
        INVALID_ANSWER,
        LOW_CONFIDENCE_EXTRACTION,
    ])
    extraction_status = "extracted" if cleaned_answer else "extraction_failed"
    if not accepted:
        if any(reason in deduped_reasons for reason in [QUESTION_REPETITION, CARRYOVER_CONTAMINATION, INVALID_ANSWER, TOPIC_MISMATCH]):
            extraction_status = "invalid_answer"
        elif TRUNCATED_ANSWER in deduped_reasons:
            extraction_status = "retry_extraction" if config.retry_on_truncation else "invalid_answer"
        else:
            extraction_status = "retry_extraction"

    return AcceptanceDecision(
        accepted=accepted,
        acceptance_status="accepted" if accepted else "rejected",
        extraction_status=extraction_status,
        rejection_reasons=deduped_reasons,
        primary_error_category=determine_primary_error_category(deduped_reasons, extraction_status=extraction_status),
        keyword_coverage_score=keyword_coverage_score,
        reason=_reason_text(deduped_reasons),
        fix_suggestion=_fix_text(deduped_reasons),
    )