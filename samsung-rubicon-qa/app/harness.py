"""Harness orchestration helpers layered above browser execution."""

from __future__ import annotations

from dataclasses import replace

from app.error_taxonomy import (
    CARRYOVER_CONTAMINATION,
    INVALID_ANSWER,
    PROMO_OR_REVIEW_LEAK,
    QUESTION_REPETITION,
    TRUNCATED_ANSWER,
    determine_primary_error_category,
    normalize_error_flag,
)
from app.models import EvalResult, ExtractedPair, HarnessSummary, RunResult, TestCase

HARNESS_VERSION = "harness-v1.0"

HARD_QUALITY_FLAGS = {
    QUESTION_REPETITION,
    CARRYOVER_CONTAMINATION,
    INVALID_ANSWER,
    TRUNCATED_ANSWER,
}


def finalize_pair_for_harness(test_case: TestCase, pair: ExtractedPair, evaluation: EvalResult) -> ExtractedPair:
    normalized_flags = [normalize_error_flag(flag) for flag in evaluation.flags if normalize_error_flag(flag)]
    run_status = "run_failed" if pair.status in {"failed", "invalid_capture"} else "run_ok"

    if pair.cleaned_answer or pair.actual_answer_clean or pair.answer_raw:
        extraction_status = "extracted"
    else:
        extraction_status = "extraction_failed"
    if pair.status == "retry_extraction":
        extraction_status = "retry_extraction"
    elif pair.status == "invalid_answer":
        extraction_status = "invalid_answer"
    elif pair.status == "failed" and extraction_status == "extracted":
        extraction_status = "extraction_failed"

    acceptance_status = "accepted" if pair.status == "passed" else "rejected"

    quality_status = "quality_review"
    if pair.status == "passed" and not any(flag in normalized_flags for flag in HARD_QUALITY_FLAGS) and evaluation.overall_score >= 7.0:
        quality_status = "quality_passed"
    elif pair.status in {"invalid_answer", "retry_extraction", "failed", "invalid_capture"} or any(
        flag in normalized_flags for flag in HARD_QUALITY_FLAGS
    ):
        quality_status = "quality_failed"

    primary_error_category = determine_primary_error_category(
        normalized_flags,
        extraction_status=extraction_status,
        acceptance_status=acceptance_status,
        run_status=run_status,
    )

    return replace(
        pair,
        run_status=run_status,
        extraction_status=extraction_status,
        acceptance_status=acceptance_status,
        quality_status=quality_status,
        primary_error_category=primary_error_category,
        final_answer=pair.cleaned_answer or pair.actual_answer_clean or pair.actual_answer or pair.answer,
        stale_answer_detected=pair.stale_answer_detected or pair.carryover_detected,
        evaluator_version=getattr(pair, "evaluator_version", "") or "evaluator-v2.4",
        extractor_version=getattr(pair, "extractor_version", "") or "dom-extractor-v2.4",
        harness_version=HARNESS_VERSION,
        released_override=test_case.released_override,
    )


def build_harness_summary(results: list[RunResult]) -> HarnessSummary:
    total = len(results)
    run_ok = sum(1 for item in results if item.pair.run_status == "run_ok")
    answer_extracted = sum(1 for item in results if item.pair.extraction_status in {"extracted", "retry_extraction", "invalid_answer"})
    answer_accepted = sum(1 for item in results if item.pair.acceptance_status == "accepted")
    quality_passed = sum(1 for item in results if item.pair.quality_status == "quality_passed")
    retry_extraction = sum(1 for item in results if item.pair.extraction_status == "retry_extraction")
    invalid_answer = sum(1 for item in results if item.pair.extraction_status == "invalid_answer")
    ui_noise_leak = sum(1 for item in results if item.pair.primary_error_category == "ui_noise_leak")
    truncation = sum(1 for item in results if item.pair.primary_error_category == TRUNCATED_ANSWER)
    carryover = sum(1 for item in results if item.pair.primary_error_category == CARRYOVER_CONTAMINATION)
    speculative = sum(1 for item in results if item.pair.primary_error_category == "speculative_unverified")
    human_review = sum(1 for item in results if item.evaluation.needs_human_review)
    primary_error_distribution: dict[str, int] = {}
    for item in results:
        category = item.pair.primary_error_category or "(none)"
        primary_error_distribution[category] = primary_error_distribution.get(category, 0) + 1

    return HarnessSummary(
        total_cases=total,
        run_ok_count=run_ok,
        answer_extracted_count=answer_extracted,
        answer_accepted_count=answer_accepted,
        quality_passed_count=quality_passed,
        retry_extraction_count=retry_extraction,
        invalid_answer_count=invalid_answer,
        ui_noise_leak_count=ui_noise_leak,
        truncation_count=truncation,
        carryover_count=carryover,
        speculative_count=speculative,
        human_review_count=human_review,
        accepted_rate=(answer_accepted / total) if total else 0.0,
        quality_pass_rate=(quality_passed / total) if total else 0.0,
        invalid_answer_rate=(invalid_answer / total) if total else 0.0,
        primary_error_distribution=primary_error_distribution,
    )