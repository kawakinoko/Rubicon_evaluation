"""OpenAI-based structured evaluation for extracted QA pairs."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from openai import OpenAI

from app.config import AppConfig
from app.dom_extractor import (
    _detect_topic_family as _dom_detect_topic_family,
    _is_question_repetition as _dom_is_question_repetition,
    _looks_truncated as _dom_looks_truncated,
)
from app.error_taxonomy import (
    CARRYOVER_CONTAMINATION,
    INVALID_ANSWER,
    LOW_CONFIDENCE_EXTRACTION,
    PROMO_OR_REVIEW_LEAK,
    QUESTION_REPETITION,
    SPECULATIVE_UNVERIFIED,
    TOPIC_MISMATCH,
    TRUNCATED_ANSWER,
    normalize_error_flag,
)
from app.models import EvalResult, ExtractedPair, TestCase


ALLOWED_FLAGS = {
    QUESTION_REPETITION,
    CARRYOVER_CONTAMINATION,
    SPECULATIVE_UNVERIFIED,
    TRUNCATED_ANSWER,
    PROMO_OR_REVIEW_LEAK,
    TOPIC_MISMATCH,
    INVALID_ANSWER,
    LOW_CONFIDENCE_EXTRACTION,
    "weak_keyword_alignment",
    "too_short",
    "timestamp_like",
    "input_not_verified",
    "evaluation_failed",
}

EVALUATOR_VERSION = "evaluator-v2.4"

FLAG_REASON_SNIPPETS = {
    "question_repetition": {
        "ko": "답변이 질문을 반복할 뿐 실제 정보를 제공하지 않습니다",
        "en": "the answer merely repeats the question instead of providing information",
    },
    CARRYOVER_CONTAMINATION: {
        "ko": "답변이 현재 질문과 어긋나거나 이전 문맥이 섞여 있습니다",
        "en": "the answer appears off-topic or carried over from another case",
    },
    TRUNCATED_ANSWER: {
        "ko": "답변이 끝부분에서 잘린 것으로 보입니다",
        "en": "the answer looks truncated near the ending",
    },
    SPECULATIVE_UNVERIFIED: {
        "ko": "공식 확인이 어려운 추정 스펙이 포함되어 있습니다",
        "en": "the answer includes speculative or unverified exact specs",
    },
    PROMO_OR_REVIEW_LEAK: {
        "ko": "상품 카드나 가격 같은 홍보성 문구가 답변에 섞였습니다",
        "en": "promotional or product-card text leaked into the answer",
    },
    TOPIC_MISMATCH: {
        "ko": "질문한 제품군과 답변 주제가 맞지 않습니다",
        "en": "the answer topic does not match the requested product family",
    },
    INVALID_ANSWER: {
        "ko": "추출은 되었지만 채택 가능한 답변으로 보기 어렵습니다",
        "en": "text was extracted, but it should not be accepted as a valid answer",
    },
    "weak_keyword_alignment": {
        "ko": "질문의 핵심 키워드와 답변 정렬이 약합니다",
        "en": "expected keywords are missing from the answer",
    },
    "too_short": {
        "ko": "답변이 너무 짧아 신뢰하기 어렵습니다",
        "en": "the answer is too short to be reliable",
    },
    "low_confidence_extraction": {
        "ko": "추출 신뢰도가 낮습니다",
        "en": "extraction confidence is low",
    },
    "timestamp_like": {
        "ko": "답변이 실제 응답이 아니라 시각 문자열처럼 보입니다",
        "en": "the answer resembles a timestamp rather than a real response",
    },
    "input_not_verified": {
        "ko": "질문 입력 검증이 충분하지 않았습니다",
        "en": "question input was not fully verified before evaluation",
    },
    "evaluation_failed": {
        "ko": "평가 모델 실패로 기본 평가를 사용했습니다",
        "en": "evaluation fallback was used because model evaluation failed",
    },
}

FLAG_FIX_SUGGESTIONS = {
    "question_repetition": {
        "ko": "질문 반복 응답은 정답으로 채택하지 말고, 실제 답변 본문이 없으면 재추출하거나 실패 처리하세요.",
        "en": "Do not accept question repetition as a valid answer; re-extract or fail the case when no real answer body exists.",
    },
    CARRYOVER_CONTAMINATION: {
        "ko": "채팅 문맥을 초기화하고, 현재 질문에 대한 새 답변인지 다시 검증하세요.",
        "en": "Reset chat context or verify that the newly detected answer belongs to the current question.",
    },
    TRUNCATED_ANSWER: {
        "ko": "답변 안정화를 한 번 더 기다리거나 DOM 추출을 다시 시도하세요.",
        "en": "Wait one more stabilization cycle or retry DOM extraction after answer completion.",
    },
    SPECULATIVE_UNVERIFIED: {
        "ko": "공식 페이지에서 확인되지 않은 정확한 수치나 스펙은 제거하고, 확인 가능한 범위만 답변하세요.",
        "en": "Remove unverified exact figures or specs and limit the answer to information confirmed on official pages.",
    },
    PROMO_OR_REVIEW_LEAK: {
        "ko": "답변 본문 뒤에 붙는 추천 질문, CS AI 챗봇 문의 유도, 더 알아보기, 상담원 연결, 리뷰, 구매 혜택, 대표 모델 예시 같은 visible CTA 문구를 제거한 뒤 핵심 답변만 채택하세요.",
        "en": "Filter product-card and price blocks from DOM history before selecting the final answer.",
    },
    TOPIC_MISMATCH: {
        "ko": "질문 제품군과 같은 토픽 패밀리의 후보만 채택하세요.",
        "en": "Accept only candidates that match the same product family as the question.",
    },
    INVALID_ANSWER: {
        "ko": "추출된 텍스트를 그대로 통과시키지 말고 acceptance gate를 통과한 본문만 평가하세요.",
        "en": "Do not evaluate extracted text unless it passed the acceptance gate.",
    },
    "weak_keyword_alignment": {
        "ko": "질문과 답변의 주제 정렬과 예상 키워드 포함 여부를 다시 확인하세요.",
        "en": "Re-check question-answer topic alignment and expected keyword matching.",
    },
    "too_short": {
        "ko": "최소 답변 길이 기준을 만족할 때만 DOM 추출 결과를 채택하세요.",
        "en": "Require a minimum answer length before accepting DOM extraction.",
    },
    "low_confidence_extraction": {
        "ko": "신뢰도가 더 높은 DOM 후보를 우선 선택하거나 재추출하세요.",
        "en": "Prefer a higher-confidence DOM candidate or retry extraction before finalizing the answer.",
    },
    "timestamp_like": {
        "ko": "시각 문자열처럼 보이는 캡처는 버리고 실제 답변이 올 때까지 기다리세요.",
        "en": "Reject timestamp-like captures and wait for a full textual answer.",
    },
    "input_not_verified": {
        "ko": "textarea 활성화, 질문 echo, 제출 후 diff를 모두 검증한 뒤에만 평가를 진행하세요.",
        "en": "Verify textarea activation, submitted user echo, and post-submit diff before accepting the capture.",
    },
    "evaluation_failed": {
        "ko": "로그와 스크린샷을 확인한 뒤, 추출된 답변이 유효한지 점검하고 다시 평가하세요.",
        "en": "Check logs and screenshots, then retry evaluation after confirming the extracted answer.",
    },
}

UNANNOUNCED_PRODUCT_PATTERNS = [
    r"\b(?:galaxy\s*)?s26(?:\s*(?:ultra|plus))?\b",
    r"갤럭시\s*s26(?:\s*(?:울트라|플러스))?",
    r"\bwatch ultra \(2025\)\b",
    r"\bbuds4 pro\b",
]

RELEASED_PRODUCT_OVERRIDES = [
    "갤럭시 s26",
    "갤럭시 s26 울트라",
    "갤럭시 s26 플러스",
    "galaxy s26",
    "galaxy s26 ultra",
    "galaxy s26 plus",
    "갤럭시 링",
    "galaxy ring",
    "갤럭시 버즈3 프로",
    "galaxy buds3 pro",
    "갤럭시 워치7",
    "galaxy watch7",
    "갤럭시 워치 울트라",
    "galaxy watch ultra",
    "갤럭시 북5 프로 360",
    "galaxy book5 pro 360",
    "비스포크 ai 콤보",
    "비스포크 냉장고",
    "bespoke",
    "오디세이 oled g8",
    "odyssey oled g8",
    "오디세이 neo g9",
    "odyssey neo g9",
    "neo qled",
    "samsung oled tv",
    "삼성 oled tv",
]

CLEANING_FIX_SUGGESTION = {
    "ko": "답변 본문 뒤에 붙는 추천 질문, CS AI 챗봇 문의 유도, 더 알아보기, 상담원 연결 같은 visible CTA와 리뷰, 구매 혜택, 대표 모델 예시를 제거한 뒤 핵심 답변만 채택하세요.",
    "en": "Remove visible CTA, follow-up prompts, review blurbs, benefits, and model-card tails before selecting the final answer body.",
}

SENSITIVE_COMMERCE_PATTERNS = [
    r"가격",
    r"혜택",
    r"할인",
    r"쿠폰",
    r"사은품",
    r"재고",
    r"구매 가능",
    r"현재 구매 가능",
    r"available now",
    r"in stock",
    r"availability",
    r"출시년도",
    r"출시 연도",
    r"launch year",
]

QUESTION_STOPWORDS = {
    "알려줘",
    "알려주세요",
    "설명",
    "비교",
    "차이",
    "what",
    "when",
    "where",
    "which",
    "about",
    "please",
    "tell",
    "explain",
    "show",
}

KO_MESSAGES = {
    "evaluation_failed_reason": "평가 API 호출에 실패했습니다.",
    "evaluation_failed_fix": "로그와 아티팩트를 확인하고 평가를 다시 시도하세요.",
    "input_not_verified_reason": "질문 입력이 검증되지 않아 평가할 수 없습니다.",
    "input_not_verified_fix": "before-send 기준으로 질문이 실제 입력되었는지 다시 확인하세요.",
    "capture_invalid_reason": "질문 입력 또는 제출 검증이 충분하지 않아 유효한 QA 쌍으로 판단할 수 없습니다.",
    "capture_invalid_fix": "textarea 활성화, 사용자 질문 echo, 제출 후 새 봇 응답 감지를 다시 확인한 뒤 재실행하세요.",
    "failed_answer_reason": "유효한 답변을 추출하기 전에 실행이 중단되었습니다.",
    "failed_answer_fix": "열기, 제출, 답변 추출 로그를 확인하고 실패 지점부터 재시도하세요.",
    "fallback_breakdown": "정확성, 관련성, 완전성, 명확성, 근거성을 모두 0.0으로 처리한 기본 평가입니다.",
    "input_not_verified_breakdown": "정확성, 관련성, 완전성, 명확성, 근거성을 모두 0.0으로 처리했습니다. 입력 검증이 완료되지 않았기 때문입니다.",
    "failed_answer_breakdown": "실제 답변이 없어 모든 세부 점수를 0.0으로 처리했습니다.",
    "guardrail_prefix": "가드레일 판정: ",
}

EN_MESSAGES = {
    "evaluation_failed_reason": "The evaluation API call failed.",
    "evaluation_failed_fix": "Check the logs and artifacts, then retry the evaluation.",
    "input_not_verified_reason": "The question input was not verified, so the case cannot be evaluated.",
    "input_not_verified_fix": "Re-check that the question was actually entered before send.",
    "capture_invalid_reason": "The question input or submit verification was insufficient, so the capture cannot be treated as a valid QA pair.",
    "capture_invalid_fix": "Re-run after verifying textarea activation, user-question echo, and a new post-submit bot response.",
    "failed_answer_reason": "Execution stopped before a valid answer could be extracted.",
    "failed_answer_fix": "Check the open, submit, and answer-extraction logs, then retry from the failed step.",
    "fallback_breakdown": "This is a fallback evaluation with all component scores set to 0.0.",
    "input_not_verified_breakdown": "All component scores are set to 0.0 because input verification was not completed.",
    "failed_answer_breakdown": "All component scores are set to 0.0 because no valid answer was extracted.",
    "guardrail_prefix": "Guardrail: ",
}

LANGUAGE_MISMATCH_ENGLISH_MARKERS = {
    "reason",
    "answer",
    "question",
    "score",
    "directly",
    "response",
    "speculative",
    "truncated",
}

LANGUAGE_MISMATCH_KOREAN_MARKERS = {
    "답변",
    "질문",
    "점수",
    "정확성",
    "관련성",
    "완전성",
    "명확성",
    "근거성",
}


EVALUATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "score_scale": {"type": "string", "enum": ["0-10"]},
        "evaluation_language": {"type": "string", "enum": ["ko", "en"]},
        "overall_score": {"type": "number", "minimum": 0, "maximum": 10},
        "correctness_score": {"type": "number", "minimum": 0, "maximum": 4},
        "relevance_score": {"type": "number", "minimum": 0, "maximum": 2},
        "completeness_score": {"type": "number", "minimum": 0, "maximum": 2},
        "clarity_score": {"type": "number", "minimum": 0, "maximum": 1},
        "groundedness_score": {"type": "number", "minimum": 0, "maximum": 1},
        "score_breakdown_explanation": {"type": "string"},
        "relevance_score": {"type": "number"},
        "keyword_alignment_score": {"type": "number"},
        "hallucination_risk": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "needs_human_review": {"type": "boolean"},
        "reason": {"type": "string"},
        "fix_suggestion": {"type": "string"},
        "flags": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": sorted(ALLOWED_FLAGS),
            },
        },
    },
    "required": [
        "score_scale",
        "evaluation_language",
        "overall_score",
        "correctness_score",
        "relevance_score",
        "completeness_score",
        "clarity_score",
        "groundedness_score",
        "score_breakdown_explanation",
        "keyword_alignment_score",
        "hallucination_risk",
        "needs_human_review",
        "reason",
        "fix_suggestion",
        "flags",
    ],
}


def _round_score(value: float) -> float:
    return round(max(0.0, value), 1)


def _clip_score(value: float, upper: float) -> float:
    return _round_score(min(max(0.0, value), upper))


def _messages(language: str) -> dict[str, str]:
    return KO_MESSAGES if language == "ko" else EN_MESSAGES


def detect_evaluation_language(question: str, locale: str | None = None) -> str:
    normalized_locale = (locale or "").lower()
    if normalized_locale.startswith("ko"):
        return "ko"
    if normalized_locale.startswith("en"):
        return "en"
    if len(re.findall(r"[가-힣]", question or "")) >= 3:
        return "ko"
    return "en"


def _localized_text(value: str | dict[str, str], language: str) -> str:
    if isinstance(value, dict):
        return value.get(language, value.get("en") or next(iter(value.values())))
    return value


def _localized_capture_reason(language: str) -> str:
    return _messages(language)["capture_invalid_reason"]


def _localized_capture_fix(language: str) -> str:
    return _messages(language)["capture_invalid_fix"]


def _localized_failed_reason(language: str, default_reason: str) -> str:
    if default_reason:
        return default_reason
    return _messages(language)["failed_answer_reason"]


def _localized_failed_fix(language: str, default_fix: str) -> str:
    if default_fix:
        return default_fix
    return _messages(language)["failed_answer_fix"]


def _localized_eval_failed_reason(language: str) -> str:
    return _messages(language)["evaluation_failed_reason"]


def _localized_eval_failed_fix(language: str) -> str:
    return _messages(language)["evaluation_failed_fix"]


def _score_breakdown_text(result: EvalResult) -> str:
    return (
        f"correctness={result.correctness_score:.1f}, "
        f"relevance={result.relevance_score:.1f}, "
        f"completeness={result.completeness_score:.1f}, "
        f"clarity={result.clarity_score:.1f}, "
        f"groundedness={result.groundedness_score:.1f}"
    )


def _build_breakdown_explanation(language: str, result: EvalResult, flags: list[str]) -> str:
    if language == "ko":
        parts = [
            f"정확성 {result.correctness_score:.1f}/4.0",
            f"관련성 {result.relevance_score:.1f}/2.0",
            f"완전성 {result.completeness_score:.1f}/2.0",
            f"명확성 {result.clarity_score:.1f}/1.0",
            f"근거성 {result.groundedness_score:.1f}/1.0",
        ]
        explanation = "세부 점수는 " + ", ".join(parts) + "입니다."
        if flags:
            flag_text = ", ".join(_localized_text(FLAG_REASON_SNIPPETS.get(flag, flag), language) for flag in flags)
            explanation += f" 주요 감점 사유는 {flag_text}입니다."
        return explanation

    parts = [
        f"correctness {result.correctness_score:.1f}/4.0",
        f"relevance {result.relevance_score:.1f}/2.0",
        f"completeness {result.completeness_score:.1f}/2.0",
        f"clarity {result.clarity_score:.1f}/1.0",
        f"groundedness {result.groundedness_score:.1f}/1.0",
    ]
    explanation = "The component scores are " + ", ".join(parts) + "."
    if flags:
        flag_text = ", ".join(_localized_text(FLAG_REASON_SNIPPETS.get(flag, flag), language) for flag in flags)
        explanation += f" The main penalties come from {flag_text}."
    return explanation


def _contains_question_repetition(question: str, answer: str) -> bool:
    return _dom_is_question_repetition(question, answer)


def _contains_released_override(text: str) -> bool:
    lowered = _normalize_answer_text(text).lower()
    return any(name in lowered for name in RELEASED_PRODUCT_OVERRIDES)


def _extract_core_keywords(text: str) -> list[str]:
    normalized = _normalize_answer_text(text).lower()
    if not normalized:
        return []
    tokens = re.findall(r"[a-z0-9가-힣+]{2,}", normalized)
    keywords: list[str] = []
    for token in tokens:
        if token in QUESTION_STOPWORDS:
            continue
        if token not in keywords:
            keywords.append(token)
    return keywords


def _keyword_coverage(question: str, answer: str, expected_keywords: list[str]) -> float:
    answer_lower = _normalize_answer_text(answer).lower()
    question_keywords = _extract_core_keywords(question)
    focus_keywords = [keyword.lower() for keyword in expected_keywords if keyword] + question_keywords[:6]
    deduped: list[str] = []
    for keyword in focus_keywords:
        if keyword and keyword not in deduped:
            deduped.append(keyword)
    if not deduped:
        return 0.0
    hits = sum(1 for keyword in deduped if keyword in answer_lower)
    return hits / len(deduped)


def _question_keywords_missing(question: str, answer: str) -> bool:
    answer_lower = _normalize_answer_text(answer).lower()
    core_keywords = _extract_core_keywords(question)[:5]
    if not core_keywords:
        return False
    hits = sum(1 for keyword in core_keywords if keyword in answer_lower)
    return hits <= 1


def _has_substantive_alignment(
    question: str,
    answer: str,
    expected_keywords: list[str],
    keyword_coverage: float | None = None,
) -> bool:
    normalized_answer = _normalize_answer_text(answer)
    if len(normalized_answer) < 40:
        return False
    if _contains_question_repetition(question, normalized_answer):
        return False

    question_family = _detect_topic_family(question)
    answer_family = _detect_topic_family(normalized_answer)
    if question_family != "unknown" and answer_family != "unknown" and question_family != answer_family:
        return False

    coverage = keyword_coverage if keyword_coverage is not None else _keyword_coverage(question, normalized_answer, expected_keywords)
    has_core_keyword_hits = not _question_keywords_missing(question, normalized_answer)
    has_sentence_shape = any(marker in normalized_answer for marker in ("다.", "요.", "니다.", ". ", ":"))
    return coverage >= 0.34 and (has_core_keyword_hits or has_sentence_shape)


def _looks_speculative_unverified(question: str, answer: str) -> bool:
    lowered_question = _normalize_answer_text(question).lower()
    lowered_answer = _normalize_answer_text(answer).lower()
    if not lowered_question or not lowered_answer:
        return False
    exact_spec_markers = ["mp", "mah", "wh", "kg", "hz", "gb", "mm", "형", "inch", "배 광학", "디지털", "원"]
    speculative_cues = ["예상", "루머", "추정", "미정", "예정", "가능성", "rumor", "expected", "unconfirmed"]
    number_like = bool(re.search(r"\b\d+(?:\.\d+)?\b", lowered_answer))
    has_released_override = _contains_released_override(lowered_question) or _contains_released_override(lowered_answer)
    asks_unannounced = any(re.search(pattern, lowered_question) for pattern in UNANNOUNCED_PRODUCT_PATTERNS)
    has_sensitive_commerce_claim = any(re.search(pattern, lowered_answer, re.IGNORECASE) for pattern in SENSITIVE_COMMERCE_PATTERNS)
    has_exact_specs = number_like and any(marker in lowered_answer for marker in exact_spec_markers)
    exact_spec_count = len(re.findall(r"\b\d+(?:\.\d+)?\s*(?:mp|mah|wh|kg|hz|gb|mm|형|inch|원)\b", lowered_answer))
    has_speculative_cue = any(cue in lowered_answer for cue in speculative_cues)
    if has_sensitive_commerce_claim:
        return True
    if asks_unannounced and (has_exact_specs or exact_spec_count >= 2):
        return True
    if has_released_override:
        return has_speculative_cue
    return has_speculative_cue or (asks_unannounced and has_exact_specs)


def _sanitize_released_override_text(text: str, question: str, answer: str) -> str:
    normalized = _normalize_answer_text(text)
    if not normalized:
        return normalized
    if not (_contains_released_override(question) or _contains_released_override(answer)):
        return normalized

    replacements = [
        (r"공개되지 않은 제품", "공식 근거가 확인되지 않은 세부 정보"),
        (r"미공개(?:로 보이는)? 제품", "공식 근거가 확인되지 않은 세부 정보"),
        (r"미발표(?:된)? 제품", "공식 근거가 확인되지 않은 세부 정보"),
        (r"아직 미공개", "아직 공식 근거가 확인되지 않음"),
        (r"미공개로 보이는", "공식 근거가 충분히 제시되지 않은"),
        (r"미발표 제품\(([^)]*)\)", r"공식 근거가 충분하지 않은 정보(\1)"),
    ]
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized)
    return normalized


def _normalize_speculative_flag(question: str, answer: str, flags: list[str]) -> list[str]:
    if SPECULATIVE_UNVERIFIED not in flags:
        return flags

    lowered_question = _normalize_answer_text(question).lower()
    lowered_answer = _normalize_answer_text(answer).lower()
    if not lowered_question or not lowered_answer:
        return flags

    speculative_cues = ["예상", "루머", "추정", "미정", "예정", "가능성", "rumor", "expected", "unconfirmed"]
    asks_unannounced = any(re.search(pattern, lowered_question) for pattern in UNANNOUNCED_PRODUCT_PATTERNS)
    has_speculative_cue = any(cue in lowered_answer for cue in speculative_cues)
    has_released_override = _contains_released_override(lowered_question) or _contains_released_override(lowered_answer)
    has_sensitive_commerce_claim = any(re.search(pattern, lowered_answer, re.IGNORECASE) for pattern in SENSITIVE_COMMERCE_PATTERNS)
    has_exact_specs = bool(re.search(r"\b\d+(?:\.\d+)?\s*(?:mp|mah|wh|kg|hz|gb|mm|형|inch|원)\b", lowered_answer))

    if has_released_override and not has_speculative_cue and not asks_unannounced and not has_sensitive_commerce_claim:
        return [flag for flag in flags if flag != SPECULATIVE_UNVERIFIED]
    if asks_unannounced and has_exact_specs:
        return flags
    return flags


def _language_mismatch(text: str, target_language: str) -> bool:
    normalized = _normalize_answer_text(text)
    if not normalized:
        return False
    if target_language == "ko":
        has_korean = bool(re.search(r"[가-힣]", normalized))
        english_hits = sum(1 for marker in LANGUAGE_MISMATCH_ENGLISH_MARKERS if marker in normalized.lower())
        return not has_korean and english_hits >= 2
    if re.search(r"[가-힣]", normalized):
        return True
    has_korean_marker = any(marker in normalized for marker in LANGUAGE_MISMATCH_KOREAN_MARKERS)
    return has_korean_marker


def _reason_lead(language: str, flags: list[str], overall_score: float) -> str:
    if QUESTION_REPETITION in flags:
        return (
            "답변이 질문을 반복해 실제 정보를 제공하지 않으므로 품질이 매우 낮습니다."
            if language == "ko"
            else "The answer quality is very poor because it repeats the question instead of providing real information."
        )
    if CARRYOVER_CONTAMINATION in flags or TOPIC_MISMATCH in flags:
        return (
            "답변 주제가 현재 질문과 어긋나 품질이 매우 낮습니다."
            if language == "ko"
            else "The answer quality is very poor because the topic does not match the current question."
        )
    if INVALID_ANSWER in flags:
        return (
            "추출된 텍스트를 유효한 답변으로 채택할 수 없어 품질이 매우 낮습니다."
            if language == "ko"
            else "The answer quality is very poor because the extracted text should not be accepted as a valid answer."
        )
    if overall_score <= 2.0:
        return (
            "답변 품질이 전반적으로 낮고 핵심 요구를 충족하지 못했습니다."
            if language == "ko"
            else "The answer quality is poor overall and does not satisfy the core request."
        )
    if overall_score >= 7.0:
        return (
            "답변이 질문 의도에 전반적으로 잘 맞고 핵심 정보를 충분히 제공합니다."
            if language == "ko"
            else "The answer generally matches the question intent and provides the key information well."
        )
    return ""


def _ensure_reason_consistency(reason: str, language: str, flags: list[str], overall_score: float) -> str:
    normalized = _normalize_answer_text(reason)
    lead = _reason_lead(language, flags, overall_score)
    if not lead:
        return normalized
    if not normalized:
        return lead
    if normalized.startswith(lead):
        return normalized
    return f"{lead} {normalized}".strip()


def _default_reason(language: str, flags: list[str], result: EvalResult) -> str:
    if language == "ko":
        if not flags:
            return _ensure_reason_consistency(
                "질문 의도에 대체로 맞는 답변이며, 세부 점수 기준에서도 큰 결함이 없습니다.",
                language,
                flags,
                result.overall_score,
            )
        details = ", ".join(_localized_text(FLAG_REASON_SNIPPETS.get(flag, flag), language) for flag in flags)
        return _ensure_reason_consistency(f"주요 문제는 {details}입니다.", language, flags, result.overall_score)
    if not flags:
        return _ensure_reason_consistency(
            "The answer generally matches the question intent and does not show major issues under the rubric.",
            language,
            flags,
            result.overall_score,
        )
    details = ", ".join(_localized_text(FLAG_REASON_SNIPPETS.get(flag, flag), language) for flag in flags)
    return _ensure_reason_consistency(f"The main issues are {details}.", language, flags, result.overall_score)


def _default_fix(language: str, flags: list[str]) -> str:
    if not flags:
        if language == "ko":
            return "필요하면 공식 페이지 링크나 모델별 조건을 덧붙여 신뢰도를 더 높이세요."
        return "Optionally add official page links or model-specific conditions to improve trustworthiness."

    suggestions: list[str] = []
    for flag in flags:
        suggestion = _localized_text(FLAG_FIX_SUGGESTIONS.get(flag, flag), language)
        if suggestion and suggestion not in suggestions:
            suggestions.append(suggestion)
    if any(flag in flags for flag in {PROMO_OR_REVIEW_LEAK, CARRYOVER_CONTAMINATION, TOPIC_MISMATCH, QUESTION_REPETITION}):
        cleaning_suggestion = _localized_text(CLEANING_FIX_SUGGESTION, language)
        if cleaning_suggestion not in suggestions:
            suggestions.append(cleaning_suggestion)
    return " ".join(suggestions)


def _localize_result_texts(result: EvalResult, language: str) -> EvalResult:
    reason = result.reason
    fix = result.fix_suggestion
    explanation = result.score_breakdown_explanation

    if _language_mismatch(reason, language):
        reason = _default_reason(language, result.flags, result)
    if _language_mismatch(fix, language) or not _normalize_answer_text(fix):
        fix = _default_fix(language, result.flags)
    if _language_mismatch(explanation, language) or not _normalize_answer_text(explanation):
        explanation = _build_breakdown_explanation(language, result, result.flags)
    reason = _ensure_reason_consistency(reason, language, result.flags, result.overall_score)

    return EvalResult(
        overall_score=result.overall_score,
        score_scale="0-10",
        evaluation_language=language,  # normalized target language wins
        correctness_score=result.correctness_score,
        relevance_score=result.relevance_score,
        completeness_score=result.completeness_score,
        clarity_score=result.clarity_score,
        groundedness_score=result.groundedness_score,
        score_breakdown_explanation=explanation,
        keyword_alignment_score=result.keyword_alignment_score,
        hallucination_risk=result.hallucination_risk,
        needs_human_review=result.needs_human_review,
        reason=reason,
        fix_suggestion=fix,
        flags=result.flags,
    )


def build_input_not_verified_evaluation(question: str, locale: str, reason: str = "", fix_suggestion: str = "") -> EvalResult:
    language = detect_evaluation_language(question, locale)
    return EvalResult(
        overall_score=0.0,
        score_scale="0-10",
        evaluation_language=language,
        correctness_score=0.0,
        relevance_score=0.0,
        completeness_score=0.0,
        clarity_score=0.0,
        groundedness_score=0.0,
        score_breakdown_explanation=_messages(language)["input_not_verified_breakdown"],
        keyword_alignment_score=0.0,
        hallucination_risk="high",
        needs_human_review=True,
        reason=reason or _localized_capture_reason(language),
        fix_suggestion=fix_suggestion or _localized_capture_fix(language),
        flags=["input_not_verified"],
    )


def fallback_evaluation(language: str = "en") -> EvalResult:
    """Return the mandated fallback JSON payload as a dataclass."""

    return EvalResult(
        overall_score=0.0,
        score_scale="0-10",
        evaluation_language=language,
        correctness_score=0.0,
        relevance_score=0.0,
        completeness_score=0.0,
        clarity_score=0.0,
        groundedness_score=0.0,
        score_breakdown_explanation=_messages(language)["fallback_breakdown"],
        keyword_alignment_score=0.0,
        hallucination_risk="high",
        needs_human_review=True,
        reason=_localized_eval_failed_reason(language),
        fix_suggestion=_localized_eval_failed_fix(language),
        flags=["evaluation_failed"],
    )


def _capture_not_verified_evaluation() -> EvalResult:
    """Return the mandated evaluation payload for invalid or unverified captures."""

    return build_input_not_verified_evaluation("", "en")


def _invalid_capture_evaluation(pair: ExtractedPair) -> EvalResult:
    language = detect_evaluation_language(pair.question, pair.locale)
    return build_input_not_verified_evaluation(
        pair.question,
        pair.locale,
        reason=(
            f"유효하지 않은 캡처입니다: {pair.input_failure_category or pair.reason or 'capture_not_verified'}"
            if language == "ko"
            else f"Invalid capture: {pair.input_failure_category or pair.reason or 'capture_not_verified'}"
        ),
        fix_suggestion=pair.fix_suggestion or (
            "runtime.log, 활성화 단계, 스크린샷을 확인하세요."
            if language == "ko"
            else "Check runtime.log, activation steps, and screenshots."
        ),
    )


def _failed_answer_evaluation(pair: ExtractedPair) -> EvalResult:
    language = detect_evaluation_language(pair.question, pair.locale)
    return EvalResult(
        overall_score=0.0,
        score_scale="0-10",
        evaluation_language=language,
        correctness_score=0.0,
        relevance_score=0.0,
        completeness_score=0.0,
        clarity_score=0.0,
        groundedness_score=0.0,
        score_breakdown_explanation=_messages(language)["failed_answer_breakdown"],
        keyword_alignment_score=0.0,
        hallucination_risk="high",
        needs_human_review=True,
        reason=_localized_failed_reason(language, pair.reason),
        fix_suggestion=_localized_failed_fix(language, pair.fix_suggestion),
        flags=[],
    )


def _evaluation_answer(pair: ExtractedPair) -> str:
    return pair.cleaned_answer or pair.actual_answer_clean or pair.actual_answer or pair.answer


def _normalize_answer_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _looks_like_timestamp(answer: str) -> bool:
    normalized = _normalize_answer_text(answer)
    if not normalized:
        return False
    return bool(
        re.fullmatch(
            r"(?:\d{1,2}:\d{2}(?::\d{2})?(?:\s?(?:AM|PM))?|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)",
            normalized,
            re.IGNORECASE,
        )
    )


def _looks_truncated(answer: str) -> bool:
    return _dom_looks_truncated(answer)


def _contains_promo_or_product_card_text(answer: str) -> bool:
    normalized = _normalize_answer_text(answer)
    lowered = normalized.lower()
    if not lowered:
        return False
    promo_tokens = [
        "⭐",
        "할인",
        "더 알아보기",
        "혜택",
        "별점",
        "sm-",
        "구매하기",
        "즉시할인",
        "리뷰에서는",
        "사용자 반응",
        "실사용자 반응",
        "재고",
        "현재 구매 가능",
    ]
    if any(token in normalized or token in lowered for token in promo_tokens):
        return True
    return bool(re.search(r"\b\d{2,3}(?:,\d{3})+원\b", normalized))


def _detect_topic_family(text: str) -> str:
    return _dom_detect_topic_family(text)


def _append_flag(flags: list[str], flag: str) -> None:
    if flag in ALLOWED_FLAGS and flag not in flags:
        flags.append(flag)


def _augment_reason(base_reason: str, flags: list[str], language: str) -> str:
    normalized_base = _normalize_answer_text(base_reason)
    guardrail_parts = [_localized_text(FLAG_REASON_SNIPPETS[flag], language) for flag in flags if flag in FLAG_REASON_SNIPPETS]
    if not guardrail_parts:
        return normalized_base or "No additional evaluation reason provided."
    guardrail_sentence = _messages(language)["guardrail_prefix"] + "; ".join(guardrail_parts) + "."
    if normalized_base:
        return f"{normalized_base} {guardrail_sentence}".strip()
    return guardrail_sentence


def _augment_fix_suggestion(base_fix: str, flags: list[str], language: str) -> str:
    suggestions: list[str] = []
    normalized_base = _normalize_answer_text(base_fix)
    if normalized_base:
        suggestions.append(normalized_base.rstrip(".") + ".")
    for flag in flags:
        suggestion = _localized_text(FLAG_FIX_SUGGESTIONS.get(flag, ""), language)
        if suggestion and suggestion not in suggestions:
            suggestions.append(suggestion)
    if any(flag in flags for flag in {PROMO_OR_REVIEW_LEAK, CARRYOVER_CONTAMINATION, QUESTION_REPETITION, TOPIC_MISMATCH}):
        cleaning_suggestion = _localized_text(CLEANING_FIX_SUGGESTION, language)
        if cleaning_suggestion and cleaning_suggestion not in suggestions:
            suggestions.append(cleaning_suggestion)
    return " ".join(suggestions).strip()


def _coerce_eval_payload(payload: dict[str, Any], target_language: str) -> EvalResult:
    """Normalize model JSON to the required dataclass schema."""

    fallback = asdict(fallback_evaluation(target_language))
    fallback.update(payload)
    raw_flags = fallback.get("flags", [])
    if isinstance(raw_flags, str):
        raw_flags = [raw_flags]
    elif not isinstance(raw_flags, list):
        raw_flags = []

    normalized_flags: list[str] = []
    for item in raw_flags:
        flag = str(item).strip()
        if flag in ALLOWED_FLAGS and flag not in normalized_flags:
            normalized_flags.append(flag)

    correctness_score = _clip_score(float(fallback.get("correctness_score", 0.0)), 4.0)
    relevance_score = _clip_score(float(fallback.get("relevance_score", 0.0)), 2.0)
    completeness_score = _clip_score(float(fallback.get("completeness_score", 0.0)), 2.0)
    clarity_score = _clip_score(float(fallback.get("clarity_score", 0.0)), 1.0)
    groundedness_score = _clip_score(float(fallback.get("groundedness_score", 0.0)), 1.0)
    recomputed_overall = _round_score(
        correctness_score + relevance_score + completeness_score + clarity_score + groundedness_score
    )

    keyword_alignment_score = _clip_score(float(fallback.get("keyword_alignment_score", relevance_score)), 10.0)

    return EvalResult(
        overall_score=recomputed_overall,
        score_scale="0-10",
        evaluation_language=str(fallback.get("evaluation_language", target_language)),
        correctness_score=correctness_score,
        relevance_score=relevance_score,
        completeness_score=completeness_score,
        clarity_score=clarity_score,
        groundedness_score=groundedness_score,
        score_breakdown_explanation=str(fallback.get("score_breakdown_explanation", "")),
        keyword_alignment_score=keyword_alignment_score,
        hallucination_risk=str(fallback["hallucination_risk"]),
        needs_human_review=bool(fallback["needs_human_review"]),
        reason=str(fallback["reason"]),
        fix_suggestion=str(fallback["fix_suggestion"]),
        flags=normalized_flags,
    )


def _apply_quality_guardrails(test_case: TestCase, pair: ExtractedPair, result: EvalResult) -> EvalResult:
    normalized_answer = _normalize_answer_text(_evaluation_answer(pair))
    flags = list(result.flags)
    flags = [normalize_error_flag(flag) for flag in flags if normalize_error_flag(flag)]
    target_language = detect_evaluation_language(test_case.question, pair.locale)
    keyword_coverage = max(
        _keyword_coverage(test_case.question, normalized_answer, test_case.expected_keywords),
        float(getattr(pair, "keyword_coverage_score", 0.0) or 0.0),
    )

    correctness_score = result.correctness_score
    relevance_score = result.relevance_score
    completeness_score = result.completeness_score
    clarity_score = result.clarity_score
    groundedness_score = result.groundedness_score
    substantive_alignment = _has_substantive_alignment(
        test_case.question,
        normalized_answer,
        test_case.expected_keywords,
        keyword_coverage=keyword_coverage,
    )

    if len(normalized_answer) < 40:
        _append_flag(flags, "too_short")
    if _looks_like_timestamp(normalized_answer):
        _append_flag(flags, "timestamp_like")
    if test_case.expected_keywords:
        lowered_answer = normalized_answer.lower()
        if not any(keyword.lower() in lowered_answer for keyword in test_case.expected_keywords):
            _append_flag(flags, "weak_keyword_alignment")
    if getattr(pair, "question_repetition_detected", False) and not substantive_alignment:
        _append_flag(flags, QUESTION_REPETITION)
    if getattr(pair, "carryover_detected", False) and not substantive_alignment:
        _append_flag(flags, CARRYOVER_CONTAMINATION)
    if pair.extraction_source == "unknown" or pair.extraction_confidence < 0.45:
        _append_flag(flags, LOW_CONFIDENCE_EXTRACTION)
    if getattr(pair, "truncated_detected", False) or getattr(pair, "truncated_answer_detected", False) or _looks_truncated(normalized_answer):
        _append_flag(flags, TRUNCATED_ANSWER)
    if _contains_promo_or_product_card_text(normalized_answer):
        _append_flag(flags, PROMO_OR_REVIEW_LEAK)
    if _contains_question_repetition(test_case.question, normalized_answer) and not substantive_alignment:
        _append_flag(flags, QUESTION_REPETITION)
    if _looks_speculative_unverified(test_case.question, normalized_answer):
        _append_flag(flags, SPECULATIVE_UNVERIFIED)

    flags = _normalize_speculative_flag(test_case.question, normalized_answer, flags)

    question_family = _detect_topic_family(test_case.question)
    answer_family = _detect_topic_family(normalized_answer)
    real_topic_mismatch = (
        question_family != "unknown"
        and answer_family != "unknown"
        and question_family != answer_family
        and keyword_coverage < 0.35
        and _question_keywords_missing(test_case.question, normalized_answer)
    )
    if real_topic_mismatch and keyword_coverage < 0.5:
        _append_flag(flags, TOPIC_MISMATCH)

    if QUESTION_REPETITION in flags:
        correctness_score = 0.0
        completeness_score = min(completeness_score, 0.2)
        relevance_score = min(relevance_score, 0.4)
        clarity_score = min(clarity_score, 0.2)
        groundedness_score = min(groundedness_score, 0.2)

    if CARRYOVER_CONTAMINATION in flags or TOPIC_MISMATCH in flags:
        correctness_score = min(correctness_score, 0.2)
        relevance_score = min(relevance_score, 0.4)
        completeness_score = min(completeness_score, 0.4)
        clarity_score = min(clarity_score, 0.3)
        groundedness_score = min(groundedness_score, 0.2)

    if SPECULATIVE_UNVERIFIED in flags:
        groundedness_score = min(groundedness_score, 0.3)
        correctness_score = min(correctness_score, 1.8)
    elif _contains_released_override(test_case.question) or _contains_released_override(normalized_answer):
        lowered_answer = normalized_answer.lower()
        exact_spec_count = len(re.findall(r"\b\d+(?:\.\d+)?\s*(?:mp|mah|wh|kg|hz|gb|mm|형|inch|원)\b", lowered_answer))
        has_sensitive_commerce_claim = any(re.search(pattern, lowered_answer, re.IGNORECASE) for pattern in SENSITIVE_COMMERCE_PATTERNS)
        if has_sensitive_commerce_claim or exact_spec_count >= 3:
            groundedness_score = min(groundedness_score, 0.5)

    if TRUNCATED_ANSWER in flags:
        completeness_score = min(completeness_score, 0.6)
        clarity_score = min(clarity_score, 0.4)

    if PROMO_OR_REVIEW_LEAK in flags:
        relevance_score = min(relevance_score, 0.8)
        clarity_score = min(clarity_score, 0.4)

    if "too_short" in flags:
        completeness_score = min(completeness_score, 0.3)

    if pair.status == "invalid_answer" and not substantive_alignment:
        _append_flag(flags, INVALID_ANSWER)

    hard_invalid_flags = {QUESTION_REPETITION, CARRYOVER_CONTAMINATION, TOPIC_MISMATCH, TRUNCATED_ANSWER, INVALID_ANSWER}
    has_hard_invalid_signal = any(flag in flags for flag in hard_invalid_flags)

    if pair.status in {"retry_extraction", "invalid_answer"}:
        needs_human_review = True
        if pair.status == "invalid_answer" and has_hard_invalid_signal:
            overall_cap = 2.5
        elif pair.status == "retry_extraction" and has_hard_invalid_signal:
            overall_cap = 4.5
        else:
            overall_cap = 10.0
    else:
        needs_human_review = result.needs_human_review or bool(flags)
        overall_cap = 10.0

    overall_score = _round_score(
        correctness_score + relevance_score + completeness_score + clarity_score + groundedness_score
    )
    if QUESTION_REPETITION in flags:
        overall_score = min(overall_score, 1.0)
    if CARRYOVER_CONTAMINATION in flags or TOPIC_MISMATCH in flags:
        overall_score = min(overall_score, 1.5)

    overall_score = min(overall_score, overall_cap)
    if any(flag in flags for flag in [CARRYOVER_CONTAMINATION, TOPIC_MISMATCH, QUESTION_REPETITION, INVALID_ANSWER]):
        needs_human_review = True

    hallucination_risk = result.hallucination_risk
    if SPECULATIVE_UNVERIFIED in flags:
        hallucination_risk = "high"
    elif groundedness_score <= 0.2:
        hallucination_risk = "high"
    elif groundedness_score <= 0.5:
        hallucination_risk = "medium"
    else:
        hallucination_risk = "low"

    updated = EvalResult(
        overall_score=overall_score,
        score_scale="0-10",
        evaluation_language=target_language,
        correctness_score=_clip_score(correctness_score, 4.0),
        relevance_score=_clip_score(relevance_score, 2.0),
        completeness_score=_clip_score(completeness_score, 2.0),
        clarity_score=_clip_score(clarity_score, 1.0),
        groundedness_score=_clip_score(groundedness_score, 1.0),
        score_breakdown_explanation="",
        keyword_alignment_score=_clip_score(max(result.keyword_alignment_score, keyword_coverage * 10.0), 10.0),
        hallucination_risk=hallucination_risk,
        needs_human_review=needs_human_review,
        reason=result.reason,
        fix_suggestion=result.fix_suggestion,
        flags=flags,
    )
    updated = _localize_result_texts(updated, target_language)
    if not _normalize_answer_text(updated.reason):
        updated = EvalResult(
            overall_score=updated.overall_score,
            score_scale=updated.score_scale,
            evaluation_language=updated.evaluation_language,
            correctness_score=updated.correctness_score,
            relevance_score=updated.relevance_score,
            completeness_score=updated.completeness_score,
            clarity_score=updated.clarity_score,
            groundedness_score=updated.groundedness_score,
            score_breakdown_explanation=_build_breakdown_explanation(target_language, updated, flags),
            keyword_alignment_score=updated.keyword_alignment_score,
            hallucination_risk=updated.hallucination_risk,
            needs_human_review=updated.needs_human_review,
            reason=_default_reason(target_language, flags, updated),
            fix_suggestion=_default_fix(target_language, flags),
            flags=flags,
        )

    updated = EvalResult(
        overall_score=updated.overall_score,
        score_scale=updated.score_scale,
        evaluation_language=updated.evaluation_language,
        correctness_score=updated.correctness_score,
        relevance_score=updated.relevance_score,
        completeness_score=updated.completeness_score,
        clarity_score=updated.clarity_score,
        groundedness_score=updated.groundedness_score,
        score_breakdown_explanation=_build_breakdown_explanation(target_language, updated, flags)
        if _language_mismatch(updated.score_breakdown_explanation, target_language) or not _normalize_answer_text(updated.score_breakdown_explanation)
        else updated.score_breakdown_explanation,
        keyword_alignment_score=updated.keyword_alignment_score,
        hallucination_risk=updated.hallucination_risk,
        needs_human_review=updated.needs_human_review,
        reason=_sanitize_released_override_text(_augment_reason(updated.reason, flags, target_language), test_case.question, normalized_answer),
        fix_suggestion=_sanitize_released_override_text(_augment_fix_suggestion(updated.fix_suggestion, flags, target_language), test_case.question, normalized_answer),
        flags=flags,
    )
    return _localize_result_texts(updated, target_language)


def _response_text(response: Any) -> str:
    """Extract textual output from an OpenAI Responses API result."""

    direct_text = getattr(response, "output_text", "")
    if direct_text:
        return direct_text

    try:
        dumped = response.model_dump()
    except Exception:
        return ""

    output_chunks = dumped.get("output", [])
    parts: list[str] = []
    for item in output_chunks:
        for content in item.get("content", []):
            text = content.get("text") or content.get("value")
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def evaluate_pair(
    config: AppConfig,
    test_case: TestCase,
    pair: ExtractedPair,
    logger: Any,
    target_language: str | None = None,
) -> EvalResult:
    """Evaluate a question-answer pair with OpenAI Structured Outputs."""

    evaluation_answer = _evaluation_answer(pair)
    target_language = target_language or detect_evaluation_language(test_case.question, pair.locale)

    if pair.status == "invalid_capture":
        logger.warning(
            "Capture invalid for case %s (%s); using invalid-capture fallback evaluation",
            pair.case_id,
            pair.input_failure_category or pair.reason,
        )
        logger.info("evaluation completed")
        return _invalid_capture_evaluation(pair)

    if pair.status == "failed" and (not pair.answer_raw or pair.input_failure_category == "answer_not_extracted"):
        logger.warning(
            "Execution failed for case %s (%s); using failed-answer fallback evaluation",
            pair.case_id,
            pair.input_failure_category or pair.reason,
        )
        logger.info("evaluation completed")
        return _failed_answer_evaluation(pair)

    if (not evaluation_answer or evaluation_answer == "(none)") and pair.input_verified and pair.submit_effect_verified and pair.new_bot_response_detected and not pair.baseline_menu_detected:
        logger.warning(
            "Answer extraction failed for case %s (status=%s); using failed-answer fallback evaluation",
            pair.case_id,
            pair.status,
        )
        logger.info("evaluation completed")
        return _failed_answer_evaluation(pair)

    if (
        not evaluation_answer
        or evaluation_answer == "(none)"
        or not pair.input_verified
        or not pair.submit_effect_verified
        or not pair.new_bot_response_detected
        or pair.baseline_menu_detected
    ):
        logger.warning(
            "Capture verification failed for case %s (status=%s); skipping GPT evaluation",
            pair.case_id,
            pair.status,
        )
        logger.info("evaluation completed")
        return build_input_not_verified_evaluation(test_case.question, pair.locale)

    if not config.openai_api_key:
        logger.warning("OpenAI API key missing; using fallback evaluation")
        logger.info("evaluation completed")
        return fallback_evaluation(target_language)

    client = OpenAI(api_key=config.openai_api_key)
    system_prompt = (
        "You are evaluating a browser-captured chatbot response from samsung.com/sec/. "
        "Use a fixed 0-10 rubric where overall_score = correctness(0-4) + relevance(0-2) + completeness(0-2) + clarity(0-1) + groundedness(0-1). "
        "If target_language is ko, write reason, fix_suggestion, and score_breakdown_explanation in natural Korean. "
        "If target_language is en, write those three fields in natural English. "
        "Do not mix Korean and English except for product names or standard abbreviations. "
        "Flags must remain canonical English identifiers. overall_score must equal the sum of the component scores. "
        "Question repetition is a hard fail and must be called out in the first sentence of reason. "
        "Carryover contamination or clear topic mismatch is a hard fail and must be called out in the first sentence of reason. "
        "Do not assign carryover_contamination when the answer covers the right product family but includes extra promo, review, or speculative noise; use promo_or_review_leak or speculative_unverified instead. "
        "If the answer looks truncated, reduce completeness. If it contains speculative exact specs or unsupported availability claims, reduce groundedness aggressively. "
        "If overall_score <= 2.0, the first sentence of reason must be clearly negative. If overall_score >= 7.0, the first sentence must be clearly positive. "
        "Return JSON only matching the provided schema."
    )
    user_prompt = {
        "page_url": pair.page_url,
        "locale": pair.locale,
        "target_language": target_language,
        "question": pair.question,
        "answer": evaluation_answer,
        "expected_keywords": test_case.expected_keywords,
        "forbidden_keywords": test_case.forbidden_keywords,
        "input_verified": pair.input_verified,
        "submit_effect_verified": pair.submit_effect_verified,
        "new_bot_response_detected": pair.new_bot_response_detected,
        "baseline_menu_detected": pair.baseline_menu_detected,
        "instructions": [
            "Evaluate only the real post-baseline bot response captured from samsung.com/sec/.",
            "Use the fixed 0-10 rubric and ensure the component sum exactly matches overall_score.",
            "Lower the score aggressively for vague, evasive, incomplete, unsupported, or language-mismatched answers.",
            "Set needs_human_review to true when the answer quality is weak or uncertain.",
            "Return flags from the allowed enum only, and use an empty list when no flags apply.",
        ],
    }

    try:
        response = client.responses.create(
            model=config.openai_model,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps(user_prompt, ensure_ascii=False)}],
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "rubicon_ui_qa_evaluation",
                    "schema": EVALUATION_SCHEMA,
                    "strict": True,
                }
            },
        )
        payload = json.loads(_response_text(response))
        result = _apply_quality_guardrails(test_case, pair, _coerce_eval_payload(payload, target_language))
        logger.info("evaluation completed")
        return result
    except Exception as exc:
        logger.exception("OpenAI evaluation failed: %s", exc)
        logger.info("evaluation completed")
        return fallback_evaluation(target_language)
