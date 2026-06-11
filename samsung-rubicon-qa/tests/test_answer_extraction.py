"""Regression tests for Samsung answer cleaning and history dedupe."""

from __future__ import annotations

from app.samsung_rubicon import (
    _clear_unverified_answer_fields,
    _clean_bot_answer_candidate,
    _clean_message_history,
    _dedupe_preserve_order,
    _is_meaningful_answer_text,
    _is_noise_line,
    _looks_like_main_answer,
    _recover_dom_response_candidate,
)


def test_clean_bot_answer_candidate_removes_followup_suggestions():
    raw = """갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 진행할 수 있어요.
가까운 센터에 방문 접수로 점검 후 교체가 가능합니다.
🔍 이어서 물어보세요
가까운 서비스센터에서 바로 가능한가요?
배터리 교체 비용은 얼마나 나와요?
삼성케어플러스 가입이면 혜택이 있나요?"""

    cleaned = _clean_bot_answer_candidate(raw)

    assert "이어서 물어보세요" not in cleaned
    assert "가까운 서비스센터에서 바로 가능한가요?" not in cleaned
    assert cleaned.startswith("갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 진행할 수 있어요.")


def test_looks_like_main_answer_rejects_followup_question_chip():
    assert _looks_like_main_answer("가까운 서비스센터에서 바로 가능한가요?") is False


def test_is_noise_line_rejects_date_delivery_and_accessibility_meta():
    assert _is_noise_line("2026년 4월 5일 수신됨") is True
    assert _is_noise_line("전송됨") is True
    assert _is_noise_line("첨부") is True
    assert _is_noise_line("자세한 내용을 보려면 Enter를 누르세요") is True


def test_dedupe_preserve_order_keeps_first_unique_message_only():
    items = [
        "질문입니다.",
        "답변입니다.",
        "질문입니다.",
        "  답변입니다.  ",
        "추가 답변입니다.",
    ]

    assert _dedupe_preserve_order(items) == [
        "질문입니다.",
        "답변입니다.",
        "추가 답변입니다.",
    ]


def test_clean_message_history_focuses_current_turn_and_removes_followup_chips():
    items = [
        "반갑습니다 송제혁님 AI Chat과 함께 시작해 볼까요?",
        "고객지원이 필요하신가요? Samsung AI CS Chat 을 클릭해주세요.",
        "갤럭시 S24 배터리 교체는 어디서 할 수 있나요? , 갤럭시 S24 배터리 교체는 어디서 할 수 있나요?",
        "갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 받을 수 있어요.",
        "가까운 서비스센터에서 바로 가능한가요?",
        "배터리 교체 비용은 얼마나 나와요?",
    ]

    cleaned, noise_removed = _clean_message_history(
        items,
        question="갤럭시 S24 배터리 교체는 어디서 할 수 있나요?",
        actual_answer="갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 받을 수 있어요.",
    )

    assert cleaned == [
        "갤럭시 S24 배터리 교체는 어디서 할 수 있나요?",
        "갤럭시 S24 배터리 교체는 삼성전자서비스 센터에서 받을 수 있어요.",
    ]
    assert noise_removed >= 1


def test_recover_dom_response_candidate_uses_focused_history_when_wait_detection_failed():
    message_history = [
        "휴대폰 액정 수리 접수는 어떻게 하나요?",
        "휴대폰 액정 수리는 삼성전자 서비스센터로 접수하면 돼요. 방문 접수가 가장 일반적이고, 상황에 따라 전화로 방문수리 예약도 가능합니다.",
        "가장 빠른 방법: 서비스센터 방문",
    ]

    recovered = _recover_dom_response_candidate(
        question="휴대폰 액정 수리 접수는 어떻게 하나요?",
        dom_answer="",
        last_answer_payload={"answer_raw": "", "actual_answer_clean": "", "extraction_source": "unknown"},
        message_history=message_history,
    )

    assert recovered["detected"] is True
    assert recovered["source"] == "message_history_recovered"
    assert recovered["actual_answer_clean"].startswith("휴대폰 액정 수리는 삼성전자 서비스센터로 접수하면 돼요.")


def test_recover_dom_response_candidate_ignores_chat_history_dump_dom_payload():
    message_history = [
        "갤럭시 버즈3 프로의 배터리 시간과 방수 등급 그리고 주요 오디오 기능을 알려주세요.",
        "갤럭시 버즈3 프로는 배터리가 케이스 포함 최대 26시간 노캔 켜짐 기준, 방수는 IP57, 오디오는 2-way 스피커와 적응형 노이즈 캔슬링이 핵심이에요.",
    ]

    recovered = _recover_dom_response_candidate(
        question="갤럭시 버즈3 프로의 배터리 시간과 방수 등급 그리고 주요 오디오 기능을 알려주세요.",
        dom_answer=(
            "4월 9일 (목) 첨부 Samsung AI CS Chat 안녕하세요 송제혁님 삼성닷컴에서 어떤 제품들을 구매할 수 있나요? "
            "프롬프트 생성 중 오류가 발생했습니다. 채팅을 다시 시작하세요. "
            "갤럭시 S26 울트라의 디스플레이 크기와 카메라 구성 그리고 배터리 같은 핵심 사양을 알려주세요?"
        ),
        last_answer_payload={"answer_raw": "", "actual_answer_clean": "", "extraction_source": "unknown"},
        message_history=message_history,
    )

    assert recovered["detected"] is True
    assert recovered["source"] == "message_history_recovered"
    assert recovered["actual_answer_clean"].startswith("갤럭시 버즈3 프로는 배터리가 케이스 포함 최대 26시간")


def test_clear_unverified_answer_fields_returns_empty_payload():
    cleared = _clear_unverified_answer_fields()

    assert cleared["answer"] == ""
    assert cleared["answer_raw"] == ""
    assert cleared["actual_answer"] == ""
    assert cleared["actual_answer_clean"] == ""
    assert cleared["extraction_source"] == "unknown"
    assert cleared["extraction_source_detail"] == "no_verified_answer"


def test_loading_placeholder_is_not_treated_as_answer():
    raw = "답변 생성 중\n갤럭시 S26 울트라의 핵심 사양을 찾고 있습니다."

    assert _clean_bot_answer_candidate(raw) == ""
    assert _is_meaningful_answer_text(raw) is False


def test_loading_placeholder_with_long_body_does_not_recurse():
    raw = (
        "답변 생성 중 갤럭시 S26 울트라 핵심 사양을 함께 정리하고 있어요. "
        "갤럭시 S26 울트라 디스플레이는 6.9형이고, 후면은 4카메라 구성, 배터리는 5,000mAh예요. "
        "상세 사양은 아래처럼 보시면 돼요. 디스플레이 6.9형 Dynamic AMOLED 2X "
        "QHD+ 해상도 3120×1440, 최대 120Hz 카메라 구성 후면 4개."
    )

    cleaned = _clean_bot_answer_candidate(raw)

    assert "답변 생성 중" in cleaned
    assert "갤럭시 S26 울트라 디스플레이는 6.9형" in cleaned


def test_clean_bot_answer_candidate_strips_accessibility_prefix_but_keeps_answer_body():
    raw = (
        "자세한 내용을 보려면 Enter를 누르세요. "
        "갤럭시 북5 프로 360은 가벼운 무게와 긴 배터리 사용 시간을 제공합니다."
    )

    assert _clean_bot_answer_candidate(raw) == "갤럭시 북5 프로 360은 가벼운 무게와 긴 배터리 사용 시간을 제공합니다."


def test_clean_bot_answer_candidate_rejects_generic_followup_chip():
    raw = "삼성닷컴에서 어떤 제품들을 구매할 수 있나요?"

    assert _clean_bot_answer_candidate(raw) == ""


def test_clean_bot_answer_candidate_rejects_hidden_korean_timestamp():
    raw = "\u200e오전 10:50"

    assert _is_noise_line(raw) is True
    assert _clean_bot_answer_candidate(raw) == ""