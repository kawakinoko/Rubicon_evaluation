"""CSV loader for chatbot QA test cases."""

from __future__ import annotations

import csv
from pathlib import Path

from app.models import TestCase
from app.scenario_tags import enrich_test_case_metadata


def _parse_keywords(raw: str) -> list[str]:
    return [item.strip() for item in raw.split("|") if item.strip()]


def load_test_cases(
    csv_path: Path,
    max_questions: int | None = None,
    selected_case_ids: list[str] | None = None,
) -> list[TestCase]:
    """Load test cases from the configured CSV file."""

    cases: list[TestCase] = []
    selected = {case_id.strip() for case_id in (selected_case_ids or []) if case_id.strip()}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            case_id = row["id"].strip()
            if selected and case_id not in selected:
                continue
            cases.append(
                enrich_test_case_metadata(TestCase(
                    id=case_id,
                    category=row["category"].strip(),
                    locale=row.get("locale", "ko-KR").strip() or "ko-KR",
                    page_url=row.get("page_url", "https://www.samsung.com/sec/").strip(),
                    question=row["question"].strip(),
                    expected_keywords=_parse_keywords(row.get("expected_keywords", "")),
                    forbidden_keywords=_parse_keywords(row.get("forbidden_keywords", "")),
                ))
            )

    if max_questions is None or max_questions <= 0:
        return cases
    return cases[:max_questions]
