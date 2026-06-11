"""Tests for the CSV test-case loader."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest

from app.csv_loader import load_test_cases


def _write_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = ["id", "category", "locale", "page_url", "question", "expected_keywords", "forbidden_keywords"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_load_test_cases_basic():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "questions.csv"
        _write_csv(
            csv_path,
            [
                {
                    "id": "c01",
                    "category": "service",
                    "locale": "ko-KR",
                    "page_url": "https://www.samsung.com/sec/",
                    "question": "배터리 교체는 어디서?",
                    "expected_keywords": "서비스센터|배터리",
                    "forbidden_keywords": "로그인",
                }
            ],
        )
        cases = load_test_cases(csv_path)
        assert len(cases) == 1
        case = cases[0]
        assert case.id == "c01"
        assert case.category == "service"
        assert case.locale == "ko-KR"
        assert case.question == "배터리 교체는 어디서?"
        assert case.expected_keywords == ["서비스센터", "배터리"]
        assert case.forbidden_keywords == ["로그인"]


def test_load_test_cases_max_questions():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "questions.csv"
        rows = [
            {
                "id": f"c0{i}",
                "category": "test",
                "locale": "ko-KR",
                "page_url": "https://www.samsung.com/sec/",
                "question": f"질문 {i}",
                "expected_keywords": "",
                "forbidden_keywords": "",
            }
            for i in range(1, 6)
        ]
        _write_csv(csv_path, rows)
        cases = load_test_cases(csv_path, max_questions=3)
        assert len(cases) == 3
        assert cases[0].id == "c01"
        assert cases[2].id == "c03"


def test_load_test_cases_max_questions_zero_returns_all():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "questions.csv"
        rows = [
            {
                "id": f"c0{i}",
                "category": "test",
                "locale": "ko-KR",
                "page_url": "https://www.samsung.com/sec/",
                "question": f"질문 {i}",
                "expected_keywords": "",
                "forbidden_keywords": "",
            }
            for i in range(1, 4)
        ]
        _write_csv(csv_path, rows)
        cases = load_test_cases(csv_path, max_questions=0)
        assert len(cases) == 3


def test_load_test_cases_default_locale():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "questions.csv"
        fieldnames = ["id", "category", "page_url", "question", "expected_keywords", "forbidden_keywords"]
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "id": "c01",
                    "category": "test",
                    "page_url": "https://www.samsung.com/sec/",
                    "question": "질문",
                    "expected_keywords": "",
                    "forbidden_keywords": "",
                }
            )
        cases = load_test_cases(csv_path)
        assert cases[0].locale == "ko-KR"


def test_load_test_cases_selected_case_ids():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "questions.csv"
        rows = [
            {
                "id": f"case0{i}",
                "category": "test",
                "locale": "ko-KR",
                "page_url": "https://www.samsung.com/sec/",
                "question": f"질문 {i}",
                "expected_keywords": "",
                "forbidden_keywords": "",
            }
            for i in range(1, 5)
        ]
        _write_csv(csv_path, rows)

        cases = load_test_cases(csv_path, selected_case_ids=["case02", "case04"])

        assert [case.id for case in cases] == ["case02", "case04"]


def test_load_real_questions_csv():
    """Smoke-test that the bundled questions.csv can be parsed."""
    csv_path = Path(__file__).resolve().parent.parent / "testcases" / "questions.csv"
    cases = load_test_cases(csv_path)
    assert len(cases) >= 1
    for case in cases:
        assert case.id
        assert case.question
        assert case.page_url.startswith("https://")
