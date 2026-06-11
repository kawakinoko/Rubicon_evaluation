"""Tests for editable-only ranked input candidate filtering."""

from __future__ import annotations

from app.samsung_rubicon import (
    _candidate_debug_line,
    _candidate_is_disabled_like,
    _candidate_has_ready_hint,
    _grade_candidate_state,
    _is_ready_composer_candidate,
    _is_transition_disabled_candidate,
    _score_ranked_candidate,
)


def _candidate(**overrides):
    base = {
        "visible": True,
        "enabled": True,
        "editable": True,
        "readonly": False,
        "aria_disabled": False,
        "aria_readonly": False,
        "disabled": False,
        "contenteditable": "false",
        "role": "",
        "tag_name": "textarea",
        "placeholder": "질문을 입력하세요",
        "aria_label": "",
        "bbox_width": 320,
        "bbox_height": 44,
    }
    base.update(overrides)
    return base


def test_disabled_textarea_and_editable_contenteditable_prefers_editable_candidate():
    disabled_textarea = _candidate(disabled=True, enabled=False, editable=False)
    editable_div = _candidate(tag_name="div", contenteditable="true", role="textbox")
    disabled_grade, _ = _grade_candidate_state(disabled_textarea)
    editable_grade, _ = _grade_candidate_state(editable_div)
    assert disabled_grade == "C"
    assert editable_grade in {"A", "B"}
    assert _score_ranked_candidate(editable_div, editable_grade, "frame[1]", "frame[1]") > _score_ranked_candidate(disabled_textarea, disabled_grade, "frame[1]", "frame[1]")


def test_aria_readonly_textbox_is_excluded():
    readonly_candidate = _candidate(role="textbox", tag_name="div", contenteditable="true", aria_readonly=True, editable=False)
    grade, reason = _grade_candidate_state(readonly_candidate)
    assert grade == "C"
    assert reason == "readonly"


def test_zero_size_input_is_excluded():
    zero_size = _candidate(bbox_width=0, bbox_height=0)
    grade, reason = _grade_candidate_state(zero_size)
    assert grade == "C"
    assert reason == "zero_size"


def test_visible_but_disabled_candidate_is_evidence_only():
    disabled_candidate = _candidate(disabled=True, enabled=False, editable=False)
    grade, reason = _grade_candidate_state(disabled_candidate)
    assert grade == "C"
    assert reason == "disabled"


def test_placeholder_shell_is_treated_as_disabled_like_evidence():
    shell_candidate = _candidate(
        editable=False,
        placeholder="대화창에 더이상 입력할 수 없습니다.",
        aria_label="대화창에 더이상 입력할 수 없습니다.",
    )
    grade, reason = _grade_candidate_state(shell_candidate)
    assert grade == "C"
    assert reason == "placeholder_shell"
    assert _candidate_is_disabled_like({"grade": grade, "reason": reason, "disabled": False}) is True


def test_transition_disabled_candidate_detected_from_placeholder():
    candidate = _candidate(
        disabled=True,
        editable=False,
        tag_name="textarea",
        placeholder="대화창에 더이상 입력할 수 없습니다.",
        aria_label="대화창에 더이상 입력할 수 없습니다.",
    )
    assert _is_transition_disabled_candidate(candidate) is True


def test_ready_composer_candidate_detected_from_ready_placeholder():
    candidate = _candidate(
        disabled=False,
        editable=True,
        tag_name="textarea",
        placeholder="무엇이든지 물어 보세요",
    )
    assert _is_ready_composer_candidate(candidate) is True


def test_ready_hint_detected_from_chat_message_aria():
    candidate = _candidate(
        disabled=False,
        editable=False,
        tag_name="div",
        aria_label="대화 중 메시지",
    )
    grade, reason = _grade_candidate_state(candidate)
    assert _candidate_has_ready_hint(candidate) is True
    assert _is_ready_composer_candidate(candidate) is True
    assert grade == "C"
    assert reason == "not_final_target"


def test_candidate_debug_line_tolerates_missing_grade_and_reason():
    candidate = {
        "score": 104.7,
        "selector": "textarea",
        "scope_name": "spr-chat__box-frame",
        "visible": True,
        "editable": True,
        "disabled": False,
    }

    debug_line = _candidate_debug_line(candidate)

    assert "selector=textarea" in debug_line
    assert "grade=?" in debug_line
    assert "reason=?" in debug_line
