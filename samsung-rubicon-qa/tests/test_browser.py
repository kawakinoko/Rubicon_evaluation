"""Tests for BrowserManager session context options."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from app.browser import BrowserManager
from app.config import AppConfig


def build_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        project_root=tmp_path,
        openai_api_key="",
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


def test_new_case_session_uses_storage_state_when_present(tmp_path: Path):
    config = build_config(tmp_path)
    config.ensure_directories()
    config.samsung_storage_state_path.write_text('{"cookies": [], "origins": []}', encoding="utf-8")

    logger = Mock()
    browser = Mock()
    context = Mock()
    page = Mock()
    browser.new_context.return_value = context
    context.new_page.return_value = page

    manager = BrowserManager(config=config, logger=logger)
    manager._browser = browser

    session = manager.new_case_session("case-1")

    assert session.page is page
    browser.new_context.assert_called_once_with(
        locale="ko-KR",
        viewport={"width": 1440, "height": 1200},
        storage_state=str(config.samsung_storage_state_path),
    )


def test_new_case_session_skips_storage_state_when_missing(tmp_path: Path):
    config = build_config(tmp_path)
    logger = Mock()
    browser = Mock()

    manager = BrowserManager(config=config, logger=logger)
    manager._browser = browser

    try:
        manager.new_case_session("case-2")
    except FileNotFoundError as exc:
        assert str(config.samsung_storage_state_path) in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError when storage state is missing")


def test_new_case_session_enables_video_only_in_debug_mode(tmp_path: Path):
    config = build_config(tmp_path)
    config = replace(config, run_mode="debug", capture_mode="debug", enable_video=True)
    config.ensure_directories()
    config.samsung_storage_state_path.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    logger = Mock()
    browser = Mock()
    context = Mock()
    page = Mock()
    browser.new_context.return_value = context
    context.new_page.return_value = page

    manager = BrowserManager(config=config, logger=logger)
    manager._browser = browser

    manager.new_case_session("case-video")

    browser.new_context.assert_called_once_with(
        locale="ko-KR",
        viewport={"width": 1440, "height": 1200},
        storage_state=str(config.samsung_storage_state_path),
        record_video_dir=str(config.video_dir),
        record_video_size={"width": 1440, "height": 1200},
    )


def test_new_case_session_skips_video_and_trace_outside_debug(tmp_path: Path):
    config = build_config(tmp_path)
    config = replace(config, run_mode="speed", enable_video=True, enable_trace=True)
    config.ensure_directories()
    config.samsung_storage_state_path.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    logger = Mock()
    browser = Mock()
    context = Mock()
    page = Mock()
    browser.new_context.return_value = context
    context.new_page.return_value = page

    manager = BrowserManager(config=config, logger=logger)
    manager._browser = browser

    manager.new_case_session("case-speed")

    browser.new_context.assert_called_once_with(
        locale="ko-KR",
        viewport={"width": 1440, "height": 1200},
        storage_state=str(config.samsung_storage_state_path),
    )
    context.tracing.start.assert_not_called()


def test_case_session_close_skips_trace_and_video_when_disabled(tmp_path: Path):
    config = build_config(tmp_path)
    context = Mock()
    page = Mock()
    page.video = None
    session = BrowserManager(config=config, logger=Mock())
    case_session = session.new_case_session if False else None
    from app.browser import CaseBrowserSession

    result = CaseBrowserSession(case_id="case-close", context=context, page=page, config=config).close()

    assert result == ("", "")
    context.tracing.stop.assert_not_called()
    context.close.assert_called_once()