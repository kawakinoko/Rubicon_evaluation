"""Canonical error taxonomy and priority rules for the Rubicon harness."""

from __future__ import annotations

QUESTION_REPETITION = "question_repetition"
UI_NOISE_LEAK = "ui_noise_leak"
CTA_LEAK = "cta_leak"
PROMO_OR_REVIEW_LEAK = "promo_or_review_leak"
TRUNCATED_ANSWER = "truncated_answer"
CARRYOVER_CONTAMINATION = "carryover_contamination"
TOPIC_MISMATCH = "topic_mismatch"
SPECULATIVE_UNVERIFIED = "speculative_unverified"
LOW_CONFIDENCE_EXTRACTION = "low_confidence_extraction"
INVALID_ANSWER = "invalid_answer"
EXTRACTION_FAILED = "extraction_failed"
WEAK_KEYWORD_ALIGNMENT = "weak_keyword_alignment"

PRIMARY_ERROR_PRIORITY = [
    QUESTION_REPETITION,
    CARRYOVER_CONTAMINATION,
    INVALID_ANSWER,
    TRUNCATED_ANSWER,
    TOPIC_MISMATCH,
    UI_NOISE_LEAK,
    CTA_LEAK,
    PROMO_OR_REVIEW_LEAK,
    SPECULATIVE_UNVERIFIED,
    LOW_CONFIDENCE_EXTRACTION,
]

LEGACY_FLAG_MAP = {
    "off_topic_or_carryover": CARRYOVER_CONTAMINATION,
    "promo_or_product_card_leak": PROMO_OR_REVIEW_LEAK,
    "too_short": LOW_CONFIDENCE_EXTRACTION,
    "timestamp_like": LOW_CONFIDENCE_EXTRACTION,
    "evaluation_failed": LOW_CONFIDENCE_EXTRACTION,
}


def normalize_error_flag(flag: str) -> str:
    normalized = str(flag or "").strip()
    if not normalized:
        return ""
    return LEGACY_FLAG_MAP.get(normalized, normalized)


def determine_primary_error_category(
    flags: list[str],
    *,
    extraction_status: str = "",
    acceptance_status: str = "",
    run_status: str = "",
) -> str:
    normalized_flags = [normalize_error_flag(flag) for flag in flags if normalize_error_flag(flag)]
    for flag in PRIMARY_ERROR_PRIORITY:
        if flag in normalized_flags:
            return flag
    if extraction_status == INVALID_ANSWER or acceptance_status == "rejected":
        return INVALID_ANSWER
    if extraction_status == EXTRACTION_FAILED or run_status == "run_failed":
        return EXTRACTION_FAILED
    return "(none)"