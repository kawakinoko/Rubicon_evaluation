"""Tests for the activation state machine."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.config import AppConfig
from app.logger import create_logger
from app.samsung_rubicon import configure_runtime, ensure_composer_ready, wait_for_composer_transition


class _DummyPage:
    def wait_for_timeout(self, _: int) -> None:
        return None


class _DummyLocator:
    def click(self, timeout: int = 0) -> None:
        return None


def _make_config() -> AppConfig:
    return AppConfig(
        project_root=Path("/tmp/rubicon-activation-tests"),
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
        run_mode="standard",
    )


def test_activation_sequence_succeeds_when_editable_candidate_appears(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime.log"))
    context = SimpleNamespace(container_locator=None, input_locator=None, scope=SimpleNamespace())
    rounds = [
        [{"selector": "textarea", "disabled": True, "editable": False, "visible": True}],
        [{"selector": ".ql-editor", "disabled": False, "editable": True, "visible": True, "scope": context.scope, "scope_name": "resolved_ctx", "locator": _DummyLocator()}],
    ]
    with (
        patch("app.samsung_rubicon._collect_lightweight_candidates", side_effect=rounds),
        patch("app.samsung_rubicon._iter_fast_transition_contexts", return_value=[("resolved_ctx", context.scope)]),
        patch("app.samsung_rubicon._assign_candidate_to_context"),
        patch("app.samsung_rubicon._activation_targets", return_value=[("chat_container", _DummyLocator())]),
    ):
        result = ensure_composer_ready(_DummyPage(), context)
    assert result["activation_success"] is True
    assert result["editable_candidates_after_activation"] == 1


def test_activation_rescan_moves_past_disabled_only_state(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime-2.log"))
    context = SimpleNamespace(container_locator=None, input_locator=None, scope=SimpleNamespace())
    rounds = [
        [{"selector": "textarea", "disabled": True, "editable": False, "visible": True}],
        [{"selector": "[role='textbox']", "disabled": False, "editable": True, "visible": True, "scope": context.scope, "scope_name": "resolved_ctx", "locator": _DummyLocator()}],
    ]
    with (
        patch("app.samsung_rubicon._collect_lightweight_candidates", side_effect=rounds),
        patch("app.samsung_rubicon._iter_fast_transition_contexts", return_value=[("resolved_ctx", context.scope)]),
        patch("app.samsung_rubicon._assign_candidate_to_context"),
        patch("app.samsung_rubicon._activation_targets", return_value=[("textarea_parent", _DummyLocator())]),
    ):
        result = ensure_composer_ready(_DummyPage(), context)
    assert result["activation_attempted"] is True
    assert result["activation_success"] is True
    assert any(step.endswith("textarea_parent") for step in result["activation_steps"])


def test_activation_uses_rescan_rounds_before_exhausting(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime-3.log"))
    context = SimpleNamespace(container_locator=None, input_locator=None, scope=SimpleNamespace())
    rounds = [
        [{"selector": "textarea", "disabled": True, "editable": False, "visible": True}],
        [{"selector": "[role='textbox']", "disabled": False, "editable": True, "visible": True, "scope": context.scope, "scope_name": "resolved_ctx", "locator": _DummyLocator()}],
    ]
    with (
        patch("app.samsung_rubicon._collect_lightweight_candidates", side_effect=rounds),
        patch("app.samsung_rubicon._iter_fast_transition_contexts", return_value=[("resolved_ctx", context.scope)]),
        patch("app.samsung_rubicon._assign_candidate_to_context"),
        patch("app.samsung_rubicon._activation_targets", return_value=[("footer", _DummyLocator())]),
    ):
        result = ensure_composer_ready(_DummyPage(), context)
    assert result["activation_success"] is True
    assert result["editable_candidates_after_activation"] == 1
    assert any(step.startswith("round2:") for step in result["activation_steps"])


def test_wait_for_composer_transition_disabled_to_ready(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime-4.log"))
    context = SimpleNamespace(scope=SimpleNamespace())
    rounds = [
        [{"selector": "textarea", "visible": True, "disabled": True, "editable": False, "tag_name": "textarea", "placeholder": "대화창에 더이상 입력할 수 없습니다.", "aria_label": "대화창에 더이상 입력할 수 없습니다."}],
        [{"selector": "textarea", "visible": True, "disabled": True, "editable": False, "tag_name": "textarea", "placeholder": "대화창에 더이상 입력할 수 없습니다.", "aria_label": "대화창에 더이상 입력할 수 없습니다."}],
        [{"selector": "textarea", "visible": True, "disabled": False, "editable": True, "tag_name": "textarea", "placeholder": "무엇이든지 물어 보세요", "aria_label": "", "scope": context.scope, "scope_name": "resolved_ctx", "locator": _DummyLocator()}],
        [{"selector": "textarea", "visible": True, "disabled": False, "editable": True, "tag_name": "textarea", "placeholder": "무엇이든지 물어 보세요", "aria_label": "", "scope": context.scope, "scope_name": "resolved_ctx", "locator": _DummyLocator()}],
    ]
    with (
        patch("app.samsung_rubicon._iter_fast_transition_contexts", return_value=[("resolved_ctx", context.scope)]),
        patch("app.samsung_rubicon._collect_lightweight_candidates", side_effect=rounds),
    ):
        result = wait_for_composer_transition(_DummyPage(), context, "case01", _make_config())
    assert result["transition_ready"] is True
    assert result["transition_timeout"] is False
    assert result["transition_reason"] == "composer_became_ready"


def test_wait_for_composer_transition_timeout(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime-5.log"))
    context = SimpleNamespace(scope=SimpleNamespace())
    disabled_round = [{"selector": "textarea", "visible": True, "disabled": True, "editable": False, "tag_name": "textarea", "placeholder": "대화창에 더이상 입력할 수 없습니다.", "aria_label": "대화창에 더이상 입력할 수 없습니다."}]
    monotonic_values = [0.0, 0.0, 5.0, 10.0, 15.0, 20.1]
    with (
        patch("app.samsung_rubicon._iter_fast_transition_contexts", return_value=[("resolved_ctx", context.scope)]),
        patch("app.samsung_rubicon._collect_lightweight_candidates", return_value=disabled_round),
        patch("app.samsung_rubicon.time.monotonic", side_effect=monotonic_values),
    ):
        result = wait_for_composer_transition(_DummyPage(), context, "case01", _make_config())
    assert result["transition_ready"] is False
    assert result["transition_timeout"] is True
    assert result["transition_reason"] == "composer_transition_timeout"


def test_wait_for_composer_transition_accepts_strong_ready_hint(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime-6.log"))
    context = SimpleNamespace(scope=SimpleNamespace())
    ready_round = [{
        "selector": "[aria-label*='메시지' i]",
        "visible": True,
        "disabled": False,
        "editable": False,
        "tag_name": "div",
        "placeholder": "",
        "aria_label": "무엇이든 물어보세요",
        "scope": context.scope,
        "scope_name": "resolved_ctx",
        "locator": _DummyLocator(),
    }]
    with (
        patch("app.samsung_rubicon._iter_fast_transition_contexts", return_value=[("resolved_ctx", context.scope)]),
        patch("app.samsung_rubicon._collect_lightweight_candidates", side_effect=[ready_round, ready_round]),
        patch("app.samsung_rubicon._collect_related_ready_candidates", return_value=[]),
    ):
        result = wait_for_composer_transition(_DummyPage(), context, "case01", _make_config())
    assert result["transition_ready"] is True
    assert result["transition_timeout"] is False
    assert result["transition_reason"] == "composer_became_ready"
