"""Tests for shared utility helpers."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.utils import (
    artifact_timestamp,
    compile_regex,
    sanitize_filename,
    utc_now_timestamp,
    write_json,
)


class TestUtcNowTimestamp:
    def test_returns_iso8601_string(self):
        ts = utc_now_timestamp()
        assert isinstance(ts, str)
        assert "T" in ts
        assert ts.endswith("+00:00")


class TestArtifactTimestamp:
    def test_returns_filename_safe_string(self):
        ts = artifact_timestamp()
        assert isinstance(ts, str)
        assert re.fullmatch(r"\d{8}_\d{6}", ts), f"Unexpected format: {ts}"


class TestSanitizeFilename:
    def test_basic_ascii(self):
        assert sanitize_filename("case01") == "case01"

    def test_spaces_replaced(self):
        result = sanitize_filename("hello world")
        assert " " not in result
        assert "_" in result

    def test_special_chars_removed(self):
        result = sanitize_filename("test/case:01?")
        assert "/" not in result
        assert ":" not in result
        assert "?" not in result

    def test_empty_string_returns_case(self):
        assert sanitize_filename("") == "case"

    def test_korean_chars(self):
        result = sanitize_filename("갤럭시 S24")
        assert " " not in result


class TestCompileRegex:
    def test_returns_compiled_pattern(self):
        pattern = compile_regex(r"chat|챗봇")
        assert isinstance(pattern, re.Pattern)

    def test_case_insensitive(self):
        pattern = compile_regex(r"chat")
        assert pattern.search("CHAT")
        assert pattern.search("chat")

    def test_korean_pattern(self):
        pattern = compile_regex(r"배터리|교체")
        assert pattern.search("배터리 교체")


class TestWriteJson:
    def test_creates_file(self, tmp_path: Path):
        output = tmp_path / "out" / "data.json"
        write_json(output, {"key": "value"})
        assert output.exists()

    def test_content_is_valid_json(self, tmp_path: Path):
        import json

        output = tmp_path / "data.json"
        payload = [{"id": 1, "text": "안녕하세요"}]
        write_json(output, payload)
        loaded = json.loads(output.read_text(encoding="utf-8"))
        assert loaded == payload

    def test_korean_characters_not_escaped(self, tmp_path: Path):
        output = tmp_path / "data.json"
        write_json(output, {"msg": "안녕하세요"})
        content = output.read_text(encoding="utf-8")
        assert "안녕하세요" in content
