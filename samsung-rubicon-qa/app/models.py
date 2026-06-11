"""Dataclasses used by the Samsung Rubicon QA workflow."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.error_taxonomy import determine_primary_error_category


def _detect_text_language(question: str, locale: str = "") -> str:
    normalized_locale = (locale or "").lower()
    if normalized_locale.startswith("ko"):
        return "ko"
    if normalized_locale.startswith("en"):
        return "en"
    if len(re.findall(r"[가-힣]", question or "")) >= 3:
        return "ko"
    return "en"


def _looks_english_heavy(text: str) -> bool:
    lowered = str(text or "").lower()
    english_words = re.findall(r"\b[a-z]{3,}\b", lowered)
    return len(english_words) >= 3 and not re.search(r"[가-힣]", lowered)


def _looks_korean_heavy(text: str) -> bool:
    return len(re.findall(r"[가-힣]", str(text or ""))) >= 3


def _language_policy_check(question: str, locale: str, reason: str, fix_suggestion: str) -> str:
    target_language = _detect_text_language(question, locale)
    combined = " ".join(part for part in [reason, fix_suggestion] if part).strip()
    if not combined:
        return "pass"
    if target_language == "ko":
        return "pass" if _looks_korean_heavy(combined) else "fail"
    return "fail" if _looks_korean_heavy(combined) else "pass"


def _serialize_cleaning_applied(ui_noise_stripped: bool, cta_stripped: bool, promo_stripped: bool) -> str:
    applied: list[str] = []
    if ui_noise_stripped:
        applied.append("ui_noise_stripped")
    if cta_stripped:
        applied.append("cta_stripped")
    if promo_stripped:
        applied.append("promo_stripped")
    return "|".join(applied)


@dataclass(slots=True)
class TestCase:
    """Single chatbot QA scenario loaded from CSV."""

    id: str
    category: str
    locale: str
    page_url: str
    question: str
    expected_keywords: list[str] = field(default_factory=list)
    forbidden_keywords: list[str] = field(default_factory=list)
    scenario_type: Literal["spec", "comparison", "policy_sensitive", "noise_sensitive"] = "spec"
    product_family: str = "unknown"
    released_override: bool = False
    policy_tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CandidateAnswer:
    raw_text: str
    cleaned_text: str
    source: str
    score: float
    rank: int = 0
    keyword_coverage: float = 0.0
    is_question_repetition: bool = False
    has_ui_noise: bool = False
    has_followup_cta: bool = False
    has_promo_or_review: bool = False
    is_truncated: bool = False
    topic_family_match: bool = True
    is_stale_vs_baseline: bool = False
    length_score: float = 0.0
    completeness_score: float = 0.0


@dataclass(slots=True)
class ExtractedPair:
    """Structured question-answer pair extracted from the browser UI."""

    run_timestamp: str
    case_id: str
    category: str
    page_url: str
    locale: str
    question: str
    answer: str
    extraction_source: Literal["dom", "ocr", "unknown"]
    extraction_confidence: float
    response_ms: int
    status: Literal["passed", "retry_extraction", "invalid_answer", "failed", "invalid_capture"]
    run_status: Literal["run_ok", "run_failed"] = "run_ok"
    extraction_status: Literal["not_started", "extracted", "retry_extraction", "invalid_answer", "extraction_failed"] = "not_started"
    acceptance_status: Literal["accepted", "rejected"] = "rejected"
    quality_status: Literal["quality_passed", "quality_review", "quality_failed"] = "quality_review"
    primary_error_category: str = "(none)"
    raw_answer: str = ""
    cleaned_answer: str = ""
    final_answer: str = ""
    answer_raw: str = ""
    answer_normalized: str = ""
    actual_answer: str = ""
    actual_answer_clean: str = ""
    extraction_source_detail: str = ""
    message_history_clean: str = ""
    ui_noise_stripped: bool = False
    cta_stripped: bool = False
    promo_stripped: bool = False
    removed_followups: bool = False
    noise_lines_removed: int = 0
    reason: str = ""
    error_message: str = ""
    run_mode: str = "speed"
    fast_path_used: bool = False
    full_screenshot_path: str = ""
    chat_screenshot_path: str = ""
    submitted_chat_screenshot_path: str = ""
    answered_chat_screenshot_path: str = ""
    video_path: str = ""
    trace_path: str = ""
    html_fragment_path: str = ""
    evidence_markdown_path: str = ""
    evidence_json_path: str = ""
    fix_suggestion: str = ""
    input_dom_verified: bool = False
    submit_effect_verified: bool = False
    input_verified: bool = False
    input_method_used: str = ""
    submit_method_used: str = "unknown"
    opened_chat_screenshot_path: str = ""
    opened_full_screenshot_path: str = ""
    opened_footer_screenshot_path: str = ""
    open_method_used: str = ""
    sdk_status: str = ""
    availability_status: str = ""
    input_scope: str = ""
    input_scope_name: str = ""
    input_selector: str = ""
    input_failure_category: str = ""
    input_failure_reason: str = ""
    input_candidate_score: float = 0.0
    top_candidate_disabled: bool = False
    top_candidate_placeholder: str = ""
    top_candidate_aria: str = ""
    input_ready_wait_result: str = ""
    transition_wait_attempted: bool = False
    transition_ready: bool = False
    transition_timeout: bool = False
    transition_reason: str = ""
    transition_history: str = ""
    activation_attempted: bool = False
    activation_steps_tried: str = ""
    editable_candidates_count: int = 0
    failover_attempts: int = 0
    final_input_target_frame: str = ""
    input_candidates_debug: str = ""
    input_candidate_logs: list[str] = field(default_factory=list)
    before_send_screenshot_path: str = ""
    before_send_full_screenshot_path: str = ""
    after_send_screenshot_path: str = ""
    after_send_full_screenshot_path: str = ""
    after_answer_screenshot_path: str = ""
    after_answer_full_screenshot_path: str = ""
    font_fix_applied: bool = False
    user_message_echo_verified: bool = False
    new_bot_response_detected: bool = False
    baseline_menu_detected: bool = False
    answer_screenshot_paths: list[str] = field(default_factory=list)
    after_answer_multi_page: bool = False
    ocr_text: str = ""
    ocr_confidence: float = 0.0
    structured_message_history_count: int = 0
    fallback_diff_used: bool = False
    question_repetition_detected: bool = False
    truncated_detected: bool = False
    truncated_answer_detected: bool = False
    carryover_detected: bool = False
    stale_answer_detected: bool = False
    keyword_coverage_score: float = 0.0
    needs_retry_extraction: bool = False
    candidate_count: int = 0
    selected_candidate_rank: int = 0
    released_override: bool = False
    evaluator_version: str = ""
    extractor_version: str = ""
    harness_version: str = ""
    message_history: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.final_answer:
            self.final_answer = self.cleaned_answer or self.actual_answer_clean or self.actual_answer or self.answer
        if self.run_status == "run_ok" and self.status in {"failed", "invalid_capture"}:
            self.run_status = "run_failed"
        if self.extraction_status == "not_started":
            if self.status == "retry_extraction":
                self.extraction_status = "retry_extraction"
            elif self.status == "invalid_answer":
                self.extraction_status = "invalid_answer"
            elif self.final_answer or self.answer_raw:
                self.extraction_status = "extracted"
            elif self.status == "failed":
                self.extraction_status = "extraction_failed"
        if self.status == "passed" and self.acceptance_status == "rejected":
            self.acceptance_status = "accepted"
        if self.status == "passed" and self.primary_error_category == "(none)":
            self.primary_error_category = "(none)"

    @property
    def debug_raw_answer(self) -> str:
        return self.raw_answer or self.answer_raw

    @property
    def debug_cleaned_answer(self) -> str:
        return self.cleaned_answer or self.actual_answer_clean or self.final_answer or self.answer

    @property
    def raw_clean_diff(self) -> str:
        raw_answer = self.debug_raw_answer
        cleaned_answer = self.debug_cleaned_answer
        if raw_answer and cleaned_answer and raw_answer != cleaned_answer:
            return "cleaned"
        return "same"

    @property
    def cleaning_applied(self) -> str:
        return _serialize_cleaning_applied(self.ui_noise_stripped, self.cta_stripped, self.promo_stripped)


@dataclass(slots=True)
class EvalResult:
    """LLM evaluation outcome for an extracted pair."""

    overall_score: float
    score_scale: str
    evaluation_language: Literal["ko", "en"]
    correctness_score: float
    relevance_score: float
    completeness_score: float
    clarity_score: float
    groundedness_score: float
    score_breakdown_explanation: str
    keyword_alignment_score: float
    hallucination_risk: Literal["low", "medium", "high"]
    needs_human_review: bool
    reason: str
    fix_suggestion: str
    flags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeMetadata:
    """Runtime metadata captured at execution start for reproducibility."""

    branch: str = "unknown"
    commit_sha: str = "unknown"
    extractor_version: str = "unknown"
    evaluator_version: str = "unknown"
    harness_version: str = "unknown"
    run_mode: str = "unknown"


@dataclass(slots=True)
class HarnessSummary:
    total_cases: int = 0
    run_ok_count: int = 0
    answer_extracted_count: int = 0
    answer_accepted_count: int = 0
    quality_passed_count: int = 0
    retry_extraction_count: int = 0
    invalid_answer_count: int = 0
    ui_noise_leak_count: int = 0
    truncation_count: int = 0
    carryover_count: int = 0
    speculative_count: int = 0
    human_review_count: int = 0
    accepted_rate: float = 0.0
    quality_pass_rate: float = 0.0
    invalid_answer_rate: float = 0.0
    primary_error_distribution: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class RunResult:
    """Combined execution and evaluation result for a test case."""

    test_case: TestCase
    pair: ExtractedPair
    evaluation: EvalResult
    runtime_metadata: RuntimeMetadata | None = None

    @property
    def run_status(self) -> str:
        return self.pair.run_status

    @property
    def extraction_status(self) -> str:
        return self.pair.extraction_status

    @property
    def acceptance_status(self) -> str:
        return self.pair.acceptance_status

    @property
    def quality_status(self) -> str:
        return self.pair.quality_status

    @staticmethod
    def _serialize_flags(flags: list[str]) -> str:
        return "|".join(flags)

    def to_nested_dict(self) -> dict[str, Any]:
        """Convert the result to a JSON-serializable dictionary."""

        return {
            "test_case": asdict(self.test_case),
            "pair": asdict(self.pair),
            "evaluation": asdict(self.evaluation),
            "runtime_metadata": asdict(self.runtime_metadata) if self.runtime_metadata is not None else None,
        }

    def to_flat_dict(self) -> dict[str, Any]:
        """Flatten the result for CSV output."""

        data = asdict(self.test_case)
        record = self.to_result_record()
        data.update({key: value for key, value in record.items() if key != "evaluation"})
        data.update({f"pair_{key}": value for key, value in asdict(self.pair).items()})
        evaluation_dict = asdict(self.evaluation)
        evaluation_dict["flags"] = self._serialize_flags(self.evaluation.flags)
        data.update({f"eval_{key}": value for key, value in evaluation_dict.items()})
        return data

    def to_result_record(self) -> dict[str, Any]:
        """Build the primary result payload consumed by reports/latest_results.json."""

        evaluation_reason = self.evaluation.reason or self.pair.reason
        evaluation_fix_suggestion = self.evaluation.fix_suggestion or self.pair.fix_suggestion
        serialized_flags = self._serialize_flags(self.evaluation.flags)
        final_answer = self.pair.final_answer
        language_policy = _language_policy_check(
            self.pair.question,
            self.pair.locale,
            evaluation_reason,
            evaluation_fix_suggestion,
        )
        error_category = determine_primary_error_category(
            self.evaluation.flags,
            extraction_status=self.pair.extraction_status,
            acceptance_status=self.pair.acceptance_status,
            run_status=self.pair.run_status,
        )
        runtime_metadata = asdict(self.runtime_metadata) if self.runtime_metadata is not None else {}

        return {
            "run_timestamp": self.pair.run_timestamp,
            "case_id": self.pair.case_id,
            "category": self.pair.category,
            "page_url": self.pair.page_url,
            "locale": self.pair.locale,
            "question": self.pair.question,
            "answer": final_answer,
            "final_answer": final_answer,
            "raw_answer": self.pair.debug_raw_answer,
            "cleaned_answer": self.pair.debug_cleaned_answer,
            "answer_raw": self.pair.answer_raw,
            "answer_normalized": self.pair.answer_normalized,
            "actual_answer": self.pair.actual_answer or final_answer,
            "actual_answer_clean": self.pair.actual_answer_clean or self.pair.actual_answer or final_answer,
            "input_dom_verified": self.pair.input_dom_verified,
            "submit_effect_verified": self.pair.submit_effect_verified,
            "input_verified": self.pair.input_verified,
            "run_status": self.pair.run_status,
            "extraction_status": self.pair.extraction_status,
            "acceptance_status": self.pair.acceptance_status,
            "quality_status": self.pair.quality_status,
            "input_method_used": self.pair.input_method_used,
            "submit_method_used": self.pair.submit_method_used,
            "user_message_echo_verified": self.pair.user_message_echo_verified,
            "new_bot_response_detected": self.pair.new_bot_response_detected,
            "baseline_menu_detected": self.pair.baseline_menu_detected,
            "status": self.pair.status,
            "error_message": self.pair.error_message,
            "reason": evaluation_reason,
            "execution_reason": self.pair.reason,
            "primary_error_category": self.pair.primary_error_category or error_category,
            "run_mode": self.pair.run_mode,
            "fast_path_used": self.pair.fast_path_used,
            "fix_suggestion": evaluation_fix_suggestion,
            "execution_fix_suggestion": self.pair.fix_suggestion,
            "flags": serialized_flags,
            "raw_clean_diff": self.pair.raw_clean_diff,
            "cleaning_applied": self.pair.cleaning_applied or "(none)",
            "message_history": self.pair.message_history,
            "message_history_clean": self.pair.message_history_clean,
            "html_fragment_path": self.pair.html_fragment_path,
            "evidence_markdown_path": self.pair.evidence_markdown_path,
            "evidence_json_path": self.pair.evidence_json_path,
            "extraction_source": self.pair.extraction_source,
            "extraction_source_detail": self.pair.extraction_source_detail,
            "cta_stripped": self.pair.cta_stripped,
            "promo_stripped": self.pair.promo_stripped,
            "removed_followups": self.pair.removed_followups,
            "noise_lines_removed": self.pair.noise_lines_removed,
            "ocr_text": self.pair.ocr_text,
            "ocr_confidence": self.pair.ocr_confidence,
            "structured_message_history_count": self.pair.structured_message_history_count,
            "fallback_diff_used": self.pair.fallback_diff_used,
            "ui_noise_stripped": self.pair.ui_noise_stripped,
            "question_repetition_detected": self.pair.question_repetition_detected,
            "truncated_detected": self.pair.truncated_detected,
            "truncated_answer_detected": self.pair.truncated_answer_detected,
            "carryover_detected": self.pair.carryover_detected,
            "stale_answer_detected": self.pair.stale_answer_detected,
            "keyword_coverage_score": self.pair.keyword_coverage_score,
            "needs_retry_extraction": self.pair.needs_retry_extraction,
            "candidate_count": self.pair.candidate_count,
            "selected_candidate_rank": self.pair.selected_candidate_rank,
            "released_override": self.pair.released_override,
            "extractor_version": self.pair.extractor_version,
            "evaluator_version": self.pair.evaluator_version,
            "harness_version": self.pair.harness_version,
            "input_scope": self.pair.input_scope or self.pair.input_scope_name,
            "input_selector": self.pair.input_selector,
            "input_candidate_score": self.pair.input_candidate_score,
            "input_failure_category": self.pair.input_failure_category,
            "input_failure_reason": self.pair.input_failure_reason,
            "top_candidate_disabled": self.pair.top_candidate_disabled,
            "top_candidate_placeholder": self.pair.top_candidate_placeholder,
            "top_candidate_aria": self.pair.top_candidate_aria,
            "input_ready_wait_result": self.pair.input_ready_wait_result,
            "transition_wait_attempted": self.pair.transition_wait_attempted,
            "transition_ready": self.pair.transition_ready,
            "transition_timeout": self.pair.transition_timeout,
            "transition_reason": self.pair.transition_reason,
            "transition_history": self.pair.transition_history,
            "activation_attempted": self.pair.activation_attempted,
            "activation_steps_tried": self.pair.activation_steps_tried,
            "editable_candidates_count": self.pair.editable_candidates_count,
            "failover_attempts": self.pair.failover_attempts,
            "final_input_target_frame": self.pair.final_input_target_frame,
            "open_method_used": self.pair.open_method_used,
            "sdk_status": self.pair.sdk_status,
            "availability_status": self.pair.availability_status,
            "input_candidates_debug": self.pair.input_candidates_debug,
            "before_send_screenshot_path": self.pair.before_send_screenshot_path,
            "submitted_chat_screenshot_path": self.pair.submitted_chat_screenshot_path,
            "after_send_screenshot_path": self.pair.after_send_screenshot_path,
            "answered_chat_screenshot_path": self.pair.answered_chat_screenshot_path,
            "after_answer_screenshot_path": self.pair.after_answer_screenshot_path,
            "answer_screenshot_paths": self.pair.answer_screenshot_paths,
            "after_answer_multi_page": self.pair.after_answer_multi_page,
            "error_category": error_category,
            "language_policy_check": language_policy,
            "full_screenshot_path": self.pair.full_screenshot_path,
            "overall_score": self.evaluation.overall_score,
            "score_scale": self.evaluation.score_scale,
            "evaluation_language": self.evaluation.evaluation_language,
            "correctness_score": self.evaluation.correctness_score,
            "needs_human_review": self.evaluation.needs_human_review,
            "relevance_score": self.evaluation.relevance_score,
            "completeness_score": self.evaluation.completeness_score,
            "clarity_score": self.evaluation.clarity_score,
            "groundedness_score": self.evaluation.groundedness_score,
            "score_breakdown_explanation": self.evaluation.score_breakdown_explanation,
            "response_ms": self.pair.response_ms,
            "extraction_confidence": self.pair.extraction_confidence,
            "opened_chat_screenshot_path": self.pair.opened_chat_screenshot_path,
            "opened_full_screenshot_path": self.pair.opened_full_screenshot_path,
            "opened_footer_screenshot_path": self.pair.opened_footer_screenshot_path,
            "input_scope_name": self.pair.input_scope_name,
            "input_candidate_logs": self.pair.input_candidate_logs,
            "before_send_full_screenshot_path": self.pair.before_send_full_screenshot_path,
            "after_send_full_screenshot_path": self.pair.after_send_full_screenshot_path,
            "after_answer_full_screenshot_path": self.pair.after_answer_full_screenshot_path,
            "chat_screenshot_path": self.pair.chat_screenshot_path,
            "video_path": self.pair.video_path,
            "trace_path": self.pair.trace_path,
            "evaluation": asdict(self.evaluation),
            **runtime_metadata,
        }


@dataclass(slots=True)
class ResolvedChatContext:
    """Resolved chat widget references for the current case."""

    scope: Any
    scope_name: str
    input_locator: Any | None
    send_locator: Any | None
    container_locator: Any | None
    bot_message_candidates: list[dict[str, Any]]
    history_candidates: list[dict[str, Any]]
    loading_candidates: list[dict[str, Any]]
    page: Any | None = None
    input_scope: Any | None = None
    input_scope_name: str = ""
    input_selector: str = ""
    input_failure_category: str = ""
    input_failure_reason: str = ""
    frame_inventory: list[dict[str, Any]] = field(default_factory=list)
    ranked_input_candidates: list[dict[str, Any]] = field(default_factory=list)
    input_candidates_debug: str = ""
    baseline_bot_count: int = 0
    baseline_bot_messages: list[str] = field(default_factory=list)
    baseline_last_answer: str = ""
    baseline_topic_family: str = "unknown"
    baseline_history: list[str] = field(default_factory=list)
    baseline_visible_text: str = ""
    baseline_message_nodes_snapshot: list[str] = field(default_factory=list)
    baseline_visible_blocks: list[str] = field(default_factory=list)
    baseline_send_button_enabled: bool | None = None
    chat_frame_score: int = 0
    input_candidate_score: float = 0.0
    input_candidate_logs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BrowserArtifacts:
    """File paths captured during or after a case run."""

    fullpage_screenshot: Path | None = None
    chatbox_screenshot: Path | None = None
    video_path: Path | None = None
    trace_path: Path | None = None
    html_fragment_path: Path | None = None
    before_send_screenshot_path: Path | None = None
