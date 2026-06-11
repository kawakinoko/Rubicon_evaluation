"""Scenario metadata enrichment for harness-oriented execution."""

from __future__ import annotations

from dataclasses import replace

from app.models import TestCase

RELEASED_PRODUCT_OVERRIDES = [
    "갤럭시 s26",
    "갤럭시 s26 울트라",
    "갤럭시 s26 플러스",
    "galaxy s26",
    "galaxy s26 ultra",
    "galaxy s26 plus",
]

PRODUCT_FAMILY_RULES = {
    "phone": ["갤럭시 s26", "galaxy s26", "울트라", "플러스", "스마트폰"],
    "laptop": ["갤럭시 북", "book", "노트북"],
    "earbuds": ["버즈", "buds", "이어버드"],
    "watch": ["워치", "watch"],
    "tv": ["oled tv", "neo qled", "qled", "tv"],
    "laundry": ["세탁", "건조", "콤보", "washer", "dryer"],
    "refrigerator": ["냉장고", "family hub", "fridge", "refrigerator"],
    "monitor": ["오디세이", "odyssey", "monitor", "모니터"],
    "ring": ["갤럭시 링", "galaxy ring", "ring"],
}

NOISE_SENSITIVE_HINTS = [
    "비교",
    "차이",
    "추천",
    "혜택",
    "가격",
    "재고",
    "family hub",
]

POLICY_SENSITIVE_HINTS = [
    "가격",
    "혜택",
    "재고",
    "구매 가능",
    "출시",
    "availability",
]


def infer_product_family(test_case: TestCase) -> str:
    haystack = " ".join([test_case.category, test_case.question, *test_case.expected_keywords]).lower()
    for family, keywords in PRODUCT_FAMILY_RULES.items():
        if any(keyword in haystack for keyword in keywords):
            return family
    return "unknown"


def infer_scenario_type(test_case: TestCase) -> str:
    question = test_case.question.lower()
    if any(token in question for token in ["비교", "차이", "compare"]):
        return "comparison"
    if any(token in question for token in POLICY_SENSITIVE_HINTS):
        return "policy_sensitive"
    if any(token in question for token in NOISE_SENSITIVE_HINTS):
        return "noise_sensitive"
    return "spec"


def infer_released_override(test_case: TestCase) -> bool:
    question = test_case.question.lower()
    category = test_case.category.lower()
    if any(keyword in question for keyword in RELEASED_PRODUCT_OVERRIDES):
        return True
    return "s26" in category


def infer_policy_tags(test_case: TestCase) -> list[str]:
    question = test_case.question.lower()
    tags: list[str] = []
    if infer_released_override(test_case):
        tags.append("released_override")
    if any(token in question for token in ["비교", "차이", "compare"]):
        tags.append("comparison")
    if any(token in question for token in POLICY_SENSITIVE_HINTS):
        tags.append("policy_sensitive")
    if any(token in question for token in NOISE_SENSITIVE_HINTS):
        tags.append("noise_sensitive")
    return tags


def enrich_test_case_metadata(test_case: TestCase) -> TestCase:
    scenario_type = infer_scenario_type(test_case)
    product_family = infer_product_family(test_case)
    released_override = infer_released_override(test_case)
    policy_tags = infer_policy_tags(test_case)
    return replace(
        test_case,
        scenario_type=scenario_type,
        product_family=product_family,
        released_override=released_override,
        policy_tags=policy_tags,
    )