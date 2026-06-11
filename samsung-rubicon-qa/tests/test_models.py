"""Tests for the data models."""

from __future__ import annotations

from dataclasses import asdict, replace

import pytest

from app.models import (
    EvalResult,
    ExtractedPair,
    RunResult,
    TestCase,
)
from app.utils import utc_now_timestamp


def _make_test_case(case_id: str = "c01") -> TestCase:
    return TestCase(
        id=case_id,
        category="service",
        locale="ko-KR",
        page_url="https://www.samsung.com/sec/",
        question="배터리 교체는 어디서?",
        expected_keywords=["서비스센터", "배터리"],
        forbidden_keywords=["로그인"],
    )


def _make_pair(case_id: str = "c01") -> ExtractedPair:
    return ExtractedPair(
        run_timestamp=utc_now_timestamp(),
        case_id=case_id,
        category="service",
        page_url="https://www.samsung.com/sec/",
        locale="ko-KR",
        question="배터리 교체는 어디서?",
        answer="서비스센터에서 가능합니다.",
        extraction_source="dom",
        extraction_confidence=1.0,
        response_ms=1000,
        status="passed",
        raw_answer="서비스센터에서 가능합니다.",
        cleaned_answer="서비스센터에서 가능합니다.",
        answer_raw="서비스센터에서 가능합니다.",
        answer_normalized="서비스센터에서 가능합니다.",
        actual_answer="서비스센터에서 가능합니다.",
        actual_answer_clean="서비스센터에서 가능합니다.",
    )


def _make_eval() -> EvalResult:
    return EvalResult(
        overall_score=8.7,
        score_scale="0-10",
        evaluation_language="ko",
        correctness_score=3.6,
        relevance_score=1.8,
        completeness_score=1.7,
        clarity_score=0.8,
        groundedness_score=0.8,
        score_breakdown_explanation="질문 의도에 맞는 정보를 충분히 제공했습니다.",
        keyword_alignment_score=8.7,
        hallucination_risk="low",
        needs_human_review=False,
        reason="질문에 맞는 답변입니다.",
        fix_suggestion="",
        flags=[],
    )


class TestTestCase:
    def test_fields(self):
        case = _make_test_case()
        assert case.id == "c01"
        assert case.expected_keywords == ["서비스센터", "배터리"]
        assert case.forbidden_keywords == ["로그인"]


class TestExtractedPair:
    def test_default_optional_fields(self):
        pair = _make_pair()
        assert pair.reason == ""
        assert pair.error_message == ""
        assert pair.full_screenshot_path == ""
        assert pair.chat_screenshot_path == ""
        assert pair.video_path == ""
        assert pair.trace_path == ""
        assert pair.run_mode == "speed"
        assert pair.fast_path_used is False
        assert pair.html_fragment_path == ""
        assert pair.fix_suggestion == ""
        assert pair.input_dom_verified is False
        assert pair.submit_effect_verified is False
        assert pair.input_verified is False
        assert pair.input_method_used == ""
        assert pair.submit_method_used == "unknown"
        assert pair.opened_chat_screenshot_path == ""
        assert pair.opened_full_screenshot_path == ""
        assert pair.opened_footer_screenshot_path == ""
        assert pair.open_method_used == ""
        assert pair.sdk_status == ""
        assert pair.availability_status == ""
        assert pair.input_scope == ""
        assert pair.input_scope_name == ""
        assert pair.input_selector == ""
        assert pair.input_failure_category == ""
        assert pair.input_failure_reason == ""
        assert pair.input_candidate_score == 0.0
        assert pair.top_candidate_disabled is False
        assert pair.activation_attempted is False
        assert pair.activation_steps_tried == ""
        assert pair.editable_candidates_count == 0
        assert pair.failover_attempts == 0
        assert pair.final_input_target_frame == ""
        assert pair.input_candidates_debug == ""
        assert pair.input_candidate_logs == []
        assert pair.before_send_screenshot_path == ""
        assert pair.before_send_full_screenshot_path == ""
        assert pair.after_send_screenshot_path == ""
        assert pair.after_send_full_screenshot_path == ""
        assert pair.font_fix_applied is False
        assert pair.user_message_echo_verified is False
        assert pair.new_bot_response_detected is False
        assert pair.baseline_menu_detected is False
        assert pair.answer_screenshot_paths == []
        assert pair.after_answer_multi_page is False
        assert pair.ocr_text == ""
        assert pair.ocr_confidence == 0.0
        assert pair.structured_message_history_count == 0
        assert pair.fallback_diff_used is False
        assert pair.raw_answer == "서비스센터에서 가능합니다."
        assert pair.cleaned_answer == "서비스센터에서 가능합니다."
        assert pair.cta_stripped is False
        assert pair.promo_stripped is False
        assert pair.question_repetition_detected is False
        assert pair.truncated_detected is False
        assert pair.truncated_answer_detected is False
        assert pair.carryover_detected is False
        assert pair.keyword_coverage_score == 0.0
        assert pair.needs_retry_extraction is False

    def test_invalid_capture_status(self):
        pair = _make_pair()
        invalid = replace(pair, status="invalid_capture", input_verified=False)
        assert invalid.status == "invalid_capture"
        assert invalid.input_verified is False

    def test_echo_verified_field(self):
        pair = _make_pair()
        echoed = replace(pair, user_message_echo_verified=True)
        assert echoed.user_message_echo_verified is True


class TestRunResult:
    def test_to_nested_dict_structure(self):
        result = RunResult(
            test_case=_make_test_case(),
            pair=_make_pair(),
            evaluation=_make_eval(),
        )
        nested = result.to_nested_dict()
        assert "test_case" in nested
        assert "pair" in nested
        assert "evaluation" in nested
        assert nested["test_case"]["id"] == "c01"
        assert nested["pair"]["answer"] == "서비스센터에서 가능합니다."
        assert nested["evaluation"]["overall_score"] == 8.7
        assert nested["evaluation"]["score_scale"] == "0-10"

    def test_to_result_record_structure(self):
        result = RunResult(
            test_case=_make_test_case(),
            pair=_make_pair(),
            evaluation=_make_eval(),
        )
        record = result.to_result_record()
        assert record["case_id"] == "c01"
        assert record["question"] == "배터리 교체는 어디서?"
        assert record["answer"] == "서비스센터에서 가능합니다."
        assert record["raw_answer"] == "서비스센터에서 가능합니다."
        assert record["cleaned_answer"] == "서비스센터에서 가능합니다."
        assert record["answer_raw"] == "서비스센터에서 가능합니다."
        assert record["answer_normalized"] == "서비스센터에서 가능합니다."
        assert record["input_dom_verified"] is False
        assert record["submit_effect_verified"] is False
        assert record["after_answer_multi_page"] is False
        assert record["structured_message_history_count"] == 0
        assert record["fallback_diff_used"] is False
        assert record["question_repetition_detected"] is False
        assert record["truncated_answer_detected"] is False
        assert record["needs_retry_extraction"] is False
        assert record["actual_answer"] == "서비스센터에서 가능합니다."
        assert record["actual_answer_clean"] == "서비스센터에서 가능합니다."
        assert record["cta_stripped"] is False
        assert record["promo_stripped"] is False
        assert record["message_history_clean"] == ""
        assert record["extraction_source_detail"] == ""
        assert record["removed_followups"] is False
        assert record["noise_lines_removed"] == 0
        assert record["input_scope"] == ""
        assert record["top_candidate_disabled"] is False
        assert record["activation_attempted"] is False
        assert record["activation_steps_tried"] == ""
        assert record["editable_candidates_count"] == 0
        assert record["failover_attempts"] == 0
        assert record["final_input_target_frame"] == ""
        assert record["open_method_used"] == ""
        assert record["sdk_status"] == ""
        assert record["availability_status"] == ""
        assert record["input_candidates_debug"] == ""
        assert record["opened_footer_screenshot_path"] == ""
        assert record["input_scope_name"] == ""
        assert record["input_selector"] == ""
        assert record["input_failure_category"] == ""
        assert record["input_failure_reason"] == ""
        assert record["input_candidate_score"] == 0.0
        assert record["input_candidate_logs"] == []
        assert record["run_mode"] == "speed"
        assert record["fast_path_used"] is False
        assert record["overall_score"] == 8.7
        assert record["score_scale"] == "0-10"
        assert record["evaluation_language"] == "ko"
        assert record["correctness_score"] == 3.6
        assert record["groundedness_score"] == 0.8
        assert record["score_breakdown_explanation"] == "질문 의도에 맞는 정보를 충분히 제공했습니다."
        assert record["needs_human_review"] is False
        assert record["fix_suggestion"] == ""
        assert record["reason"] == "질문에 맞는 답변입니다."
        assert record["flags"] == ""
        assert record["error_category"] == "(none)"
        assert record["language_policy_check"] == "pass"
        assert record["category"] == "service"
        assert record["page_url"] == "https://www.samsung.com/sec/"

    def test_to_flat_dict_structure(self):
        result = RunResult(
            test_case=_make_test_case(),
            pair=_make_pair(),
            evaluation=_make_eval(),
        )
        flat = result.to_flat_dict()
        assert "id" in flat
        assert "answer" in flat
        assert "input_scope" in flat
        assert "open_method_used" in flat
        assert "pair_answer" in flat
        assert "eval_overall_score" in flat
        assert flat["id"] == "c01"
        assert flat["answer"] == "서비스센터에서 가능합니다."
        assert flat["pair_answer"] == "서비스센터에서 가능합니다."
        assert flat["eval_overall_score"] == 8.7
        assert flat["eval_score_scale"] == "0-10"
        assert flat["eval_evaluation_language"] == "ko"
        assert flat["eval_flags"] == ""

    def test_to_flat_dict_no_key_conflicts(self):
        result = RunResult(
            test_case=_make_test_case(),
            pair=_make_pair(),
            evaluation=_make_eval(),
        )
        flat = result.to_flat_dict()
        pair_keys = {f"pair_{k}" for k in asdict(_make_pair())}
        eval_keys = {f"eval_{k}" for k in asdict(_make_eval())}
        case_keys = set(asdict(_make_test_case()).keys())
        all_expected = case_keys | pair_keys | eval_keys
        assert all_expected.issubset(flat.keys())

    def test_eval_result_flags_default_to_empty_list(self):
        evaluation = _make_eval()
        assert evaluation.flags == []

    def test_to_result_record_serializes_flags(self):
        result = RunResult(
            test_case=_make_test_case(),
            pair=_make_pair(),
            evaluation=replace(_make_eval(), flags=["too_short", "weak_keyword_alignment"]),
        )
        record = result.to_result_record()
        assert record["flags"] == "too_short|weak_keyword_alignment"


class TestExtractedPairNewFields:
    """Tests for new ExtractedPair fields: message_history and after_answer_screenshot_path."""

    def test_message_history_defaults_to_empty_list(self):
        pair = _make_pair()
        assert pair.message_history == []

    def test_after_answer_screenshot_path_defaults_to_empty(self):
        pair = _make_pair()
        assert pair.after_answer_screenshot_path == ""

    def test_after_answer_full_screenshot_path_defaults_to_empty(self):
        pair = _make_pair()
        assert pair.after_answer_full_screenshot_path == ""

    def test_new_bot_response_detected_defaults_to_false(self):
        pair = _make_pair()
        assert pair.new_bot_response_detected is False

    def test_submit_method_defaults_to_unknown(self):
        pair = _make_pair()
        assert pair.submit_method_used == "unknown"

    def test_baseline_menu_detected_defaults_to_false(self):
        pair = _make_pair()
        assert pair.baseline_menu_detected is False

    def test_message_history_stored_correctly(self):

        pair = replace(_make_pair(), message_history=["질문입니다.", "답변입니다."])
        assert pair.message_history == ["질문입니다.", "답변입니다."]

    def test_after_answer_screenshot_path_stored(self):

        pair = replace(_make_pair(), after_answer_screenshot_path="artifacts/chatbox/case01_after_answer.png")
        assert pair.after_answer_screenshot_path == "artifacts/chatbox/case01_after_answer.png"

    def test_message_history_serialised_in_nested_dict(self):

        pair = replace(_make_pair(), message_history=["msg1"])
        result = RunResult(test_case=_make_test_case(), pair=pair, evaluation=_make_eval())
        nested = result.to_nested_dict()
        assert nested["pair"]["message_history"] == ["msg1"]

    def test_answer_screenshot_paths_default_empty(self):
        pair = _make_pair()
        assert pair.answer_screenshot_paths == []

    def test_answer_normalized_stored(self):
        pair = replace(_make_pair(), answer_normalized="정리된 답변")
        assert pair.answer_normalized == "정리된 답변"

    def test_actual_answer_clean_stored(self):
        pair = replace(_make_pair(), actual_answer_clean="정제 답변")
        assert pair.actual_answer_clean == "정제 답변"
