"""Tests for the OpenAI evaluator module."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.evaluator import (
    EVALUATION_SCHEMA,
    _apply_quality_guardrails,
    _coerce_eval_payload,
    build_input_not_verified_evaluation,
    detect_evaluation_language,
    evaluate_pair,
    fallback_evaluation,
)
from app.models import EvalResult, ExtractedPair, TestCase


def _make_test_case(
    *,
    question: str = "배터리 교체는 어디서 하나요?",
    locale: str = "ko-KR",
    expected_keywords: list[str] | None = None,
) -> TestCase:
    return TestCase(
        id="c01",
        category="service",
        locale=locale,
        page_url="https://www.samsung.com/sec/",
        question=question,
        expected_keywords=expected_keywords or ["배터리", "서비스센터"],
        forbidden_keywords=["로그인"],
    )


def _make_pair(
    *,
    question: str | None = None,
    answer: str = "서비스센터에서 가능합니다.",
    locale: str = "ko-KR",
    extraction_confidence: float = 1.0,
    extraction_source: str = "dom",
) -> ExtractedPair:
    actual_question = question or "배터리 교체는 어디서 하나요?"
    return ExtractedPair(
        run_timestamp="2026-01-01T00:00:00+00:00",
        case_id="c01",
        category="service",
        page_url="https://www.samsung.com/sec/",
        locale=locale,
        question=actual_question,
        answer=answer,
        extraction_source=extraction_source,
        extraction_confidence=extraction_confidence,
        response_ms=1000,
        status="passed",
        raw_answer=answer,
        cleaned_answer=answer,
        answer_raw=answer,
        answer_normalized=answer,
        actual_answer=answer,
        actual_answer_clean=answer,
        input_dom_verified=True,
        submit_effect_verified=True,
        input_verified=True,
        input_method_used="fill",
        submit_method_used="button_click",
        new_bot_response_detected=True,
    )


def _make_eval_result(language: str = "ko") -> EvalResult:
    return EvalResult(
        overall_score=7.8,
        score_scale="0-10",
        evaluation_language=language,
        correctness_score=3.0,
        relevance_score=1.7,
        completeness_score=1.6,
        clarity_score=0.8,
        groundedness_score=0.7,
        score_breakdown_explanation="세부 점수 설명" if language == "ko" else "Score breakdown explanation",
        keyword_alignment_score=7.8,
        hallucination_risk="low",
        needs_human_review=False,
        reason="평가 사유" if language == "ko" else "Evaluation reason",
        fix_suggestion="개선 제안" if language == "ko" else "Fix suggestion",
        flags=[],
    )


def _make_config(api_key: str = "test-key"):
    from app.config import AppConfig

    return AppConfig(
        project_root=Path("/tmp/test"),
        openai_api_key=api_key,
        samsung_base_url="https://www.samsung.com/sec/",
        headless=True,
        default_locale="ko-KR",
        max_questions=5,
        openai_model="gpt-4o",
        playwright_timeout_ms=30000,
        answer_stable_checks=3,
        answer_stable_interval_sec=1.0,
        enable_video=False,
        enable_trace=False,
        enable_ocr_fallback=False,
        rubicon_chat_debug=False,
        rubicon_force_activation=True,
        rubicon_disable_sdk=False,
        rubicon_max_input_candidates=5,
        rubicon_frame_rescan_rounds=3,
        rubicon_before_send_screenshot=True,
        rubicon_opened_footer_screenshot=True,
        rubicon_after_answer_screenshot=True,
    )


def test_detect_evaluation_language_ko_from_question():
    assert detect_evaluation_language("갤럭시 링 배터리 알려줘", "") == "ko"


def test_detect_evaluation_language_en_from_locale():
    assert detect_evaluation_language("Tell me about Galaxy Ring battery life", "en-US") == "en"


def test_fallback_evaluation_uses_fixed_scale():
    result = fallback_evaluation("ko")
    assert result.score_scale == "0-10"
    assert result.evaluation_language == "ko"
    assert result.overall_score == 0.0
    assert result.correctness_score == 0.0
    assert result.groundedness_score == 0.0


def test_build_input_not_verified_evaluation_is_localized():
    result = build_input_not_verified_evaluation("갤럭시 링 배터리", "ko-KR")
    assert result.evaluation_language == "ko"
    assert result.score_scale == "0-10"
    assert result.flags == ["input_not_verified"]
    assert "질문" in result.reason or "입력" in result.reason


def test_schema_requires_new_breakdown_fields():
    required = EVALUATION_SCHEMA["required"]
    assert "score_scale" in required
    assert "evaluation_language" in required
    assert "correctness_score" in required
    assert "groundedness_score" in required
    assert "score_breakdown_explanation" in required


def test_coerce_payload_recomputes_overall_from_components():
    payload = {
        "score_scale": "0-10",
        "evaluation_language": "en",
        "overall_score": 1.0,
        "correctness_score": 3.0,
        "relevance_score": 1.5,
        "completeness_score": 1.5,
        "clarity_score": 0.7,
        "groundedness_score": 0.8,
        "score_breakdown_explanation": "English explanation",
        "keyword_alignment_score": 5.0,
        "hallucination_risk": "low",
        "needs_human_review": False,
        "reason": "English reason",
        "fix_suggestion": "English fix",
        "flags": [],
    }
    result = _coerce_eval_payload(payload, "en")
    assert result.overall_score == 7.5
    assert result.score_scale == "0-10"
    assert result.evaluation_language == "en"


def test_question_repetition_gets_hard_cap():
    question = "갤럭시 S26 울트라 사양 알려주세요"
    pair = _make_pair(question=question, answer=question)
    test_case = _make_test_case(question=question, expected_keywords=["디스플레이", "카메라"])
    result = _apply_quality_guardrails(test_case, pair, _make_eval_result("ko"))
    assert "question_repetition" in result.flags
    assert result.overall_score <= 1.0
    assert result.reason.startswith("답변이 질문을 반복해 실제 정보를 제공하지 않으므로 품질이 매우 낮습니다.")


def test_off_topic_carryover_gets_severe_penalty():
    test_case = _make_test_case(question="세탁기 용량 알려줘", expected_keywords=["세탁기"])
    pair = _make_pair(question="세탁기 용량 알려줘", answer="갤럭시 S26 울트라 카메라와 화면 차이를 안내드릴게요")
    result = _apply_quality_guardrails(test_case, pair, _make_eval_result("ko"))
    assert "topic_mismatch" in result.flags
    assert result.overall_score <= 1.5
    assert result.needs_human_review is True


def test_related_answer_with_promo_noise_is_not_marked_off_topic():
    question = "갤럭시 버즈3 프로 ANC와 방수 등 핵심 기능 알려줘"
    answer = (
        "갤럭시 버즈3 프로는 적응형 노이즈 캔슬링과 IP57 방수를 지원하고, 2-way 스피커가 핵심입니다. "
        "리뷰에서는 착용감이 좋다는 반응도 있습니다."
    )
    result = _apply_quality_guardrails(
        _make_test_case(question=question, expected_keywords=["버즈", "ANC", "IP57"]),
        _make_pair(question=question, answer=answer),
        _make_eval_result("ko"),
    )
    assert "carryover_contamination" not in result.flags
    assert "topic_mismatch" not in result.flags
    assert "promo_or_review_leak" in result.flags


def test_s26_released_name_alone_does_not_trigger_speculative_flag():
    question = "S26 Ultra 스펙 질문"
    answer = "출시 제품 기준 스펙 요약"
    result = _apply_quality_guardrails(
        _make_test_case(question=question, expected_keywords=["스펙"]),
        _make_pair(question=question, answer=answer),
        _make_eval_result("ko"),
    )
    assert "speculative_unverified" not in result.flags


def test_evaluation_prefers_cleaned_answer_over_raw_noise():
    question = "갤럭시 버즈3 프로 ANC와 방수 알려줘"
    pair = _make_pair(
        question=question,
        answer="추천 질문 관련 질문 CS AI 챗봇에 문의",
    )
    pair = replace(
        pair,
        raw_answer="추천 질문 관련 질문 CS AI 챗봇에 문의",
        cleaned_answer="갤럭시 버즈3 프로는 적응형 노이즈 캔슬링과 IP57 방수를 지원합니다.",
        actual_answer_clean="갤럭시 버즈3 프로는 적응형 노이즈 캔슬링과 IP57 방수를 지원합니다.",
    )
    result = _apply_quality_guardrails(
        _make_test_case(question=question, expected_keywords=["ANC", "IP57"]),
        pair,
        _make_eval_result("ko"),
    )
    assert "off_topic_or_carryover" not in result.flags
    assert result.overall_score >= 7.0


def test_unknown_source_with_non_empty_answer_is_treated_as_low_confidence_invalid_state():
    question = "갤럭시 버즈3 프로 ANC와 방수 알려줘"
    result = _apply_quality_guardrails(
        _make_test_case(question=question, expected_keywords=["ANC", "IP57"]),
        _make_pair(
            question=question,
            answer="갤럭시 버즈3 프로는 적응형 노이즈 캔슬링과 IP57 방수를 지원합니다.",
            extraction_source="unknown",
            extraction_confidence=0.8,
        ),
        _make_eval_result("ko"),
    )
    assert "low_confidence_extraction" in result.flags


def test_s26_exact_specs_trigger_speculative_flag():
    question = "갤럭시 S26 울트라와 플러스 차이를 알려줘"
    answer = "S26 울트라는 200MP 카메라와 5000mAh 배터리, 6.9형 디스플레이를 제공합니다."
    result = _apply_quality_guardrails(
        _make_test_case(question=question, expected_keywords=["카메라"]),
        _make_pair(question=question, answer=answer),
        _make_eval_result("ko"),
    )
    assert "speculative_unverified" in result.flags
    assert result.groundedness_score <= 0.5


def test_s26_exact_specs_by_name_only_trigger_speculative_flag():
    question = "갤럭시 S26 울트라 핵심 사양 알려줘"
    answer = "갤럭시 S26 울트라는 6.9형 디스플레이와 5,000mAh 배터리, 200MP 카메라를 제공합니다."
    result = _apply_quality_guardrails(
        _make_test_case(question=question, expected_keywords=["디스플레이", "배터리"]),
        _make_pair(question=question, answer=answer),
        _make_eval_result("ko"),
    )
    assert "speculative_unverified" in result.flags
    assert result.groundedness_score <= 0.5


def test_existing_speculative_flag_is_removed_for_released_product_without_speculative_cues():
    question = "갤럭시 링의 배터리 지속시간과 건강 센서 그리고 지원 기능을 알려주세요."
    answer = "갤럭시 링은 최대 6~7일 사용 가능하고 심박 센서와 온도 센서를 지원합니다."
    base = _make_eval_result("ko")
    base = replace(base, flags=["speculative_unverified"])

    result = _apply_quality_guardrails(
        _make_test_case(question=question, expected_keywords=["갤럭시 링", "배터리", "센서"]),
        _make_pair(question=question, answer=answer),
        base,
    )

    assert "speculative_unverified" not in result.flags


def test_existing_speculative_flag_is_kept_when_answer_uses_rumor_language():
    question = "갤럭시 링의 배터리 지속시간과 건강 센서 그리고 지원 기능을 알려주세요."
    answer = "갤럭시 링은 최대 7일로 예상되고, 정확한 센서 구성은 아직 미정입니다."
    base = _make_eval_result("ko")
    base = replace(base, flags=["speculative_unverified"])

    result = _apply_quality_guardrails(
        _make_test_case(question=question, expected_keywords=["갤럭시 링", "배터리", "센서"]),
        _make_pair(question=question, answer=answer),
        base,
    )

    assert "speculative_unverified" in result.flags


def test_s26_sensitive_commerce_claim_still_triggers_speculative_flag():
    question = "갤럭시 S26 울트라 가격과 재고 알려줘"
    answer = "갤럭시 S26 울트라는 현재 구매 가능하며 1,699,000원이고 재고가 충분합니다."
    result = _apply_quality_guardrails(
        _make_test_case(question=question, expected_keywords=["가격", "재고"]),
        _make_pair(question=question, answer=answer),
        _make_eval_result("ko"),
    )

    assert "speculative_unverified" in result.flags


def test_invalid_answer_status_keeps_human_review_and_negative_cap():
    question = "갤럭시 버즈3 프로 ANC와 방수 알려줘"
    result = _apply_quality_guardrails(
        _make_test_case(question=question, expected_keywords=["ANC", "IP57"]),
        replace(
            _make_pair(question=question, answer="갤럭시 S26 울트라 디스플레이는 6.9형입니다."),
            status="invalid_answer",
            carryover_detected=True,
            keyword_coverage_score=0.0,
        ),
        _make_eval_result("ko"),
    )

    assert result.needs_human_review is True
    assert result.overall_score <= 2.5


def test_evaluate_pair_uses_failed_answer_fallback_when_response_detected_but_answer_missing():
    logger = MagicMock()
    pair = replace(
        _make_pair(question="갤럭시 버즈3 프로 ANC와 방수 알려줘", answer=""),
        status="invalid_answer",
        answer="",
        raw_answer="",
        cleaned_answer="",
        answer_raw="",
        answer_normalized="",
        actual_answer="",
        actual_answer_clean="",
        new_bot_response_detected=True,
        input_verified=True,
        submit_effect_verified=True,
    )

    result = evaluate_pair(
        _make_config(api_key="test-key"),
        _make_test_case(question="갤럭시 버즈3 프로 ANC와 방수 알려줘", expected_keywords=["ANC", "IP57"]),
        pair,
        logger,
        target_language="ko",
    )

    assert result.flags == []
    assert result.reason == "유효한 답변을 추출하기 전에 실행이 중단되었습니다."


def test_substantive_aligned_answer_is_not_hard_failed_by_stale_dom_flags_alone():
    question = "갤럭시 북5 프로 360의 무게와 배터리 그리고 포트 구성을 알려주세요."
    answer = (
        "갤럭시 북5 프로 360은 16형 기준 무게 1.69kg, 76.1Wh 배터리, HDMI 2.1과 Thunderbolt 4 포트를 제공합니다. "
        "외부 모니터와 저장장치를 자주 연결할 때 편합니다."
    )
    result = _apply_quality_guardrails(
        _make_test_case(question=question, expected_keywords=["무게", "배터리", "포트"]),
        replace(
            _make_pair(question=question, answer=answer),
            status="invalid_answer",
            question_repetition_detected=True,
            carryover_detected=True,
            keyword_coverage_score=0.67,
        ),
        _make_eval_result("ko"),
    )

    assert "question_repetition" not in result.flags
    assert "off_topic_or_carryover" not in result.flags
    assert result.overall_score >= 7.0


def test_released_product_wording_is_sanitized_in_reason_and_fix():
    question = "갤럭시 S26 울트라 핵심 사양 알려줘"
    answer = "갤럭시 S26 울트라는 6.9형 디스플레이와 5,000mAh 배터리를 제공합니다."
    base = _make_eval_result("ko")
    base = replace(
        base,
        reason="미공개로 보이는 갤럭시 S26 울트라에 대해 근거 없이 설명합니다.",
        fix_suggestion="미발표 제품(S26 울트라)이므로 공식 공개 전까지 안내하지 마세요.",
        flags=[],
    )

    result = _apply_quality_guardrails(
        _make_test_case(question=question, expected_keywords=["디스플레이", "배터리"]),
        _make_pair(question=question, answer=answer),
        base,
    )

    assert "미공개" not in result.reason
    assert "미발표 제품" not in result.fix_suggestion


def test_truncated_and_promo_leak_flags_detected():
    question = "오디세이 OLED G8 비교"
    answer = "오디세이 OLED G8은 32형 240Hz입니다. 현재 판매가 1,299,000원:"
    result = _apply_quality_guardrails(
        _make_test_case(question=question, expected_keywords=["오디세이"]),
        _make_pair(question=question, answer=answer),
        _make_eval_result("ko"),
    )
    assert "truncated_answer" in result.flags
    assert "promo_or_review_leak" in result.flags


def test_korean_question_forces_korean_evaluation_text():
    config = _make_config("sk-test")
    logger = MagicMock()
    test_case = _make_test_case(question="갤럭시 링 배터리 알려줘", locale="ko-KR", expected_keywords=["배터리"])
    pair = _make_pair(question=test_case.question, answer="갤럭시 링은 최대 7일 사용 가능합니다.")
    payload = {
        "score_scale": "0-10",
        "evaluation_language": "en",
        "overall_score": 5.0,
        "correctness_score": 3.0,
        "relevance_score": 1.5,
        "completeness_score": 1.0,
        "clarity_score": 0.5,
        "groundedness_score": 0.5,
        "score_breakdown_explanation": "The score is based on correctness and relevance.",
        "keyword_alignment_score": 5.0,
        "hallucination_risk": "medium",
        "needs_human_review": False,
        "reason": "The answer directly addresses the question.",
        "fix_suggestion": "Add one more detail.",
        "flags": [],
    }
    response = MagicMock()
    response.output_text = json.dumps(payload, ensure_ascii=False)

    with patch("app.evaluator.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.responses.create.return_value = response
        result = evaluate_pair(config, test_case, pair, logger)

    assert result.evaluation_language == "ko"
    assert any("가" <= ch <= "힣" for ch in result.reason)
    assert any("가" <= ch <= "힣" for ch in result.fix_suggestion)
    assert any("가" <= ch <= "힣" for ch in result.score_breakdown_explanation)


def test_english_question_forces_english_evaluation_text():
    config = _make_config("sk-test")
    logger = MagicMock()
    test_case = _make_test_case(
        question="Explain the Galaxy Ring battery life and health sensors.",
        locale="en-US",
        expected_keywords=["battery", "sensor"],
    )
    pair = _make_pair(
        question=test_case.question,
        locale="en-US",
        answer="Galaxy Ring offers up to 7 days of battery life with heart rate and skin temperature sensors.",
    )
    payload = {
        "score_scale": "0-10",
        "evaluation_language": "ko",
        "overall_score": 5.0,
        "correctness_score": 3.0,
        "relevance_score": 1.5,
        "completeness_score": 1.0,
        "clarity_score": 0.5,
        "groundedness_score": 0.5,
        "score_breakdown_explanation": "세부 점수 설명입니다.",
        "keyword_alignment_score": 5.0,
        "hallucination_risk": "medium",
        "needs_human_review": False,
        "reason": "답변이 질문에 대체로 맞습니다.",
        "fix_suggestion": "세부 수치를 더 보강하세요.",
        "flags": [],
    }
    response = MagicMock()
    response.output_text = json.dumps(payload, ensure_ascii=False)

    with patch("app.evaluator.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.responses.create.return_value = response
        result = evaluate_pair(config, test_case, pair, logger)

    assert result.evaluation_language == "en"
    assert not any("가" <= ch <= "힣" for ch in result.reason)
    assert not any("가" <= ch <= "힣" for ch in result.fix_suggestion)
    assert not any("가" <= ch <= "힣" for ch in result.score_breakdown_explanation)


def test_input_not_verified_fallback_is_localized_for_english():
    result = build_input_not_verified_evaluation("Explain Galaxy Ring battery life", "en-US")
    assert result.evaluation_language == "en"
    assert "question" in result.reason.lower() or "input" in result.reason.lower()
    assert not any("가" <= ch <= "힣" for ch in result.fix_suggestion)


def test_low_score_reason_starts_negative_sentence():
    result = _apply_quality_guardrails(
        _make_test_case(question="세탁기 용량 알려줘", expected_keywords=["세탁기"]),
        _make_pair(question="세탁기 용량 알려줘", answer="갤럭시 S26 울트라 카메라와 화면 차이를 안내드릴게요"),
        _make_eval_result("ko"),
    )
    assert result.overall_score <= 2.0
    assert result.reason.startswith("답변 주제가 현재 질문과 어긋나 품질이 매우 낮습니다.")


def test_high_score_reason_starts_positive_sentence():
    question = "갤럭시 링 배터리와 센서 알려줘"
    answer = "갤럭시 링은 최대 7일 사용 가능하며 심박수와 피부 온도 같은 건강 센서를 제공합니다."
    result = _apply_quality_guardrails(
        _make_test_case(question=question, expected_keywords=["배터리", "센서"]),
        _make_pair(question=question, answer=answer),
        _make_eval_result("ko"),
    )
    assert result.overall_score >= 7.0
    assert result.reason.startswith("답변이 질문 의도에 전반적으로 잘 맞고 핵심 정보를 충분히 제공합니다.")