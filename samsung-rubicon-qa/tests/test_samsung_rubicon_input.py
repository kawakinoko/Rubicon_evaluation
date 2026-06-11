"""Tests for input candidate scoring and question-entry fallback behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.config import AppConfig
from app.logger import create_logger
from app.samsung_rubicon import (
    _select_report_answer,
    _classify_input_candidate_metadata,
    _detect_login_gate,
    _input_is_editable,
    _status_from_failure_category,
    _score_input_candidate_metadata,
    configure_runtime,
    enter_question_with_verification,
    ensure_clean_conversation,
    submit_question,
    wait_for_answer_completion,
    wait_for_new_bot_response,
)


class _FakeScope:
    name = "spr-chat__box-frame"

    def __init__(self, login_required=False):
        self.login_required = login_required

    def evaluate(self, expression: str, arg=None):
        if "const text =" in expression and "buttons" in expression:
            if self.login_required:
                return {
                    "text": "대화를 시작하려면 Samsung AI Assistant에 로그인하세요 로그인 / 회원가입",
                    "buttons": [{"text": "로그인 / 회원가입", "aria": "", "disabled": False}],
                }
            return {"text": "", "buttons": []}
        raise RuntimeError("unexpected scope evaluate")


class _FakeLocator:
    def __init__(self, *, editable=True, value="", input_type="textarea", role="", contenteditable="false"):
        self.editable = editable
        self.value = value
        self.input_type = input_type
        self.role = role
        self.contenteditable = contenteditable
        self.clicks = 0

    def scroll_into_view_if_needed(self, timeout: int = 0) -> None:
        return None

    def click(self, timeout: int = 0) -> None:
        self.clicks += 1

    def fill(self, value: str, timeout: int = 0) -> None:
        self.value = value

    def press(self, key: str) -> None:
        if key == "Control+A":
            return None
        if key == "Backspace":
            self.value = ""

    def press_sequentially(self, value: str, delay: int = 0) -> None:
        self.value = value

    def input_value(self, timeout: int = 0) -> str:
        return self.value

    def inner_text(self, timeout: int = 0) -> str:
        return self.value

    def text_content(self, timeout: int = 0) -> str:
        return self.value

    def evaluate(self, expression: str, arg=None):
        if "const inputLike" in expression:
            input_like = self.input_type in {"input", "textarea"} or self.role == "textbox" or self.contenteditable not in {"", "false", "inherit"}
            return self.editable and input_like
        if expression.strip() == "el => el.tagName.toLowerCase()":
            return self.input_type
        if expression.strip() == "el => el.contentEditable":
            return self.contenteditable
        if "const disabled" in expression:
            return self.editable
        return None


class _FakePage:
    def __init__(self, raise_on_evaluate: bool = False):
        self.raise_on_evaluate = raise_on_evaluate
        self.evaluate_calls: list[str] = []
        self.wait_calls: list[int] = []

    def evaluate(self, expression: str):
        self.evaluate_calls.append(expression)
        if self.raise_on_evaluate:
            raise RuntimeError("sdk unavailable")
        return None

    def wait_for_timeout(self, timeout_ms: int) -> None:
        self.wait_calls.append(timeout_ms)


def _make_config() -> AppConfig:
    return AppConfig(
        project_root=Path("/tmp/rubicon-input-tests"),
        openai_api_key="",
        samsung_base_url="https://www.samsung.com/sec/",
        headless=True,
        default_locale="ko-KR",
        max_questions=1,
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


class TestInputCandidateScoring:
    def test_visible_editable_textarea_scores_higher(self):
        good = {
            "tag": "textarea",
            "type": "",
            "role": "",
            "placeholder": "메시지를 입력",
            "ariaLabel": "",
            "visible": True,
            "editable": True,
            "disabled": False,
            "obscured": False,
            "footerLike": True,
            "rectTop": 900,
            "viewportHeight": 1200,
            "contentEditable": "",
        }
        bad = {
            "tag": "div",
            "type": "",
            "role": "",
            "placeholder": "",
            "ariaLabel": "",
            "visible": False,
            "editable": False,
            "disabled": True,
            "obscured": True,
            "footerLike": False,
            "rectTop": 10,
            "viewportHeight": 1200,
            "contentEditable": "",
        }
        assert _score_input_candidate_metadata(good, "chat-frame", "chat-frame") > _score_input_candidate_metadata(bad, "chat-frame", "page")


class TestInputCandidateClassification:
    def test_disabled_candidate_is_classified(self):
        category, reason = _classify_input_candidate_metadata({"disabled": True, "editable": False, "obscured": False})
        assert category == "input locator found but disabled"
        assert "disabled" in reason

    def test_obscured_candidate_is_classified(self):
        category, reason = _classify_input_candidate_metadata({"disabled": False, "editable": True, "obscured": True})
        assert category == "input locator found but obscured by overlay"
        assert "obscured" in reason


def test_enter_question_uses_focus_proxy_when_ready_wrapper_is_not_editable(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime.log"))
    wrapper = _FakeLocator(editable=False, value="")
    proxy = _FakeLocator(editable=True, value="")
    logger = create_logger(tmp_path / "runtime-2.log")

    with patch("app.samsung_rubicon._resolve_focus_proxy_candidate", return_value=(proxy, ".ql-editor")):
        verified, method, effective_locator, effective_selector = enter_question_with_verification(_FakeScope(), wrapper, "배터리 교체 문의", logger)

    assert verified is True
    assert method == "fill"
    assert effective_locator is proxy
    assert effective_selector == ".ql-editor"
    assert proxy.value == "배터리 교체 문의"


def test_input_is_editable_rejects_non_input_ready_wrapper():
    wrapper = _FakeLocator(editable=True, value="", input_type="div", role="", contenteditable="false")
    assert _input_is_editable(wrapper) is False


def test_detect_login_gate_from_visible_text_and_button(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime-login.log"))
    payload = _detect_login_gate(SimpleNamespace(scope=_FakeScope(login_required=True)))
    assert payload["login_required"] is True
    assert "login" in payload["reason"].lower()


def test_status_maps_login_required_to_failed():
    assert _status_from_failure_category("login_required") == "failed"


def test_submit_question_uses_ready_signal_candidate_with_focus_proxy(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime-3.log"))
    wrapper = _FakeLocator(editable=False, value="")
    proxy = _FakeLocator(editable=True, value="")
    context = SimpleNamespace(
        scope=_FakeScope(),
        scope_name="spr-chat__box-frame",
        input_locator=wrapper,
        input_scope=None,
        input_scope_name="spr-chat__box-frame",
        input_selector="[placeholder*='무엇이든 물어보세요' i]",
        input_candidate_score=78.0,
        send_locator=None,
        container_locator=None,
        page=SimpleNamespace(),
        baseline_bot_messages=[],
        baseline_bot_count=0,
        baseline_history=[],
        baseline_visible_text="",
        baseline_visible_blocks=[],
        baseline_message_nodes_snapshot=[],
        baseline_send_button_enabled=None,
        ranked_input_candidates=[],
        input_candidate_logs=[],
        input_candidates_debug="",
    )
    candidate = {
        "locator": wrapper,
        "scope": context.scope,
        "scope_name": "spr-chat__box-frame",
        "selector": "[placeholder*='무엇이든 물어보세요' i]",
        "score": 78.0,
        "grade": "B",
        "reason": "ready_signal",
        "visible": True,
        "enabled": True,
        "editable": False,
        "disabled": False,
        "readonly": False,
        "aria_disabled": False,
        "aria_readonly": False,
        "placeholder": "무엇이든 물어보세요",
        "aria_label": "",
        "bbox_width": 320,
        "bbox_height": 44,
        "contenteditable": "false",
        "role": "textbox",
        "tag_name": "div",
        "failure_category": "",
        "failure_reason": "",
    }

    with (
        patch("app.samsung_rubicon.capture_baseline_state", return_value={}),
        patch("app.samsung_rubicon.collect_ranked_input_candidates", return_value=[candidate]),
        patch("app.samsung_rubicon._resolve_focus_proxy_candidate", return_value=(proxy, ".ql-editor")),
        patch("app.samsung_rubicon.verify_input_dom_state", return_value=True),
        patch("app.samsung_rubicon.capture_named_artifact", return_value=("before-full.png", "before-chat.png")),
        patch("app.samsung_rubicon.trigger_submit", return_value=(True, "enter", True, "after-chat.png", "after-full.png")),
        patch("app.samsung_rubicon.first_visible_locator", return_value=(None, None)),
    ):
        evidence = submit_question(SimpleNamespace(), context, "배터리 교체 문의")

    assert evidence.input_dom_verified is True
    assert evidence.submit_effect_verified is True
    assert evidence.input_verified is True
    assert evidence.input_method_used == "fill"
    assert evidence.input_selector == ".ql-editor"
    assert evidence.user_message_echo_verified is True


def test_ensure_clean_conversation_falls_back_to_menu_when_sdk_fails(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime-clean-1.log"))
    page = _FakePage(raise_on_evaluate=True)
    dirty_context = SimpleNamespace(scope=object(), scope_name="spr-chat__box-frame")
    clean_context = SimpleNamespace(scope=object(), scope_name="spr-chat__box-frame")

    with (
        patch("app.samsung_rubicon._has_stale_conversation_messages", side_effect=[(True, ["old message"]), (False, [])]),
        patch("app.samsung_rubicon._end_conversation_via_menu", return_value=True) as menu_reset,
        patch("app.samsung_rubicon.open_chat_widget_or_conversation", return_value={"open_ok": True}),
        patch("app.samsung_rubicon.resolve_chat_context", return_value=clean_context),
    ):
        result = ensure_clean_conversation(page, dirty_context)

    assert result is clean_context
    assert menu_reset.called is True


def test_ensure_clean_conversation_uses_menu_when_sdk_reset_stays_dirty(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime-clean-2.log"))
    page = _FakePage(raise_on_evaluate=False)
    dirty_context = SimpleNamespace(scope=object(), scope_name="spr-chat__box-frame")
    still_dirty_context = SimpleNamespace(scope=object(), scope_name="spr-chat__box-frame")
    clean_context = SimpleNamespace(scope=object(), scope_name="spr-chat__box-frame")

    with (
        patch(
            "app.samsung_rubicon._has_stale_conversation_messages",
            side_effect=[(True, ["old message"]), (True, ["still old"]), (False, [])],
        ),
        patch("app.samsung_rubicon._end_conversation_via_menu", return_value=True) as menu_reset,
        patch("app.samsung_rubicon.open_chat_widget_or_conversation", return_value={"open_ok": True}),
        patch("app.samsung_rubicon.resolve_chat_context", side_effect=[still_dirty_context, clean_context]),
    ):
        result = ensure_clean_conversation(page, dirty_context)

    assert result is clean_context
    assert menu_reset.call_count == 1


def test_submit_question_stops_early_when_login_required(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime-4.log"))
    wrapper = _FakeLocator(editable=False, value="")
    context = SimpleNamespace(
        scope=_FakeScope(login_required=True),
        scope_name="spr-chat__box-frame",
        input_locator=wrapper,
        input_scope=None,
        input_scope_name="spr-chat__box-frame",
        input_selector="[aria-label*='대화 중 메시지' i]",
        input_candidate_score=78.0,
        send_locator=None,
        container_locator=None,
        page=SimpleNamespace(),
        baseline_bot_messages=[],
        baseline_bot_count=0,
        baseline_history=[],
        baseline_visible_text="",
        baseline_visible_blocks=[],
        baseline_message_nodes_snapshot=[],
        baseline_send_button_enabled=None,
        ranked_input_candidates=[],
        input_candidate_logs=[],
        input_candidates_debug="",
    )
    candidate = {
        "locator": wrapper,
        "scope": context.scope,
        "scope_name": "spr-chat__box-frame",
        "selector": "[aria-label*='대화 중 메시지' i]",
        "score": 78.0,
        "grade": "B",
        "reason": "ready_signal",
        "visible": True,
        "enabled": True,
        "editable": False,
        "disabled": False,
        "readonly": False,
        "aria_disabled": False,
        "aria_readonly": False,
        "placeholder": "",
        "aria_label": "대화 중 메시지",
        "bbox_width": 320,
        "bbox_height": 44,
        "contenteditable": "false",
        "role": "textbox",
        "tag_name": "div",
        "failure_category": "",
        "failure_reason": "",
    }
    with (
        patch("app.samsung_rubicon.capture_baseline_state", return_value={}),
        patch("app.samsung_rubicon.collect_ranked_input_candidates", return_value=[candidate]),
    ):
        evidence = submit_question(SimpleNamespace(), context, "배터리 교체 문의")

    assert evidence.input_verified is False
    assert evidence.input_failure_category == "login_required"
    assert "login" in evidence.input_failure_reason.lower()


def test_wait_for_new_bot_response_passes_question_to_completion(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime-5.log"))
    context = SimpleNamespace(baseline_bot_count=0, baseline_bot_messages=[])

    with (
        patch("app.samsung_rubicon.extract_bot_message_texts", return_value=[]),
        patch("app.samsung_rubicon.wait_for_answer_completion") as mock_wait,
    ):
        wait_for_new_bot_response(context, 3, question="배터리 교체는 어디서 하나요?")

    assert context.baseline_bot_count == 3
    mock_wait.assert_called_once_with(context, question="배터리 교체는 어디서 하나요?")


def test_select_report_answer_prefers_verified_wait_answer():
    wait_answer = "갤럭시 S24 배터리 교체는 삼성전자 서비스센터에서 진행할 수 있어요."
    dom_answer = "4월 5일 (일) 첨부 ... 갤럭시 S24 배터리 교체는 삼성전자 서비스센터에서 진행할 수 있어요."

    selected = _select_report_answer(wait_answer, dom_answer, True)

    assert selected == wait_answer


def test_select_report_answer_falls_back_to_dom_when_wait_answer_missing():
    dom_answer = "갤럭시 S24 배터리 교체는 삼성전자 서비스센터에서 진행할 수 있어요."

    selected = _select_report_answer("", dom_answer, True)

    assert selected == dom_answer


def test_select_report_answer_rejects_stale_carryover_dom_answer():
    wait_answer = ""
    dom_answer = (
        "4월 13일 (월) 갤럭시 S26 울트라의 디스플레이 크기와 카메라 구성 그리고 배터리 같은 핵심 사양을 알려주세요. "
        "갤럭시 S26 울트라는 6.9형 디스플레이와 5,000mAh 배터리를 제공합니다."
    )

    selected = _select_report_answer(
        wait_answer,
        dom_answer,
        True,
        question="갤럭시 버즈3 프로의 배터리 시간과 방수 등급 그리고 주요 오디오 기능을 알려주세요.",
        baseline_last_answer="갤럭시 S26 울트라는 6.9형 디스플레이와 5,000mAh 배터리를 제공합니다.",
        baseline_topic_family="phone",
    )

    assert selected == ""


def test_select_report_answer_rejects_truncated_dom_answer():
    selected = _select_report_answer(
        "",
        "갤럭시 북5 프로 360 16형은 무게 1.69kg, 배터리 76.1Wh, 포트는 HDMI 2.1 + 썬더볼트4 2개 + USB-A까지 갖춘 구성이에요. 요청하신 3가지 기준으로",
        True,
        question="갤럭시 북5 프로 360의 무게와 배터리 그리고 포트 구성을 알려주세요.",
    )

    assert selected == ""


def test_wait_for_answer_completion_uses_fast_exit_for_meaningful_stable_answer(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime-fast-answer.log"))

    class _Scope:
        def wait_for_timeout(self, _: int) -> None:
            return None

    context = SimpleNamespace(scope=_Scope(), baseline_bot_count=0, baseline_bot_messages=[])
    candidate_payload = {
        "current_bot_count": 1,
        "bot_count_increased": True,
        "new_bot_segments": [],
        "diff_segments": [],
        "strict_candidates": ["배터리 교체는 가까운 삼성전자서비스 센터에서 점검 후 진행할 수 있으며 방문 접수가 가장 빠릅니다."],
        "fallback_candidates": [],
        "answer": "배터리 교체는 가까운 삼성전자서비스 센터에서 점검 후 진행할 수 있으며 방문 접수가 가장 빠릅니다.",
    }

    with (
        patch("app.samsung_rubicon.build_post_baseline_answer_candidates", side_effect=[candidate_payload, candidate_payload]),
        patch("app.samsung_rubicon._loading_visible", return_value=False),
    ):
        result = wait_for_answer_completion(context, question="배터리 교체는 어디서 하나요?")

    assert result.new_bot_response_detected is True
    assert "삼성전자서비스 센터" in result.answer


def test_wait_for_answer_completion_recovers_last_bot_message_after_timeout(tmp_path):
    configure_runtime(_make_config(), create_logger(tmp_path / "runtime-timeout-recovery.log"))

    class _Scope:
        def wait_for_timeout(self, _: int) -> None:
            return None

    context = SimpleNamespace(
        scope=_Scope(),
        baseline_bot_count=0,
        baseline_bot_messages=[],
        baseline_last_answer="",
        baseline_topic_family="unknown",
    )
    candidate_payload = {
        "current_bot_count": 1,
        "bot_count_increased": True,
        "new_bot_segments": [],
        "diff_segments": [],
        "strict_candidates": [],
        "fallback_candidates": [],
        "answer": "",
    }
    recovered_payload = {
        "actual_answer": "배터리 교체는 가까운 삼성전자서비스 센터에서 접수 후 진행할 수 있습니다.",
        "actual_answer_clean": "배터리 교체는 가까운 삼성전자서비스 센터에서 접수 후 진행할 수 있습니다.",
        "answer_raw": "배터리 교체는 가까운 삼성전자서비스 센터에서 접수 후 진행할 수 있습니다.",
        "extraction_source": "dom_main_answer",
    }

    with (
        patch("app.samsung_rubicon._answer_wait_settings", return_value=(0.01, 1, 0.01)),
        patch("app.samsung_rubicon.build_post_baseline_answer_candidates", return_value=candidate_payload),
        patch("app.samsung_rubicon.extract_last_answer", return_value=recovered_payload),
        patch("app.samsung_rubicon.time.perf_counter", side_effect=[0.0, 0.0, 0.02, 0.03]),
    ):
        result = wait_for_answer_completion(context, question="배터리 교체는 어디서 하나요?")

    assert result.new_bot_response_detected is True
    assert "삼성전자서비스 센터" in result.answer