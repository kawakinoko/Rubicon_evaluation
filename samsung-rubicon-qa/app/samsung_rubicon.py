"""Samsung /sec/ Rubicon chatbot UI automation using Playwright."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import Frame, Locator, Page

from app.acceptance import assess_answer_acceptance
from app.config import AppConfig
from app.dom_extractor import (
    _clean_answer_candidate_details as _dom_clean_answer_candidate_details,
    _detect_topic_family as _dom_detect_topic_family,
    _is_stale_or_invalid_candidate as _dom_is_stale_or_invalid_candidate,
    _is_question_repetition as _dom_is_question_repetition,
    _looks_truncated as _dom_looks_truncated,
    build_post_baseline_answer_candidates,
    choose_best_answer_segment,
    compute_new_text_segments,
    count_bot_messages,
    diff_visible_text_against_baseline,
    extract_bot_message_texts,
    extract_dom_payload,
    extract_message_history_candidates,
    extract_structured_message_history,
    extract_visible_chat_text,
    extract_visible_text_blocks,
    filter_out_static_ui_text,
    looks_like_chat_history_dump,
    normalize_text_for_diff,
)
from app.models import BrowserArtifacts, ExtractedPair, ResolvedChatContext, TestCase
from app.ocr_fallback import extract_text_from_image
from app.utils import artifact_timestamp, build_locator, compile_regex, first_visible_locator, sanitize_filename, utc_now_timestamp


LAUNCHER_CANDIDATES = [
    {"type": "role", "role": "button", "name": compile_regex(r"AI|Chat|챗봇|상담|Assistant|Help|Rubicon|루비콘")},
    {"type": "label", "value": compile_regex(r"AI|Chat|챗봇|상담|Assistant|Help|Rubicon|루비콘")},
    {"type": "text", "value": compile_regex(r"AI|Chat|챗봇|상담|Assistant|Help|Rubicon|루비콘")},
    {"type": "css", "value": "#spr-chat__trigger-button, .spr-chat__trigger-box button"},
    {"type": "css", "value": "button[aria-label*='chat' i], button[aria-label*='assistant' i], button[aria-label*='rubicon' i]"},
    {"type": "css", "value": "[data-testid*='chat'], [data-testid*='assistant'], [data-testid*='rubicon']"},
    {"type": "css", "value": "button[class*='chat'], button[class*='assistant'], button[class*='floating']"},
    {"type": "css", "value": "div[style*='position: fixed'] button, a[style*='position: fixed'], div[style*='bottom'] button"},
]

INPUT_CANDIDATES = [
    {"type": "role", "role": "textbox", "name": compile_regex(r"질문|문의|메시지|채팅|입력|message|chat")},
    {"type": "label", "value": compile_regex(r"질문|문의|메시지|채팅|입력|message|chat")},
    {"type": "placeholder", "value": compile_regex(r"질문|문의|메시지|무엇을 도와|message|ask")},
    {"type": "css", "value": "textarea[placeholder*='메시지'], textarea[aria-label*='메시지'], textarea[placeholder*='message' i], textarea[aria-label*='message' i]"},
    {"type": "css", "value": ".ql-editor, .ql-container, .DraftEditor-root [contenteditable='true']"},
    {"type": "css", "value": "[placeholder*='무엇이든지' i], [placeholder*='질문' i], [placeholder*='입력' i], [placeholder*='메시지' i]"},
    {"type": "css", "value": "[aria-label*='무엇이든지' i], [aria-label*='대화 중 메시지' i], [aria-label*='질문' i], [aria-label*='입력' i], [aria-label*='메시지' i]"},
    {"type": "css", "value": "textarea, [role='textbox'], [contenteditable='true'], div[contenteditable]"},
]

INPUT_SCAN_SELECTORS = [
    ".ql-editor",
    ".ql-container",
    ".DraftEditor-root [contenteditable='true']",
    "[placeholder*='무엇이든지' i]",
    "[placeholder*='질문' i]",
    "[placeholder*='입력' i]",
    "[placeholder*='메시지' i]",
    "[aria-label*='무엇이든지' i]",
    "[aria-label*='대화 중 메시지' i]",
    "[aria-label*='질문' i]",
    "[aria-label*='입력' i]",
    "[aria-label*='메시지' i]",
    "textarea",
    "[role='textbox']",
    "[contenteditable='true']",
    "[contenteditable='plaintext-only']",
    "div[contenteditable]",
    "textarea[placeholder]",
    "textarea[aria-label]",
    "[contenteditable][aria-label]",
]

_SPR_CHAT_TRIGGER_CANDIDATES = [
    "#spr-chat__trigger-button",
    "[aria-label*='chat' i]",
    "[class*='chat' i]",
    "button:has-text('채팅')",
    "button:has-text('상담')",
]

CHAT_MENU_BUTTON_HINTS = [
    "전체 메뉴",
    "더보기",
]

CHAT_END_CONVERSATION_HINTS = [
    "대화 그만하기",
    "대화 종료",
    "채팅 종료",
]

CHAT_CONFIRM_BUTTON_HINTS = [
    "확인",
    "예",
]

_ACTIVATION_CANDIDATES = [
    "button:has-text('Start chat')",
    "button:has-text('Chat now')",
    "button:has-text('Ask a question')",
    "button:has-text('문의')",
    "button:has-text('상담')",
    "button:has-text('시작')",
    "button:has-text('메시지')",
    "[role='button']:has-text('문의')",
    "[role='button']:has-text('상담')",
]

SEND_BUTTON_CANDIDATES = [
    {"type": "role", "role": "button", "name": compile_regex(r"Send|전송|제출|문의|보내기")},
    {"type": "label", "value": compile_regex(r"Send|전송|제출|문의|보내기")},
    {"type": "css", "value": "button[aria-label*='send' i], button[aria-label*='전송'], button[aria-label*='보내기']"},
    {"type": "css", "value": "button[aria-label*='send' i], button[aria-label*='전송'], button[type='submit']"},
    {"type": "css", "value": "button[class*='send'], button[class*='submit'], button svg"},
]

BOT_MESSAGE_CANDIDATES = [
    {"type": "css", "value": ".bot-message, .agent-message, [data-message-author='bot'], [data-author='assistant'], [data-author='bot']"},
    {"type": "css", "value": "[class*='agent' i], [class*='assistant' i], [class*='message' i], [data-testid*='message' i]"},
    {"type": "css", "value": "[role='log'] article, [role='log'] li, [role='list'] article, [role='list'] li"},
    {"type": "css", "value": "article[class*='assistant'], div[class*='assistant'], div[class*='response'], div[class*='message']"},
    {"type": "text", "value": compile_regex(r"서비스센터|삼성닷컴|도와드리|안내드리")},
]

USER_MESSAGE_CANDIDATES = [
    {"type": "css", "value": ".user-message, [data-message-author='user'], [data-author='user'], [data-author='customer']"},
    {"type": "css", "value": "[class*='user' i][class*='message' i], [class*='customer' i][class*='message' i]"},
    {"type": "css", "value": "[class*='outgoing' i], [class*='sent' i], [class*='right' i][class*='message' i]"},
    {"type": "css", "value": "[role='log'] [data-message-author='user'], [role='list'] [data-message-author='user']"},
]

HISTORY_CANDIDATES = [
    {"type": "css", "value": "[role='log'] *"},
    {"type": "css", "value": "[role='list'] *"},
    {"type": "css", "value": "article, li, [data-message-author], [data-author]"},
]

CONTAINER_CANDIDATES = [
    {"type": "css", "value": "[role='dialog'], [role='complementary'], aside, section[class*='chat'], div[class*='chat'], div[class*='assistant']"},
    {"type": "css", "value": "[class*='spr' i], [id*='spr' i], [title*='Sprinklr' i], iframe[title*='live chat' i], iframe[title*='라이브챗']"},
    {"type": "css", "value": "iframe, form, [data-testid*='chat'], [data-testid*='assistant']"},
]

LOADING_CANDIDATES = [
    {"type": "css", "value": ".typing, .loading, .spinner, [aria-busy='true'], [class*='typing'], [class*='loading']"},
    {"type": "text", "value": compile_regex(r"입력 중|작성 중|답변 생성 중|찾아보고 있어요|불러오는 중|typing|loading")},
]

LOADING_TEXT_HINTS = [
    "입력 중",
    "작성 중",
    "답변 생성 중",
    "찾고 있습니다",
    "찾아보고 있어요",
    "불러오는 중",
    "loading",
    "typing",
]

POPUP_CLOSE_CANDIDATES = [
    {"type": "role", "role": "button", "name": compile_regex(r"닫기|Close|취소|오늘 그만 보기")},
    {"type": "text", "value": compile_regex(r"닫기|Close|오늘 그만 보기")},
    {"type": "css", "value": "button[aria-label*='close' i], button[aria-label*='닫기'], .close, .btn-close"},
]

POPUP_ACCEPT_CANDIDATES = [
    {"type": "role", "role": "button", "name": compile_regex(r"동의|확인|Accept|허용")},
    {"type": "text", "value": compile_regex(r"동의|확인|Accept|허용")},
]

KOREAN_FONT_CSS = (
    '* { font-family: "Noto Sans KR", "Noto Sans CJK KR", "Nanum Gothic",'
    ' "Apple SD Gothic Neo", sans-serif !important; }'
)

# Delay (ms / s) after submit to let the UI render the user-message bubble
ECHO_RENDER_DELAY_MS = 600
ECHO_RENDER_DELAY_SEC = ECHO_RENDER_DELAY_MS / 1000.0

BASELINE_MENU_TEXTS = [
    "아래에서 원하는 항목을 선택해 주세요",
    "구매 상담사 연결",
    "주문·배송 조회",
    "모바일 케어플러스",
    "가전 케어플러스",
    "서비스 센터",
    "FAQ",
]
LOGIN_REQUIRED_HINTS = [
    "로그인 / 회원가입",
    "로그인하세요",
    "회원가입",
    "Samsung AI Assistant에 로그인",
]

CAPTURE_INVALID_REASON = "Capture invalid: no verified submitted question and bot answer pair"
CAPTURE_INVALID_FIX = "Check before_send/after_send screenshots, frame selection, and message diff logs"
EXTRACTOR_VERSION = "dom-extractor-v2.4"
MIN_INPUT_WIDTH = 24
MIN_INPUT_HEIGHT = 18
UNAVAILABLE_AVAILABILITY_VALUES = {"unavailable", "offline", "hidden", "closed"}
CHAT_READY_HINTS = [
    "무엇이든 물어보세요",
    "무엇이든 물어 보세요",
    "메시지를 입력",
    "질문을 입력",
]
CHAT_READY_SIGNAL_HINTS = [
    "대화 중 메시지",
]
CHAT_DISABLED_HINTS = [
    "대화창에 더이상 입력할 수 없습니다",
    "더이상 입력할 수 없습니다",
]
FAST_TRANSITION_FRAME_HINTS = [
    "spr-chat__box-frame",
    "spr-live-chat-frame",
]
CHAT_READY_TIMEOUT_SEC = 20.0
CHAT_READY_POLL_MS = 400
COMPOSER_TRANSITION_STABLE_ROUNDS = 2
ACTIVATION_MAX_ROUNDS = 2
ACTIVATION_POLL_MS = 600
POPUP_SCAN_TIMEOUT_SEC = 6.0
POPUP_LOCATOR_TIMEOUT_MS = 250
CHAT_READY_SCAN_SELECTORS = [
    "textarea",
    "textarea[placeholder]",
    "textarea[aria-label]",
    "[role='textbox']",
    "[contenteditable='true']",
    "[contenteditable='plaintext-only']",
]
CHAT_INPUT_ROOT_SELECTORS = [
    "footer",
    "form",
    "[class*='footer' i]",
    "[class*='composer' i]",
    "[class*='input' i]",
    "[class*='textarea' i]",
]

ANSWER_CUTOFF_HINTS = [
    "🔍 이어서 물어보세요",
    "이어서 물어보세요",
]

ANSWER_META_NOISE_HINTS = [
    "자세한 내용을 보려면 Enter를 누르세요",
    "리치 텍스트 메시지",
    "AI 생성 메시지는 부정확할 수 있습니다",
    "첨부",
    "수신됨",
    "전송됨",
    "더보기",
]

ANSWER_SUGGESTION_LINE_HINTS = [
    "가까운 서비스센터에서 바로 가능한가요?",
    "배터리 교체 비용은 얼마나 나와요?",
    "삼성케어플러스 가입이면 혜택이 있나요?",
    "삼성닷컴에서 어떤 제품들을 구매할 수 있나요?",
]

HISTORY_ALWAYS_DROP_HINTS = [
    "고객지원이 필요하신가요? Samsung AI CS Chat 을 클릭해주세요.",
    "환영합니다",
    "오늘은 무엇을 도와드릴까요",
    "갤럭시 워치8 관련 기획전 알려주세요.",
    "갤럭시 S26 스펙이 궁금해요.",
    "최신 노트북에 대해 알고싶어요.",
    "삼성닷컴에서 어떤 제품들을 구매할 수 있나요?",
]

MIN_MAIN_ANSWER_LEN = 40
MIN_KEYWORD_COVERAGE_SCORE = 0.30
MEANINGFUL_ANSWER_HINTS = [
    "죄송",
    "문의",
    "구매",
    "서비스센터",
    "도와드리",
    "안내드리",
    "가능합니다",
    "가능해요",
]

_KOREAN_DATE_RE = re.compile(r"\b20\d{2}년\s*\d{1,2}월\s*\d{1,2}일\b")
_KOREAN_TIME_RE = re.compile(r"(?:오전|오후)\s*\d{1,2}:\d{2}")
_EN_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)\b", re.IGNORECASE)
_ANSWER_META_PREFIX_PATTERNS = [
    re.compile(r"^자세한 내용을 보려면 Enter를 누르세요[.\s,:-]*", re.IGNORECASE),
    re.compile(r"^리치 텍스트 메시지[.\s,:-]*", re.IGNORECASE),
    re.compile(r"^첨부[.\s,:-]*", re.IGNORECASE),
    re.compile(r"^더보기[.\s,:-]*", re.IGNORECASE),
]


@dataclass(slots=True)
class SubmissionEvidence:
    input_dom_verified: bool
    submit_effect_verified: bool
    input_verified: bool
    input_method_used: str
    submit_method_used: str
    input_scope: str
    input_selector: str
    input_candidate_score: float
    top_candidate_disabled: bool
    top_candidate_placeholder: str
    top_candidate_aria: str
    input_ready_wait_attempted: bool
    input_ready_wait_result: str
    transition_wait_attempted: bool
    transition_ready: bool
    transition_timeout: bool
    transition_reason: str
    transition_history: str
    failover_attempts: int
    final_input_value_verified: bool
    user_message_echo_verified: bool
    input_failure_category: str
    input_failure_reason: str
    editable_candidates_count: int
    final_input_target_frame: str
    input_candidates_debug: str
    before_send_chatbox_path: str
    before_send_fullpage_path: str
    after_send_chatbox_path: str
    after_send_fullpage_path: str
    capture_reason: str


@dataclass(slots=True)
class AnswerWaitResult:
    answer: str
    response_ms: int
    new_bot_response_detected: bool
    baseline_menu_detected: bool
    reason: str
    question_repetition_detected: bool = False
    truncated_answer_detected: bool = False
    needs_retry_extraction: bool = False


@dataclass(slots=True)
class _InputCandidate:
    scope: Page | Frame
    scope_name: str
    locator: Locator
    selector: str
    index: int
    score: int
    metadata: dict[str, Any]


@dataclass(slots=True)
class _RuntimeState:
    config: AppConfig
    logger: Any
    current_case_id: str = ""
    current_case_timestamp: str = ""
    latest_html_fragment_path: str = ""
    current_screenshot_count: int = 0


_RUNTIME: _RuntimeState | None = None


def configure_runtime(config: AppConfig, logger: Any) -> None:
    """Bind config and logger for the required module-level functions."""

    global _RUNTIME
    _RUNTIME = _RuntimeState(config=config, logger=logger)


def _runtime() -> _RuntimeState:
    if _RUNTIME is None:
        raise RuntimeError("samsung_rubicon.configure_runtime() must be called before use")
    return _RUNTIME


def _reset_case_artifact_state() -> None:
    runtime = _runtime()
    runtime.current_screenshot_count = 0
    runtime.latest_html_fragment_path = ""


def _has_failure_capture_budget(config: AppConfig) -> bool:
    if config.capture_mode == "debug":
        return True
    return _runtime().current_screenshot_count < config.max_screenshots_per_case


def _register_screenshot_capture() -> None:
    runtime = _runtime()
    if runtime.config.capture_mode != "debug":
        runtime.current_screenshot_count += 1


def _success_stage_enabled(stage: str, config: AppConfig) -> bool:
    if config.capture_mode != "debug" or not config.enable_screenshots:
        return False
    if stage == "before_send":
        return config.save_before_send_on_success or config.rubicon_before_send_screenshot
    if stage == "after_answer":
        return config.save_after_answer_on_success or config.rubicon_after_answer_screenshot
    if stage == "opened_footer":
        return config.rubicon_opened_footer_screenshot or config.enable_chatbox_screenshots
    return True


def _should_capture_stage(stage: str, *, case_failed: bool, config: AppConfig) -> bool:
    if case_failed:
        if config.capture_mode not in {"fail_only", "debug"}:
            return False
        if config.max_screenshots_per_case <= 0:
            return False
        return _has_failure_capture_budget(config)
    return _success_stage_enabled(stage, config)


def _should_capture_fullpage(*, case_failed: bool, config: AppConfig) -> bool:
    if case_failed:
        return config.capture_mode == "debug" and config.enable_fullpage_screenshots and _has_failure_capture_budget(config)
    return config.capture_mode == "debug" and config.enable_fullpage_screenshots and config.enable_screenshots


def _should_capture_chatbox(stage: str, *, case_failed: bool, config: AppConfig) -> bool:
    if case_failed:
        return _should_capture_stage(stage, case_failed=True, config=config)
    if not _should_capture_stage(stage, case_failed=False, config=config):
        return False
    if stage == "opened_footer":
        return config.rubicon_opened_footer_screenshot or config.enable_chatbox_screenshots
    if stage == "before_send":
        return config.save_before_send_on_success or config.rubicon_before_send_screenshot
    if stage == "after_answer":
        return config.save_after_answer_on_success or config.rubicon_after_answer_screenshot or config.enable_chatbox_screenshots
    return config.enable_chatbox_screenshots


def _is_meaningful_answer_text(text: str) -> bool:
    normalized = _clean_bot_answer_candidate(text)
    if not normalized:
        return False
    if _is_loading_answer_text(normalized):
        return False
    if _looks_like_main_answer(normalized):
        return True
    if len(normalized) >= 16:
        return True
    return any(hint in normalized for hint in MEANINGFUL_ANSWER_HINTS)


def _should_run_ocr_fallback(dom_answer: str, new_bot_response_detected: bool, config: AppConfig) -> bool:
    if config.enable_ocr_always:
        return True
    if not config.enable_ocr_on_failure:
        return False
    if not new_bot_response_detected:
        return True
    normalized = _clean_bot_answer_candidate(dom_answer)
    return not _is_meaningful_answer_text(normalized)


def _context_resolve_rounds(config: AppConfig) -> int:
    if config.is_speed_mode:
        return max(1, config.fast_context_resolve_rounds)
    return 6


def _context_resolve_wait_ms(config: AppConfig) -> int:
    if config.is_speed_mode:
        return max(100, config.fast_context_resolve_wait_ms)
    return 5000


def _answer_wait_settings(config: AppConfig) -> tuple[float, int, float]:
    if config.is_speed_mode:
        return (
            config.fast_answer_timeout_ms / 1000.0,
            max(1, config.fast_answer_stable_checks),
            max(0.1, config.fast_answer_stable_interval_sec),
        )
    return (
        config.playwright_timeout_ms / 1000.0,
        max(1, config.answer_stable_checks),
        max(0.1, config.answer_stable_interval_sec),
    )


def _should_store_success_message_history(config: AppConfig) -> bool:
    return (not config.is_speed_mode) or config.is_debug_mode or config.enable_message_history_on_success


def _should_dump_dom_payload(*, case_failed: bool, config: AppConfig) -> bool:
    if case_failed:
        return True
    return config.is_debug_mode or config.enable_dom_dump_on_success


def _dump_chat_html_fragment(context: ResolvedChatContext | None, case_id: str, timestamp: str) -> str:
    if context is None:
        return ""

    runtime = _runtime()
    safe_case_id = sanitize_filename(case_id)
    html_fragment_path = runtime.config.chatbox_dir / f"{timestamp}_{safe_case_id}.html"

    html_payload = ""
    try:
        if context.container_locator is not None:
            html_payload = context.container_locator.evaluate("el => el.outerHTML || ''") or ""
    except Exception:
        html_payload = ""

    if not html_payload:
        try:
            html_payload = context.scope.evaluate(
                "() => { const el = document.body || document.documentElement; return el ? (el.outerHTML || '') : ''; }"
            ) or ""
        except Exception:
            html_payload = ""

    if not html_payload:
        return ""

    html_fragment_path.write_text(html_payload, encoding="utf-8")
    runtime.latest_html_fragment_path = str(html_fragment_path)
    runtime.logger.info("[ARTIFACT][SAVE] stage=html_fragment path=%s", html_fragment_path)
    return str(html_fragment_path)


def _iter_scopes(page: Page) -> list[tuple[str, Page | Frame]]:
    scopes: list[tuple[str, Page | Frame]] = [("page", page)]
    for index, frame in enumerate(page.frames):
        frame_name = frame.name or frame.url or f"frame-{index}"
        scopes.append((frame_name, frame))
    return scopes


def _iter_popup_scopes(page: Page) -> list[tuple[str, Page | Frame]]:
    prioritized: list[tuple[str, Page | Frame]] = [("page", page)]
    secondary: list[tuple[str, Page | Frame]] = []
    for index, frame in enumerate(page.frames):
        frame_name = frame.name or ""
        frame_url = frame.url or ""
        frame_label = frame_name or frame_url or f"frame-{index}"
        frame_hint = f"{frame_name} {frame_url}".lower()
        if any(keyword in frame_hint for keyword in ("spr", "chat", "popup", "consent", "notice", "layer", "dialog")):
            prioritized.append((frame_label, frame))
        else:
            secondary.append((frame_label, frame))
    return prioritized + secondary[:2]


def _first_quick_visible_locator(
    scope: Page | Frame,
    candidates: list[dict[str, Any]],
    timeout_ms: int = POPUP_LOCATOR_TIMEOUT_MS,
) -> tuple[Locator | None, dict[str, Any] | None]:
    for candidate in candidates:
        locator = build_locator(scope, candidate).first
        try:
            if locator.is_visible(timeout=timeout_ms):
                return locator, candidate
        except Exception:
            continue
    return None, None


def _bool_attr(value: Any) -> bool:
    return str(value or "").strip().lower() == "true"


def _norm_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(str(value).strip().split())


def _candidate_size_ok(candidate_state: dict[str, Any]) -> bool:
    return int(candidate_state.get("bbox_width", 0) or 0) >= MIN_INPUT_WIDTH and int(candidate_state.get("bbox_height", 0) or 0) >= MIN_INPUT_HEIGHT


def _candidate_reason(candidate_state: dict[str, Any]) -> str:
    if not candidate_state.get("visible"):
        return "not_visible"
    if candidate_state.get("disabled") or not candidate_state.get("enabled"):
        return "disabled"
    if candidate_state.get("readonly") or candidate_state.get("aria_readonly"):
        return "readonly"
    if candidate_state.get("aria_disabled"):
        return "aria_disabled"
    if not _candidate_size_ok(candidate_state):
        return "zero_size"

    placeholder = str(candidate_state.get("placeholder", "")).lower()
    aria_label = str(candidate_state.get("aria_label", "")).lower()
    if "더이상 입력할 수 없습니다" in placeholder or "더이상 입력할 수 없습니다" in aria_label:
        return "placeholder_shell"
    if _candidate_has_ready_hint(candidate_state):
        return "allowed"
    if not candidate_state.get("editable"):
        return "not_editable"
    return "allowed"


def _grade_candidate_state(candidate_state: dict[str, Any]) -> tuple[str, str]:
    reason = _candidate_reason(candidate_state)
    if reason != "allowed":
        return "C", reason

    if (
        candidate_state.get("visible")
        and candidate_state.get("enabled")
        and candidate_state.get("editable")
        and _candidate_has_ready_hint(candidate_state)
    ):
        return "B", "ready_signal"

    contenteditable = str(candidate_state.get("contenteditable", "")).lower()
    tag_name = str(candidate_state.get("tag_name", "")).lower()
    role = str(candidate_state.get("role", "")).lower()
    if candidate_state.get("visible") and candidate_state.get("enabled") and candidate_state.get("editable"):
        if tag_name in {"textarea", "input"} and contenteditable not in {"false", "inherit"}:
            return "A", "editable_dom"
        if tag_name in {"textarea", "input"}:
            return "A", "editable_dom"
        if role == "textbox" or contenteditable in {"true", "plaintext-only"}:
            return "B", "textbox_like"
    return "C", "not_final_target"


def _score_ranked_candidate(candidate_state: dict[str, Any], grade: str, preferred_scope: str, scope_name: str) -> float:
    score = 95.0 if grade == "A" else 78.0 if grade == "B" else 15.0
    if scope_name == preferred_scope:
        score += 4.0
    if candidate_state.get("placeholder"):
        score += 1.0
    if candidate_state.get("tag_name") == "textarea":
        score += 2.0
    if candidate_state.get("contenteditable") in {"true", "plaintext-only"}:
        score += 2.0
    if candidate_state.get("role") == "textbox":
        score += 1.0
    score += min(int(candidate_state.get("bbox_width", 0) or 0) / 100.0, 4.0)
    return score


def _candidate_debug_line(candidate: dict[str, Any]) -> str:
    score = float(candidate.get("score", 0.0) or 0.0)
    return (
        f"score={score:.1f} selector={candidate.get('selector', '?')} scope={candidate.get('scope_name', '?')} "
        f"visible={candidate.get('visible', '?')} editable={candidate.get('editable', '?')} disabled={candidate.get('disabled', '?')} "
        f"grade={candidate.get('grade', '?')} reason={candidate.get('reason', '?')}"
    )


def _candidate_is_disabled_like(candidate: dict[str, Any] | None) -> bool:
    if not candidate:
        return False
    if candidate.get("grade") in {"A", "B"}:
        return False
    if candidate.get("disabled") or candidate.get("readonly") or candidate.get("aria_disabled") or candidate.get("aria_readonly"):
        return True
    return str(candidate.get("reason", "")) in {
        "disabled",
        "readonly",
        "aria_disabled",
        "placeholder_shell",
        "not_editable",
    }


def _is_disabled_transition_candidate(candidate: dict[str, Any]) -> bool:
    placeholder = _norm_text(candidate.get("placeholder"))
    aria = _norm_text(candidate.get("aria_label") or candidate.get("aria"))
    combined = f"{placeholder} {aria}".strip()

    if not candidate.get("visible", False):
        return False
    if not candidate.get("disabled", False):
        return False
    if candidate.get("tag_name") not in ("textarea", "input", "div"):
        return False
    return any(hint in combined for hint in CHAT_DISABLED_HINTS)


def _is_ready_candidate(candidate: dict[str, Any]) -> bool:
    placeholder = _norm_text(candidate.get("placeholder"))
    aria = _norm_text(candidate.get("aria_label") or candidate.get("aria"))
    combined = f"{placeholder} {aria}".strip()

    if not candidate.get("visible", False):
        return False
    if candidate.get("disabled", False):
        return False
    if candidate.get("editable", False):
        return True
    return any(hint in combined for hint in CHAT_READY_HINTS)


def _candidate_has_ready_hint(candidate: dict[str, Any]) -> bool:
    placeholder = _norm_text(candidate.get("placeholder"))
    aria = _norm_text(candidate.get("aria_label") or candidate.get("aria"))
    combined = f"{placeholder} {aria}".strip()
    return any(hint in combined for hint in [*CHAT_READY_HINTS, *CHAT_READY_SIGNAL_HINTS])


def _is_transition_disabled_candidate(candidate: dict[str, Any]) -> bool:
    return _is_disabled_transition_candidate(candidate)


def _is_ready_composer_candidate(candidate: dict[str, Any]) -> bool:
    return _is_ready_candidate(candidate)


def _top_candidate_texts(ranked_candidates: list[dict[str, Any]]) -> tuple[str, str]:
    top = ranked_candidates[0] if ranked_candidates else None
    if not top:
        return "", ""
    return _norm_text(top.get("placeholder")), _norm_text(top.get("aria_label") or top.get("aria"))


def _candidate_bottom_weight(candidate: dict[str, Any]) -> int:
    rect_top = int(candidate.get("rectTop", candidate.get("bbox_top", 0)) or 0)
    viewport_height = int(candidate.get("viewportHeight", 0) or 0)
    if viewport_height and rect_top > int(viewport_height * 0.45):
        return 6
    return 0


def _locator_count(scope: Page | Frame, selector: str) -> int:
    try:
        return scope.locator(selector).count()
    except Exception:
        return 0


def _inspect_candidate(locator: Locator) -> dict[str, Any]:
    visible = False
    enabled = False
    editable = False
    try:
        visible = locator.is_visible(timeout=400)
    except Exception:
        visible = False
    try:
        enabled = locator.is_enabled(timeout=400)
    except Exception:
        enabled = False
    try:
        editable = locator.is_editable(timeout=400)
    except Exception:
        editable = False

    payload = {
        "visible": visible,
        "enabled": enabled,
        "editable": editable,
        "readonly": False,
        "aria_disabled": False,
        "aria_readonly": False,
        "disabled": not enabled,
        "role": "",
        "tag_name": "",
        "input_type": "",
        "contenteditable": "",
        "placeholder": "",
        "aria_label": "",
        "bbox_width": 0,
        "bbox_height": 0,
    }
    try:
        payload.update(
            locator.evaluate(
                """
                (el) => {
                  const rect = el.getBoundingClientRect();
                  return {
                    readonly: !!el.readOnly,
                    aria_disabled: (el.getAttribute('aria-disabled') || '').toLowerCase() === 'true',
                    aria_readonly: (el.getAttribute('aria-readonly') || '').toLowerCase() === 'true',
                    disabled: !!el.disabled,
                    role: (el.getAttribute('role') || '').toLowerCase(),
                    tag_name: (el.tagName || '').toLowerCase(),
                    input_type: (el.getAttribute('type') || '').toLowerCase(),
                    contenteditable: (el.getAttribute('contenteditable') || el.contentEditable || '').toLowerCase(),
                    placeholder: (el.getAttribute('placeholder') || '').trim(),
                    aria_label: (el.getAttribute('aria-label') || '').trim(),
                    bbox_width: Math.round(rect.width || 0),
                    bbox_height: Math.round(rect.height || 0),
                  };
                }
                """
            )
        )
    except Exception:
        pass
    payload["editable"] = bool(payload["editable"]) and not bool(payload["disabled"]) and not bool(payload["readonly"]) and not bool(payload["aria_disabled"]) and not bool(payload["aria_readonly"])
    payload["aria"] = payload.get("aria_label", "")
    return payload


def _assign_candidate_to_context(ctx: ResolvedChatContext, candidate: dict[str, Any]) -> None:
    candidate_scope = candidate.get("scope", ctx.scope)
    candidate_scope_name = candidate.get("scope_name", ctx.scope_name)
    ctx.scope = candidate_scope
    ctx.scope_name = candidate_scope_name
    ctx.input_locator = candidate.get("locator")
    ctx.input_scope = candidate_scope
    ctx.input_scope_name = candidate_scope_name
    ctx.input_selector = candidate.get("selector", "")
    ctx.input_candidate_score = float(candidate.get("score", 0.0) or 0.0)
    ctx.input_failure_category = candidate.get("failure_category", "")
    ctx.input_failure_reason = candidate.get("failure_reason", "")
    send_locator, _ = first_visible_locator(candidate_scope, SEND_BUTTON_CANDIDATES, timeout_ms=700)
    if send_locator is None and ctx.page is not None:
        send_locator, _ = first_visible_locator(ctx.page, SEND_BUTTON_CANDIDATES, timeout_ms=700)
    ctx.send_locator = send_locator
    container_locator, _ = first_visible_locator(candidate_scope, CONTAINER_CANDIDATES, timeout_ms=700)
    if container_locator is not None:
        ctx.container_locator = container_locator


def _iter_fast_transition_contexts(page: Page, resolved_ctx: ResolvedChatContext | None) -> list[tuple[str, Any]]:
    contexts: list[tuple[str, Any]] = []
    if resolved_ctx is not None:
        contexts.append(("resolved_ctx", resolved_ctx.scope))

    for index, frame in enumerate(page.frames):
        frame_url = ""
        frame_name = ""
        try:
            frame_url = frame.url or ""
        except Exception:
            pass
        try:
            frame_name = frame.name or ""
        except Exception:
            pass
        frame_sig = f"{frame_name} {frame_url}"
        if any(hint in frame_sig for hint in FAST_TRANSITION_FRAME_HINTS):
            contexts.append((f"fast_frame[{index}]", frame))

    deduped: list[tuple[str, Any]] = []
    seen: set[int] = set()
    for label, current_ctx in contexts:
        key = id(current_ctx)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((label, current_ctx))
    return deduped


def _collect_lightweight_candidates(ctx: Any, scope_label: str) -> list[dict[str, Any]]:
    selectors = [
        ".ql-editor",
        ".ql-container",
        "[placeholder*='무엇이든지' i]",
        "[placeholder*='입력' i]",
        "[aria-label*='무엇이든지' i]",
        "[aria-label*='대화 중 메시지' i]",
        "[aria-label*='입력' i]",
        "[aria-label*='메시지' i]",
        "textarea",
        "textarea[placeholder]",
        "textarea[aria-label]",
        "[contenteditable='true']",
        "[contenteditable='plaintext-only']",
        "[role='textbox']",
    ]
    scope = ctx.scope if isinstance(ctx, ResolvedChatContext) else ctx
    items: list[dict[str, Any]] = []
    for selector in selectors:
        try:
            locs = scope.locator(selector)
            count = min(locs.count(), 3)
        except Exception:
            continue
        for index in range(count):
            try:
                loc = locs.nth(index)
                state = _inspect_candidate(loc)
                grade, reason = _grade_candidate_state(state)
                items.append(
                    {
                        **state,
                        "aria": state.get("aria_label", ""),
                        "selector": selector,
                        "scope_name": scope_label,
                        "scope": scope,
                        "locator": loc,
                        "index": index,
                        "grade": grade,
                        "reason": reason,
                        "score": _score_ranked_candidate(state, grade, scope_label, scope_label),
                    }
                )
                if _candidate_has_ready_hint(items[-1]) and not items[-1].get("editable", False):
                    items.extend(_collect_related_ready_candidates(loc, scope, scope_label))
            except Exception:
                continue
    return items


def _collect_related_ready_candidates(locator: Locator, scope: Any, scope_label: str) -> list[dict[str, Any]]:
    related_selectors = [
        ".ql-editor",
        ".DraftEditor-root [contenteditable='true']",
        "textarea",
        "textarea[placeholder]",
        "textarea[aria-label]",
        "input[type='text']",
        "input[type='search']",
        "[contenteditable='true']",
        "[contenteditable='plaintext-only']",
        "[role='textbox']",
    ]
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    containers = [locator]
    try:
        containers.append(locator.locator("xpath=ancestor-or-self::*[1]"))
    except Exception:
        pass
    try:
        containers.append(locator.locator("xpath=ancestor::*[self::div or self::form or self::section][1]"))
    except Exception:
        pass
    for container in containers:
        for selector in related_selectors:
            try:
                related = container.locator(selector)
                count = min(related.count(), 3)
            except Exception:
                continue
            for index in range(count):
                key = (selector, index)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    current = related.nth(index)
                    state = _inspect_candidate(current)
                    grade, reason = _grade_candidate_state(state)
                    items.append(
                        {
                            **state,
                            "aria": state.get("aria_label", ""),
                            "selector": selector,
                            "scope_name": scope_label,
                            "scope": scope,
                            "locator": current,
                            "index": index,
                            "grade": grade,
                            "reason": reason,
                            "score": _score_ranked_candidate(state, grade, scope_label, scope_label),
                        }
                    )
                except Exception:
                    continue
    return items


def _resolve_focus_proxy_candidate(scope: Page | Frame, anchor_locator: Locator, logger: Any) -> tuple[Locator | None, str]:
    selectors = [
        ".ql-editor:focus",
        "textarea:focus",
        "input:focus",
        "[role='textbox']:focus",
        "[contenteditable='true']:focus",
        "[contenteditable='plaintext-only']:focus",
        ".ql-editor:focus-within",
        "[role='textbox']:focus-within",
        "[contenteditable='true']:focus-within",
        "[contenteditable='plaintext-only']:focus-within",
        ".ql-editor",
        "[contenteditable='true']",
        "[contenteditable='plaintext-only']",
        "textarea",
        "input[type='text']",
        "input[type='search']",
        "[role='textbox']",
    ]

    try:
        active_snapshot = scope.evaluate(
            """
            () => {
              const el = document.activeElement;
              if (!el) return null;
              const rect = el.getBoundingClientRect();
              return {
                tag: (el.tagName || '').toLowerCase(),
                role: (el.getAttribute('role') || '').toLowerCase(),
                placeholder: (el.getAttribute('placeholder') || '').trim(),
                aria: (el.getAttribute('aria-label') || '').trim(),
                contenteditable: (el.getAttribute('contenteditable') || el.contentEditable || '').toLowerCase(),
                disabled: !!el.disabled || (el.getAttribute('aria-disabled') || '').toLowerCase() === 'true',
                readonly: !!el.readOnly || (el.getAttribute('aria-readonly') || '').toLowerCase() === 'true',
                rect: [Math.round(rect.left || 0), Math.round(rect.top || 0), Math.round(rect.width || 0), Math.round(rect.height || 0)],
              };
            }
            """
        )
        logger.info("[INPUT][FOCUS_PROXY] active=%s", active_snapshot)
    except Exception as exc:
        logger.debug("[INPUT][FOCUS_PROXY] active snapshot failed: %s", exc)

    related_candidates = _collect_related_ready_candidates(anchor_locator, scope, "focus_proxy")
    for candidate in related_candidates:
        logger.info("[INPUT][FOCUS_PROXY] related selector=%s visible=%s editable=%s disabled=%s grade=%s reason=%s",
                    candidate.get("selector"), candidate.get("visible"), candidate.get("editable"), candidate.get("disabled"), candidate.get("grade"), candidate.get("reason"))
        if candidate.get("grade") in {"A", "B"} and not candidate.get("disabled", False):
            return candidate.get("locator"), str(candidate.get("selector") or "related")

    for selector in selectors:
        try:
            locators = scope.locator(selector)
            count = min(locators.count(), 3)
        except Exception:
            continue
        for index in range(count):
            try:
                current = locators.nth(index)
                state = _inspect_candidate(current)
                grade, reason = _grade_candidate_state(state)
                logger.info(
                    "[INPUT][FOCUS_PROXY] selector=%s index=%s visible=%s editable=%s disabled=%s grade=%s reason=%s placeholder=%r aria=%r",
                    selector,
                    index,
                    state.get("visible"),
                    state.get("editable"),
                    state.get("disabled"),
                    grade,
                    reason,
                    _norm_text(state.get("placeholder")),
                    _norm_text(state.get("aria_label") or state.get("aria")),
                )
                if grade in {"A", "B"} and not state.get("disabled", False):
                    return current, selector
            except Exception:
                continue
    return None, ""


def wait_for_composer_transition(
    page: Page,
    resolved_ctx: ResolvedChatContext | None,
    case_id: str,
    config: AppConfig,
) -> dict[str, Any]:
    if resolved_ctx is None:
        return {
            "transition_ready": False,
            "transition_timeout": True,
            "transition_reason": "composer_transition_timeout",
            "transition_history": [],
            "ready_scope": "",
            "ready_candidate": None,
            "ready_ctx": None,
        }

    result = wait_until_chat_input_ready(page, resolved_ctx, case_id, config)
    return {
        "transition_ready": bool(result.get("ready", False)),
        "transition_timeout": bool(result.get("timeout", False)),
        "transition_reason": "composer_became_ready" if result.get("ready") else "composer_transition_timeout",
        "transition_history": result.get("history", []),
        "ready_scope": str(result.get("scope_name", "") or resolved_ctx.scope_name),
        "ready_candidate": result.get("candidate"),
        "ready_ctx": resolved_ctx,
    }


def _input_candidate_snapshot(locator: Locator) -> dict[str, Any]:
    try:
        return locator.evaluate(
            r"""
            (el) => {
              const normalize = (value) => (value || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
              const tag = (el.tagName || '').toLowerCase();
              const type = (el.getAttribute('type') || '').toLowerCase();
              const role = (el.getAttribute('role') || '').toLowerCase();
              const ariaLabel = normalize(el.getAttribute('aria-label') || '');
              const placeholder = normalize(el.getAttribute('placeholder') || '');
              const contentEditable = (el.getAttribute('contenteditable') || el.contentEditable || '').toLowerCase();
              const disabled = !!el.disabled || el.getAttribute('aria-disabled') === 'true';
              const readOnly = !!el.readOnly || el.getAttribute('aria-readonly') === 'true';
              const style = window.getComputedStyle(el);
              const rect = el.getBoundingClientRect();
              const visible = !!style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              const centerX = Math.min(Math.max(rect.left + (rect.width / 2), 0), window.innerWidth - 1);
              const centerY = Math.min(Math.max(rect.top + (rect.height / 2), 0), window.innerHeight - 1);
              const topEl = visible ? document.elementFromPoint(centerX, centerY) : null;
              const obscured = !!topEl && topEl !== el && !el.contains(topEl) && !topEl.contains(el);
              const editable = !disabled && !readOnly && (
                tag === 'textarea' ||
                tag === 'input' ||
                role === 'textbox' ||
                (contentEditable && contentEditable !== 'false' && contentEditable !== 'inherit')
              );
              const footerLike = !!el.closest('footer, form, [class*="footer" i], [class*="input" i], [class*="composer" i], [class*="textarea" i]');
              return {
                tag,
                type,
                role,
                ariaLabel,
                placeholder,
                contentEditable,
                disabled,
                readOnly,
                visible,
                obscured,
                editable,
                footerLike,
                textPreview: normalize(el.innerText || el.textContent || ''),
                className: typeof el.className === 'string' ? normalize(el.className) : '',
                id: normalize(el.id || ''),
                rectTop: Number.isFinite(rect.top) ? Math.round(rect.top) : 0,
                rectLeft: Number.isFinite(rect.left) ? Math.round(rect.left) : 0,
                rectWidth: Number.isFinite(rect.width) ? Math.round(rect.width) : 0,
                rectHeight: Number.isFinite(rect.height) ? Math.round(rect.height) : 0,
                viewportHeight: window.innerHeight || 0,
              };
            }
            """
        )
    except Exception:
        return {}


def _score_input_candidate_metadata(metadata: dict[str, Any], preferred_scope: str, candidate_scope: str) -> int:
    score = 0
    tag = str(metadata.get("tag", ""))
    role = str(metadata.get("role", ""))
    candidate_type = str(metadata.get("type", ""))
    placeholder = f"{metadata.get('placeholder', '')} {metadata.get('ariaLabel', '')}".lower()

    if metadata.get("visible"):
        score += 12
    else:
        score -= 10
    if metadata.get("editable"):
        score += 12
    else:
        score -= 6
    if metadata.get("disabled"):
        score -= 12
    else:
        score += 4
    if metadata.get("obscured"):
        score -= 8
    else:
        score += 5
    if metadata.get("footerLike"):
        score += 4
    if candidate_scope == preferred_scope:
        score += 6

    if tag == "textarea":
        score += 8
    elif tag == "input" and candidate_type in {"text", "search", ""}:
        score += 6
    elif role == "textbox":
        score += 6
    elif metadata.get("contentEditable"):
        score += 7

    if any(keyword in placeholder for keyword in ["질문", "문의", "메시지", "채팅", "입력", "message", "chat", "ask"]):
        score += 8

    rect_top = int(metadata.get("rectTop", 0) or 0)
    viewport_height = int(metadata.get("viewportHeight", 0) or 0)
    if viewport_height > 0 and rect_top > int(viewport_height * 0.45):
        score += 3

    return score


def _is_excluded_non_chat_candidate(metadata: dict[str, Any]) -> bool:
    combined = _norm_text(
        f"{metadata.get('placeholder', '')} {metadata.get('ariaLabel', '')} {metadata.get('textPreview', '')}"
    ).lower()
    return any(
        hint in combined
        for hint in [
            "궁금한 제품을 찾아보세요",
            "검색어를 입력",
            "search",
        ]
    )


def _iter_chat_input_roots(context: ResolvedChatContext) -> list[tuple[str, Locator]]:
    roots: list[tuple[str, Locator]] = []
    seen: set[str] = set()

    def add_root(label: str, locator: Locator) -> None:
        if label in seen:
            return
        try:
            if not locator.is_visible(timeout=300):
                return
        except Exception:
            return
        seen.add(label)
        roots.append((label, locator))

    if context.container_locator is not None:
        add_root("chat_container", context.container_locator)
        for selector in CHAT_INPUT_ROOT_SELECTORS:
            try:
                locator = context.container_locator.locator(selector)
                count = min(locator.count(), 3)
            except Exception:
                continue
            for index in range(count):
                add_root(f"container:{selector}:{index}", locator.nth(index))

    if context.input_locator is not None:
        for xpath in [
            "xpath=ancestor-or-self::*[self::footer or self::form][1]",
            "xpath=ancestor-or-self::*[contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'footer') or contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'composer') or contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'input')][1]",
        ]:
            try:
                add_root(f"input_ancestor:{xpath}", context.input_locator.locator(xpath).first)
            except Exception:
                continue

    if not roots:
        for selector in CHAT_INPUT_ROOT_SELECTORS:
            try:
                locator = context.scope.locator(selector)
                count = min(locator.count(), 3)
            except Exception:
                continue
            for index in range(count):
                add_root(f"scope:{selector}:{index}", locator.nth(index))

    return roots


def _collect_chat_input_candidates(context: ResolvedChatContext) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, int, int]] = set()
    roots = _iter_chat_input_roots(context)

    if context.input_locator is not None:
        metadata = _input_candidate_snapshot(context.input_locator)
        if metadata and metadata.get("visible") and not _is_excluded_non_chat_candidate(metadata):
            placeholder = _norm_text(metadata.get("placeholder"))
            aria_label = _norm_text(metadata.get("ariaLabel"))
            key = (
                "current_input",
                str(metadata.get("tag", "")),
                placeholder,
                int(metadata.get("rectTop", 0) or 0),
                int(metadata.get("rectLeft", 0) or 0),
            )
            seen.add(key)
            current_candidate = {
                "locator": context.input_locator,
                "scope": context.input_scope or context.scope,
                "scope_name": context.input_scope_name or context.scope_name,
                "selector": context.input_selector or str(metadata.get("tag", "") or "current_input"),
                "root_label": "current_input",
                "visible": bool(metadata.get("visible")),
                "enabled": not bool(metadata.get("disabled")),
                "editable": bool(metadata.get("editable")),
                "disabled": bool(metadata.get("disabled")),
                "readonly": bool(metadata.get("readOnly")),
                "aria_disabled": False,
                "aria_readonly": False,
                "placeholder": placeholder,
                "aria_label": aria_label,
                "aria": aria_label,
                "tag_name": str(metadata.get("tag", "")).lower(),
                "role": str(metadata.get("role", "")).lower(),
                "contenteditable": str(metadata.get("contentEditable", "")).lower(),
                "bbox_width": int(metadata.get("rectWidth", 0) or 0),
                "bbox_height": int(metadata.get("rectHeight", 0) or 0),
                "rectTop": int(metadata.get("rectTop", 0) or 0),
                "viewportHeight": int(metadata.get("viewportHeight", 0) or 0),
                "footerLike": bool(metadata.get("footerLike")),
            }
            current_candidate["score"] = (
                50
                + (18 if current_candidate["footerLike"] else 0)
                + (12 if any(hint in f"{placeholder} {aria_label}" for hint in CHAT_READY_HINTS) else 0)
                + _candidate_bottom_weight(current_candidate)
                + (4 if current_candidate["tag_name"] == "textarea" else 0)
                - (25 if current_candidate["disabled"] else 0)
            )
            candidates.append(current_candidate)

    for root_label, root in roots:
        for selector in CHAT_READY_SCAN_SELECTORS:
            try:
                locator = root.locator(selector)
                count = min(locator.count(), 4)
            except Exception:
                continue
            for index in range(count):
                current = locator.nth(index)
                metadata = _input_candidate_snapshot(current)
                if not metadata or not metadata.get("visible"):
                    continue
                if _is_excluded_non_chat_candidate(metadata):
                    continue
                key = (
                    root_label,
                    str(metadata.get("tag", "")),
                    str(metadata.get("placeholder", "")),
                    int(metadata.get("rectTop", 0) or 0),
                    int(metadata.get("rectLeft", 0) or 0),
                )
                if key in seen:
                    continue
                seen.add(key)
                placeholder = _norm_text(metadata.get("placeholder"))
                aria_label = _norm_text(metadata.get("ariaLabel"))
                candidate = {
                    "locator": current,
                    "scope": context.scope,
                    "scope_name": context.scope_name,
                    "selector": selector,
                    "root_label": root_label,
                    "visible": bool(metadata.get("visible")),
                    "enabled": not bool(metadata.get("disabled")),
                    "editable": bool(metadata.get("editable")),
                    "disabled": bool(metadata.get("disabled")),
                    "readonly": bool(metadata.get("readOnly")),
                    "aria_disabled": False,
                    "aria_readonly": False,
                    "placeholder": placeholder,
                    "aria_label": aria_label,
                    "aria": aria_label,
                    "tag_name": str(metadata.get("tag", "")).lower(),
                    "role": str(metadata.get("role", "")).lower(),
                    "contenteditable": str(metadata.get("contentEditable", "")).lower(),
                    "bbox_width": int(metadata.get("rectWidth", 0) or 0),
                    "bbox_height": int(metadata.get("rectHeight", 0) or 0),
                    "rectTop": int(metadata.get("rectTop", 0) or 0),
                    "viewportHeight": int(metadata.get("viewportHeight", 0) or 0),
                    "footerLike": bool(metadata.get("footerLike")),
                }
                candidate["score"] = (
                    (40 if candidate["editable"] else 0)
                    + (18 if candidate["footerLike"] else 0)
                    + (12 if any(hint in f"{placeholder} {aria_label}" for hint in CHAT_READY_HINTS) else 0)
                    + _candidate_bottom_weight(candidate)
                    + (4 if selector == "textarea" else 0)
                    - (25 if candidate["disabled"] else 0)
                )
                candidates.append(candidate)

    candidates.sort(key=lambda item: item.get("score", 0), reverse=True)
    return candidates


def _history_entry(state: str, candidate: dict[str, Any] | None, started: float) -> dict[str, Any]:
    return {
        "ts": round(time.monotonic() - started, 2),
        "state": state,
        "selector": (candidate or {}).get("selector", ""),
        "placeholder": _norm_text((candidate or {}).get("placeholder")),
        "aria": _norm_text((candidate or {}).get("aria_label") or (candidate or {}).get("aria")),
        "editable": bool((candidate or {}).get("editable", False)),
        "disabled": bool((candidate or {}).get("disabled", False)),
    }


def wait_until_chat_input_ready(
    page: Page,
    ctx: ResolvedChatContext,
    case_id: str,
    config: AppConfig,
) -> dict[str, Any]:
    del case_id
    runtime = _runtime()
    max_rounds = _context_resolve_rounds(config)
    poll_ms = _context_resolve_wait_ms(config)
    runtime.logger.info(
        "[CHAT_READY][START] rounds=%s poll_ms=%s scope=%s",
        max_rounds,
        poll_ms,
        getattr(ctx, "scope_name", "resolved_ctx"),
    )
    started = time.monotonic()
    history: list[dict[str, Any]] = []
    last_state = ""

    for round_index in range(max_rounds):
        context_candidates: list[dict[str, Any]] = []
        for scope_name, scope in _iter_fast_transition_contexts(page, ctx):
            current_ctx = ctx if scope is getattr(ctx, "scope", None) else scope
            current_candidates = _collect_lightweight_candidates(current_ctx, scope_name)
            for candidate in current_candidates:
                candidate.setdefault("scope_name", scope_name)
                candidate.setdefault("scope", scope)
            context_candidates.extend(current_candidates)

        candidates = sorted(context_candidates, key=lambda item: item.get("score", 0), reverse=True)
        ready_candidate = next((candidate for candidate in candidates if _is_ready_candidate(candidate)), None)
        disabled_candidate = next((candidate for candidate in candidates if _is_disabled_transition_candidate(candidate)), None)
        fallback_candidate = None
        if round_index == 0:
            fallback_candidate = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.get("visible", False)
                    and not candidate.get("disabled", False)
                    and str(candidate.get("reason", "")) != "placeholder_shell"
                ),
                None,
            )

        if ready_candidate is not None:
            runtime.logger.info(
                "[CHAT_READY][READY] selector=%s placeholder=%r aria=%r editable=%s",
                ready_candidate.get("selector"),
                ready_candidate.get("placeholder"),
                ready_candidate.get("aria_label"),
                ready_candidate.get("editable"),
            )
            if last_state != "ready":
                history.append(_history_entry("ready", ready_candidate, started))
            return {
                "ready": True,
                "timeout": False,
                "scope": ready_candidate.get("scope", ctx.scope),
                "scope_name": ready_candidate.get("scope_name", getattr(ctx, "scope_name", "resolved_ctx")),
                "candidate": ready_candidate,
                "history": history,
                "result": "ready",
            }

        if fallback_candidate is not None:
            runtime.logger.info(
                "[CHAT_READY][FALLBACK] selector=%s placeholder=%r aria=%r editable=%s",
                fallback_candidate.get("selector"),
                fallback_candidate.get("placeholder"),
                fallback_candidate.get("aria_label"),
                fallback_candidate.get("editable"),
            )
            history.append(_history_entry("fallback_candidate", fallback_candidate, started))
            return {
                "ready": True,
                "timeout": False,
                "scope": fallback_candidate.get("scope", ctx.scope),
                "scope_name": fallback_candidate.get("scope_name", getattr(ctx, "scope_name", "resolved_ctx")),
                "candidate": fallback_candidate,
                "history": history,
                "result": "fallback_candidate",
            }

        if disabled_candidate is not None:
            runtime.logger.info(
                "[CHAT_READY][WAITING_DISABLED] selector=%s placeholder=%r aria=%r",
                disabled_candidate.get("selector"),
                disabled_candidate.get("placeholder"),
                disabled_candidate.get("aria_label"),
            )
            if last_state != "waiting_disabled":
                history.append(_history_entry("waiting_disabled", disabled_candidate, started))
                last_state = "waiting_disabled"
        else:
            if last_state != "waiting_other":
                history.append(_history_entry("waiting_other", candidates[0] if candidates else None, started))
                last_state = "waiting_other"

        if round_index != max_rounds - 1:
            page.wait_for_timeout(poll_ms)

    runtime.logger.warning("[CHAT_READY][TIMEOUT]")
    return {
        "ready": False,
        "timeout": True,
        "scope": ctx.scope,
        "scope_name": getattr(ctx, "scope_name", "resolved_ctx"),
        "candidate": None,
        "history": history,
        "result": "timeout",
    }


def _classify_input_candidate_metadata(metadata: dict[str, Any]) -> tuple[str, str]:
    if not metadata:
        return "input locator not found", "No input candidate metadata available"
    if metadata.get("disabled"):
        return "input locator found but disabled", "Input candidate exists but is disabled"
    if not metadata.get("editable"):
        return "input locator found but not editable", "Input candidate exists but is not editable"
    if metadata.get("obscured"):
        return "input locator found but obscured by overlay", "Input candidate exists but is obscured by another element"
    return "", ""


def _format_input_candidate_log(candidate: _InputCandidate) -> str:
    metadata = candidate.metadata
    return (
        f"scope={candidate.scope_name} score={candidate.score} selector={candidate.selector} index={candidate.index} "
        f"tag={metadata.get('tag', '')} type={metadata.get('type', '')} role={metadata.get('role', '')} "
        f"visible={metadata.get('visible', False)} editable={metadata.get('editable', False)} "
        f"disabled={metadata.get('disabled', False)} obscured={metadata.get('obscured', False)} "
        f"placeholder={metadata.get('placeholder', '')!r} aria={metadata.get('ariaLabel', '')!r} "
        f"footerLike={metadata.get('footerLike', False)} rect=({metadata.get('rectLeft', 0)},{metadata.get('rectTop', 0)},{metadata.get('rectWidth', 0)},{metadata.get('rectHeight', 0)})"
    )


def _collect_input_candidates(scope: Page | Frame, scope_name: str, preferred_scope_name: str) -> list[_InputCandidate]:
    candidates: list[_InputCandidate] = []
    seen: set[tuple[str, str, str, str, int, int]] = set()
    for selector in INPUT_SCAN_SELECTORS:
        try:
            locator = scope.locator(selector)
            count = locator.count()
        except Exception:
            continue
        for index in range(count):
            candidate_locator = locator.nth(index)
            metadata = _input_candidate_snapshot(candidate_locator)
            if not metadata:
                continue
            key = (
                scope_name,
                str(metadata.get("tag", "")),
                str(metadata.get("placeholder", "")),
                str(metadata.get("ariaLabel", "")),
                int(metadata.get("rectTop", 0) or 0),
                int(metadata.get("rectLeft", 0) or 0),
            )
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                _InputCandidate(
                    scope=scope,
                    scope_name=scope_name,
                    locator=candidate_locator,
                    selector=selector,
                    index=index,
                    score=_score_input_candidate_metadata(metadata, preferred_scope_name, scope_name),
                    metadata=metadata,
                )
            )
    return candidates


def _resolve_best_input_candidate(page: Page, preferred_scope_name: str) -> tuple[_InputCandidate | None, list[str], str, str]:
    runtime = _runtime()
    all_candidates: list[_InputCandidate] = []
    for scope_name, scope in _iter_scopes(page):
        all_candidates.extend(_collect_input_candidates(scope, scope_name, preferred_scope_name))

    ordered = sorted(all_candidates, key=lambda item: item.score, reverse=True)
    candidate_logs = [_format_input_candidate_log(candidate) for candidate in ordered]
    if candidate_logs:
        runtime.logger.info("[INPUT] opened HTML candidate count: %s", len(candidate_logs))
        for entry in candidate_logs:
            runtime.logger.info("[INPUT] opened HTML candidate %s", entry)
    else:
        runtime.logger.warning("[INPUT] opened HTML candidate count: 0")

    if not ordered:
        return None, candidate_logs, "input locator not found", "No textarea/input/contenteditable candidate found across page and iframes"

    best = ordered[0]
    category, reason = _classify_input_candidate_metadata(best.metadata)
    return best, candidate_logs, category, reason


def get_sprinklr_sdk_status(page: Page) -> dict[str, bool]:
    status = {"has_sprchat": False, "trigger_exists": False}
    try:
        status = page.evaluate(
            """
            () => ({
              has_sprchat: typeof window.sprChat === 'function',
              trigger_exists: !!document.querySelector('#spr-chat__trigger-button'),
            })
            """
        )
    except Exception:
        pass
    _runtime().logger.info(
        "[SPR][SDK_STATUS] has_sprchat=%s trigger_exists=%s",
        status.get("has_sprchat", False),
        status.get("trigger_exists", False),
    )
    return status


def bind_availability_probe(page: Page) -> None:
    runtime = _runtime()
    try:
        subscribed = page.evaluate(
            """
            () => {
              window.__rubicon_chat_probe = window.__rubicon_chat_probe || { availability: 'unknown' };
              if (typeof window.sprChat !== 'function') {
                return false;
              }
              try {
                window.sprChat('onAvailabilityChange', (value) => {
                  const nextValue = typeof value === 'string' ? value : (value?.availability || value?.status || 'unknown');
                  window.__rubicon_chat_probe.availability = String(nextValue || 'unknown');
                });
                return true;
              } catch (error) {
                return false;
              }
            }
            """
        )
        if subscribed:
            runtime.logger.info("[SPR][AVAILABILITY][SUBSCRIBED]")
    except Exception:
        pass


def get_availability_probe(page: Page) -> str:
    value = "unknown"
    try:
        value = str(
            page.evaluate(
                "() => (window.__rubicon_chat_probe && window.__rubicon_chat_probe.availability) || 'unknown'"
            )
        )
    except Exception:
        value = "unknown"
    _runtime().logger.info("[SPR][AVAILABILITY][STATE] value=%s", value)
    if value.lower() in UNAVAILABLE_AVAILABILITY_VALUES:
        _runtime().logger.warning("[SPR][AVAILABILITY][UNAVAILABLE_HINT]")
    return value


def _chat_surface_present(page: Page) -> bool:
    for _, scope in _iter_scopes(page):
        try:
            if _locator_count(scope, "textarea, [role='textbox'], [contenteditable='true'], .ql-editor") > 0:
                return True
            if _locator_count(scope, "[role='dialog'], [class*='chat' i], [class*='composer' i]") > 0:
                return True
        except Exception:
            continue
    return False


def _click_selector_candidates(scope: Page | Frame, selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            locator = scope.locator(selector).first
            if locator.count() <= 0:
                continue
            locator.click(timeout=2000)
            return True
        except Exception:
            continue
    return False


def _button_matches_any_hint(text: str, aria_label: str, hints: list[str]) -> bool:
    haystack = _normalize_text(f"{text} {aria_label}")
    if not haystack:
        return False
    return any(hint in haystack for hint in hints)


def _click_button_by_hints(
    scope: Page | Frame,
    hints: list[str],
    *,
    logger: Any,
    log_tag: str,
    timeout_ms: int = 2000,
) -> bool:
    try:
        buttons = scope.locator("button, [role='button']")
        count = min(buttons.count(), 80)
    except Exception as exc:
        logger.debug("[%s][SCAN_FAIL] err=%s", log_tag, exc)
        return False

    for index in range(count):
        locator = buttons.nth(index)
        try:
            if not locator.is_visible(timeout=300):
                continue
        except Exception:
            continue

        try:
            payload = locator.evaluate(
                                r"""
                (el) => ({
                  text: (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim(),
                  aria: (el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim(),
                  disabled: !!el.disabled || (el.getAttribute('aria-disabled') || '').toLowerCase() === 'true',
                })
                """
            )
        except Exception:
            continue

        text = str(payload.get("text", "") or "")
        aria_label = str(payload.get("aria", "") or "")
        disabled = bool(payload.get("disabled", False))
        if disabled or not _button_matches_any_hint(text, aria_label, hints):
            continue

        try:
            locator.click(timeout=timeout_ms)
            logger.info("[%s][CLICK] index=%s text=%r aria=%r", log_tag, index, text, aria_label)
            return True
        except Exception as exc:
            logger.warning("[%s][CLICK_FAIL] index=%s text=%r aria=%r err=%s", log_tag, index, text, aria_label, exc)

    logger.info("[%s][NOT_FOUND] hints=%s", log_tag, hints)
    return False


def _end_conversation_via_menu(page: Page, context: ResolvedChatContext) -> bool:
    runtime = _runtime()
    scopes: list[tuple[str, Page | Frame]] = []
    seen: set[int] = set()
    for scope_name, scope in [(context.scope_name, context.scope), ("page", page)]:
        key = id(scope)
        if key in seen:
            continue
        seen.add(key)
        scopes.append((scope_name, scope))

    for scope_name, scope in scopes:
        if not _click_button_by_hints(
            scope,
            CHAT_MENU_BUTTON_HINTS,
            logger=runtime.logger,
            log_tag=f"SPR][CONVERSATION_RESET][MENU_OPEN:{scope_name}",
        ):
            continue

        page.wait_for_timeout(500)
        if not _click_button_by_hints(
            scope,
            CHAT_END_CONVERSATION_HINTS,
            logger=runtime.logger,
            log_tag=f"SPR][CONVERSATION_RESET][MENU_END:{scope_name}",
        ):
            continue

        page.wait_for_timeout(900)
        _click_button_by_hints(
            scope,
            CHAT_CONFIRM_BUTTON_HINTS,
            logger=runtime.logger,
            log_tag=f"SPR][CONVERSATION_RESET][MENU_CONFIRM:{scope_name}",
        )
        page.wait_for_timeout(1200)
        runtime.logger.info("[SPR][CONVERSATION_RESET][MENU_OK] scope=%s", scope_name)
        return True

    runtime.logger.warning("[SPR][CONVERSATION_RESET][MENU_FAIL]")
    return False


def open_chat_widget_or_conversation(page: Page) -> dict[str, Any]:
    runtime = _runtime()
    result = {"open_method": "failed", "open_ok": False, "open_error": ""}
    sdk_status = get_sprinklr_sdk_status(page)

    def maybe_start_new_conversation(method_name: str) -> None:
        if runtime.config.rubicon_disable_sdk or not sdk_status.get("has_sprchat"):
            return
        if method_name == "sdk_open_new":
            return
        try:
            page.evaluate("() => window.sprChat('openNewConversation')")
            page.wait_for_timeout(1200)
            runtime.logger.info("[SPR][OPEN][NEW_CONVERSATION] method=%s", method_name)
        except Exception as exc:
            runtime.logger.warning("[SPR][OPEN][NEW_CONVERSATION_FALLBACK] method=%s err=%s", method_name, exc)

    methods: list[tuple[str, Any]] = [
        ("ui_star_launcher", lambda: _click_preferred_rubicon_launcher(page)[0]),
        ("ui_launcher_candidates", lambda: _click_selector_candidates(page, ["#spr-chat__trigger-button", *_SPR_CHAT_TRIGGER_CANDIDATES])),
    ]
    if not runtime.config.rubicon_disable_sdk and sdk_status.get("has_sprchat"):
        methods.extend([
            ("sdk_open_new", lambda: page.evaluate("() => window.sprChat('openNewConversation')")),
            ("sdk_open", lambda: page.evaluate("() => window.sprChat('open')")),
        ])
    if sdk_status.get("trigger_exists"):
        methods.append(("trigger_button", lambda: page.locator("#spr-chat__trigger-button").first.click(timeout=2000)))
    methods.append(("generic_trigger", lambda: _click_selector_candidates(page, _SPR_CHAT_TRIGGER_CANDIDATES)))

    for method_name, action in methods:
        runtime.logger.info("[SPR][OPEN][TRY] method=%s", method_name)
        try:
            action()
            page.wait_for_timeout(800)
            if _chat_surface_present(page):
                maybe_start_new_conversation(method_name)
                runtime.logger.info("[SPR][OPEN][OK] method=%s", method_name)
                result.update({"open_method": method_name, "open_ok": True, "open_error": ""})
                return result
            runtime.logger.info("[SPR][OPEN][FALLBACK] method=%s", method_name)
        except Exception as exc:
            runtime.logger.warning("[SPR][OPEN][FALLBACK] method=%s", method_name)
            result["open_error"] = str(exc)

    runtime.logger.info("[SPR][OPEN][TRY] method=legacy_chat_icon")
    try:
        open_rubicon_widget(page)
        page.wait_for_timeout(800)
        result.update({"open_method": "legacy_chat_icon", "open_ok": _chat_surface_present(page), "open_error": ""})
        if result["open_ok"]:
            maybe_start_new_conversation("legacy_chat_icon")
            runtime.logger.info("[SPR][OPEN][OK] method=legacy_chat_icon")
            return result
    except Exception as exc:
        result["open_error"] = str(exc)

    runtime.logger.error("[SPR][OPEN][FAIL] error=%s", result.get("open_error", ""))
    return result


def _has_stale_conversation_messages(context: ResolvedChatContext) -> tuple[bool, list[str]]:
    candidates: list[str] = []
    seen: set[str] = set()

    for item in extract_structured_message_history(context).get("history", []):
        normalized = _normalize_text(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(item)

    for item in extract_bot_message_texts(context):
        normalized = _normalize_text(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(item)

    stale_messages: list[str] = []
    for item in candidates:
        normalized = _normalize_text(item)
        if not normalized:
            continue
        if is_initial_menu_text(normalized):
            continue
        if any(hint in normalized for hint in CHAT_READY_HINTS + CHAT_READY_SIGNAL_HINTS + CHAT_DISABLED_HINTS):
            continue
        if any(hint in normalized for hint in HISTORY_ALWAYS_DROP_HINTS):
            continue
        stale_messages.append(item)

    return bool(stale_messages), stale_messages


def ensure_clean_conversation(page: Page, context: ResolvedChatContext) -> ResolvedChatContext:
    runtime = _runtime()
    has_stale_messages, stale_messages = _has_stale_conversation_messages(context)
    if not has_stale_messages:
        runtime.logger.info("[SPR][CONVERSATION_RESET][CLEAN]")
        return context

    runtime.logger.warning(
        "[SPR][CONVERSATION_RESET][DIRTY] count=%s preview=%s",
        len(stale_messages),
        _normalize_text(stale_messages[0])[:160],
    )

    refreshed_context = context
    for attempt in range(1, 4):
        reset_method = "sdk_open_new"
        try:
            page.evaluate("() => window.sprChat('openNewConversation')")
            page.wait_for_timeout(900 * attempt)
        except Exception as exc:
            runtime.logger.warning("[SPR][CONVERSATION_RESET][SDK_FAIL] attempt=%s err=%s", attempt, exc)
            reset_method = "menu_end_conversation"
            if not _end_conversation_via_menu(page, refreshed_context):
                break
            open_chat_widget_or_conversation(page)
            page.wait_for_timeout(900 * attempt)

        try:
            refreshed_context = resolve_chat_context(page)
        except Exception as exc:
            runtime.logger.warning("[SPR][CONVERSATION_RESET][RESOLVE_FAIL] attempt=%s err=%s", attempt, exc)
            refreshed_context = context

        has_stale_messages, stale_messages = _has_stale_conversation_messages(refreshed_context)
        if has_stale_messages and reset_method == "sdk_open_new":
            runtime.logger.warning("[SPR][CONVERSATION_RESET][SDK_DIRTY] attempt=%s remaining=%s", attempt, len(stale_messages))
            if _end_conversation_via_menu(page, refreshed_context):
                reset_method = "menu_end_conversation"
                open_chat_widget_or_conversation(page)
                page.wait_for_timeout(900 * attempt)
                try:
                    refreshed_context = resolve_chat_context(page)
                except Exception as exc:
                    runtime.logger.warning("[SPR][CONVERSATION_RESET][MENU_RESOLVE_FAIL] attempt=%s err=%s", attempt, exc)
                has_stale_messages, stale_messages = _has_stale_conversation_messages(refreshed_context)

        runtime.logger.info(
            "[SPR][CONVERSATION_RESET][CHECK] attempt=%s method=%s stale=%s remaining=%s",
            attempt,
            reset_method,
            has_stale_messages,
            len(stale_messages),
        )
        if not has_stale_messages:
            return refreshed_context

    runtime.logger.warning("[SPR][CONVERSATION_RESET][FAILED] continuing with existing context")
    return refreshed_context


def scan_frame_inventory(page: Page) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    scopes = [(0, "page", page)]
    scopes.extend((index + 1, frame.name or frame.url or f"frame-{index}", frame) for index, frame in enumerate(page.frames))
    for frame_index, label, scope in scopes:
        ranked_candidates: list[dict[str, Any]] = []
        for selector in INPUT_SCAN_SELECTORS:
            try:
                locator = scope.locator(selector)
                for index in range(locator.count()):
                    ranked_candidates.append(_inspect_candidate(locator.nth(index)))
            except Exception:
                continue
        item = {
            "frame_index": frame_index,
            "frame_label": label,
            "url": getattr(scope, "url", "") if isinstance(scope, Frame) else page.url,
            "textarea_count": _locator_count(scope, "textarea"),
            "contenteditable_count": _locator_count(scope, "[contenteditable='true'], [contenteditable='plaintext-only'], div[contenteditable]"),
            "role_textbox_count": _locator_count(scope, "[role='textbox']"),
            "visible_candidate_count": sum(1 for candidate in ranked_candidates if candidate.get("visible")),
            "editable_candidate_count": sum(1 for candidate in ranked_candidates if _grade_candidate_state(candidate)[0] in {"A", "B"}),
            "disabled_candidate_count": sum(1 for candidate in ranked_candidates if candidate.get("disabled") or candidate.get("readonly") or candidate.get("aria_disabled") or candidate.get("aria_readonly")),
        }
        inventory.append(item)
        _runtime().logger.info(
            "[INPUT_V2][FRAME_INVENTORY] frame=%s url=%s textarea=%s contenteditable=%s role_textbox=%s editable=%s disabled=%s",
            item["frame_index"],
            item["url"],
            item["textarea_count"],
            item["contenteditable_count"],
            item["role_textbox_count"],
            item["editable_candidate_count"],
            item["disabled_candidate_count"],
        )
    return inventory


def _resolve_candidate_scope(ctx: ResolvedChatContext) -> list[tuple[str, Page | Frame]]:
    if ctx.page is None:
        return [(ctx.scope_name, ctx.scope)]
    return _iter_scopes(ctx.page)


def _update_context_from_ranked_candidates(ctx: ResolvedChatContext, ranked_candidates: list[dict[str, Any]]) -> None:
    ctx.ranked_input_candidates = ranked_candidates
    ctx.input_candidate_logs = [_candidate_debug_line(candidate) for candidate in ranked_candidates]
    ctx.input_candidates_debug = "\n".join(ctx.input_candidate_logs)
    preferred = next((candidate for candidate in ranked_candidates if candidate["grade"] in {"A", "B"}), None)
    if preferred is None and ranked_candidates:
        preferred = ranked_candidates[0]
    if preferred is None:
        ctx.input_locator = None
        ctx.input_scope = None
        ctx.input_scope_name = ""
        ctx.input_selector = ""
        ctx.input_candidate_score = 0.0
        return

    _assign_candidate_to_context(ctx, preferred)


def collect_ranked_input_candidates(ctx: ResolvedChatContext, frame_label: str = "", preferred_scope: str = "") -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    preferred_scope_name = preferred_scope or frame_label or ctx.scope_name or ctx.input_scope_name
    seen: set[tuple[str, str, str, str, int, int]] = set()
    for scope_name, scope in _resolve_candidate_scope(ctx):
        if frame_label and scope_name != frame_label:
            continue
        for selector in INPUT_SCAN_SELECTORS:
            try:
                locator = scope.locator(selector)
                count = locator.count()
            except Exception:
                continue
            for index in range(count):
                current = locator.nth(index)
                state = _inspect_candidate(current)
                key = (
                    scope_name,
                    selector,
                    state.get("tag_name", ""),
                    state.get("placeholder", ""),
                    int(state.get("bbox_width", 0) or 0),
                    int(state.get("bbox_height", 0) or 0),
                )
                if key in seen:
                    continue
                seen.add(key)
                grade, reason = _grade_candidate_state(state)
                score = _score_ranked_candidate(state, grade, preferred_scope_name, scope_name)
                candidate = {
                    "locator": current,
                    "scope": scope,
                    "scope_name": scope_name,
                    "selector": selector,
                    "score": score,
                    "grade": grade,
                    "reason": reason,
                    "visible": state.get("visible", False),
                    "enabled": state.get("enabled", False),
                    "editable": state.get("editable", False),
                    "disabled": state.get("disabled", False),
                    "readonly": state.get("readonly", False),
                    "aria_disabled": state.get("aria_disabled", False),
                    "aria_readonly": state.get("aria_readonly", False),
                    "placeholder": state.get("placeholder", ""),
                    "aria_label": state.get("aria_label", ""),
                    "bbox_width": state.get("bbox_width", 0),
                    "bbox_height": state.get("bbox_height", 0),
                    "contenteditable": state.get("contenteditable", ""),
                    "role": state.get("role", ""),
                    "tag_name": state.get("tag_name", ""),
                    "failure_category": "" if grade in {"A", "B"} else ("top_candidate_disabled" if reason in {"disabled", "readonly", "aria_disabled", "placeholder_shell"} else "no_editable_candidate_after_rescan"),
                    "failure_reason": reason,
                }
                if grade == "C":
                    _runtime().logger.info("[INPUT_V2][CANDIDATE_FILTER] selector=%s rejected_reason=%s", selector, reason)
                ranked.append(candidate)
    ranked.sort(key=lambda item: item["score"], reverse=True)
    _update_context_from_ranked_candidates(ctx, ranked)
    top_summary = _candidate_debug_line(ranked[0]) if ranked else "none"
    _runtime().logger.info("[INPUT_V2][RANKED_CANDIDATES] count=%s top=%s", len(ranked), top_summary)
    return ranked


def _activation_click(locator: Locator, target: str) -> bool:
    try:
        locator.click(timeout=2000)
        _runtime().logger.info("[SPR][ACTIVATION][CLICK] target=%s", target)
        return True
    except Exception:
        return False


def _activation_targets(page: Page, ctx: ResolvedChatContext) -> list[tuple[str, Locator]]:
    targets: list[tuple[str, Locator]] = []
    if ctx.container_locator is not None:
        targets.append(("chat_container", ctx.container_locator))
    try:
        targets.append(("footer", ctx.scope.locator("footer, form, [class*='footer' i], [class*='composer' i]").first))
    except Exception:
        pass
    if ctx.input_locator is not None:
        try:
            targets.append(("input_wrapper", ctx.input_locator.locator("xpath=ancestor::*[contains(@class, 'input') or contains(@class, 'composer')][1]").first))
        except Exception:
            pass
        try:
            targets.append(("textarea_parent", ctx.input_locator.locator("xpath=parent::*").first))
        except Exception:
            pass
    return targets


def ensure_composer_ready(page: Page, ctx: ResolvedChatContext) -> dict[str, Any]:
    runtime = _runtime()
    runtime.logger.info("[SPR][ACTIVATION][START]")
    steps: list[str] = []
    latest_candidates: list[dict[str, Any]] = []

    for round_index in range(ACTIVATION_MAX_ROUNDS):
        for target_name, locator in _activation_targets(page, ctx):
            step_name = f"round{round_index + 1}:{target_name}"
            try:
                locator.click(timeout=2000)
                steps.append(step_name)
                runtime.logger.info("[SPR][ACTIVATION][CLICK] target=%s", step_name)
            except Exception as exc:
                runtime.logger.debug("[SPR][ACTIVATION][CLICK_FAIL] target=%s err=%s", step_name, exc)
                continue
            page.wait_for_timeout(ACTIVATION_POLL_MS)
            ready_candidates: list[dict[str, Any]] = []
            for scope_label, current_ctx in _iter_fast_transition_contexts(page, ctx):
                latest_candidates = _collect_lightweight_candidates(current_ctx, f"activation_round_{round_index + 1}:{scope_label}")
                ready_candidates.extend([candidate for candidate in latest_candidates if _is_ready_candidate(candidate)])
            runtime.logger.info("[SPR][ACTIVATION][STATE] editable_candidates=%s", len(ready_candidates))
            if ready_candidates:
                _assign_candidate_to_context(ctx, ready_candidates[0])
                runtime.logger.info("[SPR][ACTIVATION][SUCCESS]")
                return {
                    "activation_attempted": True,
                    "activation_steps": steps,
                    "activation_success": True,
                    "editable_candidates_after_activation": len(ready_candidates),
                    "editable_candidates": ready_candidates,
                }
    runtime.logger.warning("[SPR][ACTIVATION][EXHAUSTED]")
    return {
        "activation_attempted": bool(steps),
        "activation_steps": steps,
        "activation_success": False,
        "editable_candidates_after_activation": 0,
        "editable_candidates": [],
    }


def _maybe_visible(scope: Page | Frame, candidate: dict[str, Any]) -> Locator | None:
    locator = build_locator(scope, candidate).first
    try:
        if locator.is_visible(timeout=1500):
            return locator
    except Exception:
        return None
    return None


def _sprinklr_launcher_present(page: Page) -> bool:
    try:
        return page.locator("#spr-chat__trigger-button, .spr-chat__trigger-box button, iframe[title='라이브챗']").count() > 0
    except Exception:
        return False


def _click_preferred_rubicon_launcher(page: Page) -> tuple[bool, str]:
        runtime = _runtime()
        script = r"""
() => {
    const normalize = (value) => (value || '').replace(/\s+/g, ' ').trim();
    const isVisible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width >= 28 && rect.height >= 28;
    };
    const score = (el) => {
        if (!isVisible(el)) return -9999;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        const attrs = normalize([
            el.id,
            el.className,
            el.getAttribute('aria-label') || '',
            el.getAttribute('title') || '',
            el.innerText || el.textContent || '',
        ].join(' ')).toLowerCase();
        let total = 0;
        if (attrs.includes('spr') || attrs.includes('chat') || attrs.includes('assistant') || attrs.includes('rubicon') || attrs.includes('루비콘') || attrs.includes('상담')) total += 18;
        if (attrs.includes('별') || attrs.includes('star')) total += 8;
        if (el.querySelector('svg')) total += 4;
        if (rect.left > window.innerWidth * 0.6 && rect.top > window.innerHeight * 0.55) total += 16;
        if ((style.position || '').includes('fixed') || (style.position || '').includes('sticky')) total += 10;
        const radius = parseFloat(style.borderRadius || '0');
        if (radius >= Math.min(rect.width, rect.height) / 3) total += 6;
        if (rect.width >= 36 && rect.width <= 96 && rect.height >= 36 && rect.height <= 96) total += 5;
        return total;
    };
    const best = Array.from(document.querySelectorAll('button, [role="button"], a, div[role="button"]'))
        .map((el) => ({ el, score: score(el) }))
        .filter((item) => item.score > 0)
        .sort((a, b) => b.score - a.score)[0];
    if (!best) return { clicked: false, method: 'ui_launcher_heuristic' };
    best.el.click();
    return { clicked: true, method: 'ui_launcher_heuristic' };
}
"""
        try:
                payload = page.evaluate(script)
        except Exception as exc:
                runtime.logger.debug("[SPR][OPEN][UI_HEURISTIC_FAIL] %s", exc)
                return False, ""
        return bool(payload.get("clicked")), str(payload.get("method") or "")


def _open_sprinklr_widget(page: Page) -> bool:
    runtime = _runtime()
    settle_wait_ms = 500 if runtime.config.is_speed_mode else 1500
    script = """
() => {
  const button = document.querySelector('#spr-chat__trigger-button, .spr-chat__trigger-box button');
  if (button) {
    button.click();
    return true;
  }
  return false;
}
"""

    try:
        if page.evaluate(script):
            page.wait_for_timeout(settle_wait_ms)
    except Exception:
        pass

    frame_selectors = ["iframe[title='라이브챗']", "iframe[title='Sprinklr live chat']"]
    for selector in frame_selectors:
        try:
            trigger = page.frame_locator(selector).locator("button, [role='button']").first
            if trigger.count() <= 0:
                continue
            trigger.click(timeout=3000)
            page.wait_for_timeout(settle_wait_ms)
            runtime.logger.info("rubicon icon clicked")
            return True
        except Exception:
            continue

    if _sprinklr_launcher_present(page):
        runtime.logger.info("rubicon icon clicked")
        return True
    return False


def inject_korean_font(page: Page) -> bool:
    """Inject Korean font fallback CSS into the page and all loaded frames.

    Returns True when the style tag was injected successfully.
    """

    runtime = _runtime()
    success = _inject_korean_font_css(page, runtime.logger, label="main page")
    for index, frame in enumerate(page.frames):
        _inject_korean_font_css(frame, runtime.logger, label=f"frame[{index}]")
    return success


def _inject_korean_font_css(scope: Page | Frame, logger: Any, label: str = "scope") -> bool:
    try:
        scope.add_style_tag(content=KOREAN_FONT_CSS)
        logger.info("[FONT] Korean font fallback injected into %s", label)
        return True
    except Exception as exc:
        logger.warning("[FONT] font injection failed on %s: %s", label, exc)
        return False


def open_homepage(page: Page) -> None:
    """Open the Samsung /sec/ homepage without entering any login flow."""

    runtime = _runtime()
    page.goto(runtime.config.samsung_base_url, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=min(runtime.config.playwright_timeout_ms, 10000))
    except Exception:
        pass
    runtime.logger.info("homepage opened")


def dismiss_popups(page: Page) -> None:
    """Close blocking popups that could obscure the chatbot widget."""

    runtime = _runtime()
    dismissed = 0
    start_ts = time.monotonic()
    runtime.logger.info("[POPUP] dismiss scan start")
    for _ in range(2):
        if (time.monotonic() - start_ts) >= POPUP_SCAN_TIMEOUT_SEC:
            break
        for scope_name, scope in _iter_popup_scopes(page):
            if (time.monotonic() - start_ts) >= POPUP_SCAN_TIMEOUT_SEC:
                break
            for candidate_group in (POPUP_CLOSE_CANDIDATES, POPUP_ACCEPT_CANDIDATES):
                locator, matched = _first_quick_visible_locator(scope, candidate_group)
                if locator is None:
                    continue
                try:
                    locator.click(timeout=1500)
                    dismissed += 1
                    runtime.logger.info(
                        "[POPUP] clicked scope=%s candidate=%s",
                        scope_name,
                        matched,
                    )
                    page.wait_for_timeout(250)
                except Exception:
                    continue
    runtime.logger.info(
        "popups dismissed count=%s elapsed_sec=%.2f",
        dismissed,
        time.monotonic() - start_ts,
    )


def open_rubicon_widget(page: Page) -> None:
    """Locate and click the floating Rubicon launcher if the chat is not already open."""

    runtime = _runtime()
    input_timeout_ms = 600 if runtime.config.is_speed_mode else 1200
    for scope_name, scope in _iter_scopes(page):
        input_locator, _ = first_visible_locator(scope, INPUT_CANDIDATES, timeout_ms=input_timeout_ms)
        if input_locator is not None:
            runtime.logger.info("rubicon icon clicked")
            return

    if _open_sprinklr_widget(page):
        settle_rounds = 6 if runtime.config.is_speed_mode else 10
        settle_wait_ms = 500 if runtime.config.is_speed_mode else 1000
        for _ in range(settle_rounds):
            for _, scope in _iter_scopes(page):
                input_locator, _ = first_visible_locator(scope, INPUT_CANDIDATES, timeout_ms=600)
                if input_locator is not None:
                    return
            page.wait_for_timeout(settle_wait_ms)

    for scope_name, scope in _iter_scopes(page):
        launcher, _ = first_visible_locator(scope, LAUNCHER_CANDIDATES, timeout_ms=1500)
        if launcher is None:
            continue
        try:
            launcher.scroll_into_view_if_needed(timeout=1500)
            launcher.click(timeout=2000)
            runtime.logger.info("rubicon icon clicked")
            return
        except Exception:
            runtime.logger.debug("launcher click failed in scope %s", scope_name, exc_info=True)
            continue
    raise RuntimeError("Rubicon chatbot icon not found")


def find_sprinklr_frames(page: Page) -> list[Frame]:
    """Return candidate Sprinklr frames, preferring live-chat over proactive frames."""

    frames: list[Frame] = []
    for frame in page.frames:
        frame_hint = f"{frame.name or ''} {frame.url or ''}".lower()
        if "spr" in frame_hint or "chat" in frame_hint or "live" in frame_hint or "assistant" in frame_hint:
            frames.append(frame)
    if frames:
        return frames
    return list(page.frames)


def score_frame_as_chat_candidate(scope: Page | Frame) -> int:
    """Score a page/frame by how much it looks like the active Sprinklr chat surface."""

    score = 0
    scope_hint = ""
    if isinstance(scope, Frame):
        scope_hint = f"{scope.name or ''} {scope.url or ''}".lower()

    input_locator, _ = first_visible_locator(scope, INPUT_CANDIDATES, timeout_ms=500)
    send_locator, _ = first_visible_locator(scope, SEND_BUTTON_CANDIDATES, timeout_ms=400)
    container_locator, container_candidate = first_visible_locator(scope, CONTAINER_CANDIDATES, timeout_ms=400)

    if input_locator is not None:
        score += 8
    if send_locator is not None:
        score += 4
    if container_locator is not None:
        score += 4
    if container_candidate and container_candidate.get("value"):
        score += 1

    live_regions = scope.locator("[role='log'], [role='list'], [role='article'], [aria-live]")
    try:
        if live_regions.count() > 0:
            score += 5
    except Exception:
        pass

    bubble_locator = scope.locator("[data-message-author], [data-author], [class*='message' i], [class*='bubble' i]")
    try:
        bubble_count = bubble_locator.count()
        if bubble_count > 0:
            score += min(bubble_count, 6)
    except Exception:
        pass

    try:
        visible_text = scope.evaluate(
            "() => { const el = document.body || document.documentElement; return el ? (el.innerText || el.textContent || '') : ''; }"
        )
        visible_norm = normalize_text_for_diff(visible_text)
        if any(keyword in visible_norm.lower() for keyword in ["상담", "메시지", "assistant", "chat", "문의"]):
            score += 3
    except Exception:
        pass

    if "live-chat" in scope_hint or "spr-live-chat-frame" in scope_hint:
        score += 7
    if "survey-app" in scope_hint or "survey" in scope_hint:
        score -= 12
    if "session-storage" in scope_hint:
        score -= 4
    if "trigger" in scope_hint:
        score -= 2
    if "proactive" in scope_hint:
        score -= 8

    return score


def resolve_sprinklr_chat_context(page: Page) -> ResolvedChatContext:
    """Resolve the best Sprinklr chat context using frame scoring and visible chat signals."""

    runtime = _runtime()
    candidate_scopes: list[tuple[str, Page | Frame]] = [("page", page)]
    candidate_scopes.extend((frame.name or frame.url or f"frame-{index}", frame) for index, frame in enumerate(find_sprinklr_frames(page)))

    runtime.logger.info("[CONTEXT] frame count: %s", len(page.frames))

    scored: list[tuple[int, str, Page | Frame]] = []
    for scope_name, scope in candidate_scopes:
        score = score_frame_as_chat_candidate(scope)
        runtime.logger.info("[CONTEXT] candidate scope=%s score=%s", scope_name, score)
        if score <= 0:
            continue
        scored.append((score, scope_name, scope))

    fallback_context: ResolvedChatContext | None = None

    for score, scope_name, scope in sorted(scored, key=lambda item: item[0], reverse=True):
        container_locator, container_candidate = first_visible_locator(scope, CONTAINER_CANDIDATES, timeout_ms=900)
        context = ResolvedChatContext(
            scope=scope,
            scope_name=scope_name,
            input_locator=None,
            send_locator=None,
            container_locator=container_locator,
            bot_message_candidates=BOT_MESSAGE_CANDIDATES,
            history_candidates=HISTORY_CANDIDATES,
            loading_candidates=LOADING_CANDIDATES,
            page=page,
            chat_frame_score=score,
        )
        ranked_candidates = collect_ranked_input_candidates(context, scope_name)
        editable_candidates = [candidate for candidate in ranked_candidates if candidate["grade"] in {"A", "B"}]
        top_candidate = ranked_candidates[0] if ranked_candidates else None
        context.input_failure_category = ""
        context.input_failure_reason = ""
        if not editable_candidates:
            if _candidate_is_disabled_like(top_candidate):
                context.input_failure_category = "top_candidate_disabled"
                context.input_failure_reason = top_candidate.get("reason", "disabled")
            else:
                context.input_failure_category = "no_editable_candidate_after_rescan"
                context.input_failure_reason = "No editable candidate found in ranked rescan"
            runtime.logger.info("[CONTEXT] skipping chat frame without editable input: %s", scope_name)
            if fallback_context is None:
                fallback_context = context
            continue
        runtime.logger.info("[CONTEXT] selected chat frame: %s", scope_name)
        runtime.logger.info("[CONTEXT] chat container selector matched: %s", container_candidate)
        runtime.logger.info("[INPUT] selected input scope: %s", context.input_scope_name or "(none)")
        runtime.logger.info("[INPUT] selected input selector: %s", context.input_selector or "(none)")
        runtime.logger.info("[INPUT] selected input score: %s", context.input_candidate_score)
        if context.input_failure_category:
            runtime.logger.warning("[INPUT] %s", context.input_failure_category)
            runtime.logger.warning("[INPUT] %s", context.input_failure_reason)
        return context

    if fallback_context is not None:
        runtime.logger.info("[CONTEXT] selected fallback chat frame: %s", fallback_context.scope_name)
        runtime.logger.info("[INPUT] selected input scope: %s", fallback_context.input_scope_name or "(none)")
        runtime.logger.info("[INPUT] selected input selector: %s", fallback_context.input_selector or "(none)")
        runtime.logger.info("[INPUT] selected input score: %s", fallback_context.input_candidate_score)
        if fallback_context.input_failure_category:
            runtime.logger.warning("[INPUT] %s", fallback_context.input_failure_category)
            runtime.logger.warning("[INPUT] %s", fallback_context.input_failure_reason)
        return fallback_context

    raise RuntimeError("Chat iframe/input context could not be resolved")


def resolve_chat_context(page: Page) -> ResolvedChatContext:
    """Resolve the active chat context from the page DOM or nested iframes."""

    runtime = _runtime()
    last_error: Exception | None = None

    for attempt in range(_context_resolve_rounds(runtime.config)):
        try:
            context = resolve_sprinklr_chat_context(page)
            runtime.logger.info("chat context resolved attempt=%s", attempt + 1)
            return context
        except Exception as exc:
            last_error = exc
            if attempt != _context_resolve_rounds(runtime.config) - 1:
                page.wait_for_timeout(_context_resolve_wait_ms(runtime.config))

    raise RuntimeError(str(last_error or "Chat iframe/input context could not be resolved"))


# ---------------------------------------------------------------------------
# Input verification helpers
# ---------------------------------------------------------------------------

def _detect_input_type(locator: Locator) -> str:
    """Detect whether the locator targets an input, textarea, or contenteditable."""

    try:
        tag = locator.evaluate("el => el.tagName.toLowerCase()")
        if tag in ("input", "textarea"):
            return tag
        ce = locator.evaluate("el => el.contentEditable")
        if ce and ce not in ("inherit", "false"):
            return "contenteditable"
    except Exception:
        pass
    return "input"


def detect_input_kind(locator: Locator) -> str:
    """Return the resolved kind of chat input element."""

    return _detect_input_type(locator)


def _focus_input(locator: Locator, logger: Any) -> bool:
    """Click the input to give it focus; return True on success."""

    try:
        locator.scroll_into_view_if_needed(timeout=1500)
        locator.click(timeout=2000)
        logger.info("[INPUT] focus success")
        return True
    except Exception as exc:
        logger.warning("[INPUT] focus fail: %s", exc)
        return False


def focus_input(locator: Locator) -> bool:
    """Focus the chat input using the configured runtime logger."""

    return _focus_input(locator, _runtime().logger)


def _clear_input(locator: Locator, input_type: str) -> None:
    """Remove any existing text from the input element."""

    try:
        if input_type in ("input", "textarea"):
            locator.fill("", timeout=1500)
        else:
            locator.press("Control+A")
            locator.press("Backspace")
    except Exception:
        try:
            locator.press("Control+A")
            locator.press("Backspace")
        except Exception:
            pass


def clear_input(locator: Locator) -> None:
    """Clear the chat input using the detected input type."""

    _clear_input(locator, detect_input_kind(locator))


def verify_input_text(locator: Locator, question: str, input_type: str) -> bool:
    """Return True when the question text is confirmed present in the input element."""

    try:
        if input_type in ("input", "textarea"):
            value = locator.input_value(timeout=1500)
            return value.strip() == question.strip()
        else:
            text = locator.inner_text(timeout=1500) or locator.text_content(timeout=1500) or ""
            return question.strip() in text.strip()
    except Exception:
        return False


def _read_input_value(locator: Locator, input_type: str) -> str:
    try:
        if input_type in ("input", "textarea"):
            return locator.input_value(timeout=1500).strip()
        return (locator.inner_text(timeout=1500) or locator.text_content(timeout=1500) or "").strip()
    except Exception:
        return ""


def _input_is_editable(locator: Locator) -> bool:
    try:
        return bool(
            locator.evaluate(
                """
                (el) => {
                                    const tag = (el.tagName || '').toLowerCase();
                                    const role = (el.getAttribute('role') || '').toLowerCase();
                                    const contentEditable = (el.getAttribute('contenteditable') || el.contentEditable || '').toLowerCase();
                  const disabled = !!el.disabled;
                  const readOnly = !!el.readOnly;
                                    const ariaDisabled = (el.getAttribute('aria-disabled') || '').toLowerCase() === 'true';
                                    const ariaReadOnly = (el.getAttribute('aria-readonly') || '').toLowerCase() === 'true';
                  const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                  const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
                                    const inputLike = (
                                        tag === 'input' ||
                                        tag === 'textarea' ||
                                        role === 'textbox' ||
                                        (contentEditable && contentEditable !== 'false' && contentEditable !== 'inherit')
                                    );
                                    if (!inputLike) return false;
                                    if (disabled || readOnly || ariaDisabled || ariaReadOnly) return false;
                  if (aria.includes('더이상 입력할 수 없습니다') || placeholder.includes('더이상 입력할 수 없습니다')) {
                    return false;
                  }
                  return true;
                }
                """
            )
        )
    except Exception:
        return False


def _capture_opened_footer(
    case_id: str,
    timestamp: str,
    config: AppConfig,
    logger: Any,
    context: ResolvedChatContext,
) -> str:
    if context.input_locator is None:
        return ""

    safe_id = sanitize_filename(case_id)
    footer_path = config.chatbox_dir / f"{timestamp}_{safe_id}_opened_footer.png"
    footer_locator = context.input_locator
    try:
        footer_locator = context.input_locator.locator(
            "xpath=ancestor-or-self::*[self::footer or self::form or contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'footer') or contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'input') or contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'composer')][1]"
        ).first
        footer_locator.wait_for(state="visible", timeout=1200)
    except Exception:
        footer_locator = context.input_locator

    try:
        footer_locator.screenshot(path=str(footer_path))
        logger.info("[ARTIFACT] opened_footer screenshot saved: %s", footer_path)
        return str(footer_path)
    except Exception as exc:
        logger.warning("opened_footer screenshot failed: %s", exc)
        return ""


def verify_input_dom_state(locator: Locator, question: str) -> bool:
    """Verify that the DOM input element reflects the question text."""

    logger = _runtime().logger
    input_type = detect_input_kind(locator)
    verified = verify_input_text(locator, question, input_type)
    logger.info("[INPUT] DOM input verification %s", "success" if verified else "fail")
    return verified


def _is_send_button_enabled(locator: Locator | None) -> bool | None:
    if locator is None:
        return None
    try:
        return locator.is_enabled()
    except Exception:
        return None


def is_initial_menu_text(text: str) -> bool:
    """Return True if the text matches an initial menu or baseline CTA."""

    return _contains_baseline_menu(text)


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _normalize_answer_text(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"[\u200e\u200f\u202a-\u202e\ufeff]", "", str(text)).replace("\u00a0", " ")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def _extract_alignment_keywords(text: str) -> list[str]:
    normalized = _normalize_answer_text(text).lower()
    if not normalized:
        return []
    stopwords = {
        "알려줘",
        "알려주세요",
        "비교",
        "차이",
        "설명",
        "주세요",
        "what",
        "which",
        "tell",
        "please",
        "about",
    }
    keywords: list[str] = []
    for token in re.findall(r"[a-z0-9가-힣+]{2,}", normalized):
        if token in stopwords or token in keywords:
            continue
        keywords.append(token)
    return keywords


def _has_minimal_question_alignment(question: str, answer: str) -> bool:
    normalized_answer = _clean_bot_answer_candidate(answer).lower()
    if not normalized_answer or _dom_is_question_repetition(question, normalized_answer):
        return False

    question_family = _dom_detect_topic_family(question)
    answer_family = _dom_detect_topic_family(normalized_answer)
    if question_family != "unknown" and answer_family != "unknown" and question_family != answer_family:
        return False

    keywords = _extract_alignment_keywords(question)[:6]
    if not keywords:
        return True
    hits = sum(1 for keyword in keywords if keyword in normalized_answer)
    required_hits = 1 if len(keywords) <= 2 else 2
    return hits >= required_hits


def _wait_one_more_extraction_cycle(context: ResolvedChatContext, interval_sec: float) -> None:
    if hasattr(context.scope, "wait_for_timeout"):
        context.scope.wait_for_timeout(int(interval_sec * 1000))
    else:
        time.sleep(interval_sec)


def _quality_gate_fix_suggestion(reasons: list[str]) -> str:
    if any(reason in reasons for reason in {"question_repetition", "carryover", "topic_mismatch"}):
        return "현재 질문과 맞는 새 답변이 나오도록 문맥 오염을 제거하고 재실행하세요."
    if "truncated" in reasons:
        return "응답 안정화를 한 번 더 기다리거나 추출을 다시 시도해 완결된 본문만 채택하세요."
    return "UI 노이즈 제거 후에도 핵심 본문과 키워드 정렬이 충분한 후보만 채택하세요."


def _assess_dom_payload_acceptance(test_case: TestCase, dom_payload: dict[str, Any]) -> dict[str, Any]:
    decision = assess_answer_acceptance(test_case.question, dom_payload, _runtime().config)
    return {
        "passed": decision.accepted,
        "status": "passed" if decision.accepted else decision.extraction_status,
        "reason": decision.reason,
        "fix_suggestion": decision.fix_suggestion,
        "question_repetition_detected": bool(dom_payload.get("question_repetition_detected", False)),
        "truncated_detected": bool(dom_payload.get("truncated_detected", False)),
        "carryover_detected": bool(dom_payload.get("carryover_detected", False)) or bool(dom_payload.get("stale_answer_detected", False)),
        "topic_mismatch_detected": bool(dom_payload.get("topic_mismatch_detected", False)),
        "keyword_coverage_low": decision.keyword_coverage_score < _runtime().config.acceptance_keyword_threshold,
        "keyword_coverage_score": decision.keyword_coverage_score,
        "ui_noise_stripped": bool(dom_payload.get("ui_noise_stripped", False)),
        "acceptance_status": decision.acceptance_status,
        "primary_error_category": decision.primary_error_category,
    }


def _strip_answer_meta_prefixes(text: str) -> str:
    cleaned = _normalize_answer_text(text)
    if not cleaned:
        return ""

    if cleaned.startswith("답변 생성 중") and len(cleaned) >= 80:
        substantive_tail = cleaned[len("답변 생성 중"):].strip()
        if substantive_tail and any(token in substantive_tail for token in ["입니다", "예요", "지원", "배터리", "디스플레이", "카메라"]):
            return cleaned

    changed = True
    while changed:
        changed = False
        for pattern in _ANSWER_META_PREFIX_PATTERNS:
            updated = pattern.sub("", cleaned).strip()
            if updated != cleaned:
                cleaned = updated
                changed = True

    return cleaned


def _is_noise_line(line: str) -> bool:
    line_n = _strip_answer_meta_prefixes(line)
    if not line_n:
        return True

    for hint in ANSWER_META_NOISE_HINTS:
        if line_n == hint:
            return True

    if "2026년" in line_n and ("수신됨" in line_n or "전송됨" in line_n):
        return True
    if _KOREAN_DATE_RE.search(line_n) and ("수신됨" in line_n or "전송됨" in line_n):
        return True
    if line_n in ("삼성닷컴 AI", "Samsung AI CS Chat", "고객지원이 필요하신가요?"):
        return True
    if _normalize_text(line_n) in {"수신됨", "전송됨", "첨부", "더보기"}:
        return True
    if _KOREAN_TIME_RE.fullmatch(line_n) or _EN_TIME_RE.fullmatch(line_n):
        return True

    return False


def _strip_followup_suggestions(text: str) -> str:
    text_n = _normalize_answer_text(text)
    if not text_n:
        return ""

    for hint in ANSWER_CUTOFF_HINTS:
        idx = text_n.find(hint)
        if idx >= 0:
            text_n = text_n[:idx].strip()

    filtered_lines = []
    for line in text_n.splitlines():
        line_n = line.strip()
        if not line_n:
            continue
        if line_n in ANSWER_SUGGESTION_LINE_HINTS:
            continue
        filtered_lines.append(line_n)

    return "\n".join(filtered_lines).strip()


def _is_loading_answer_text(text: str) -> bool:
    text_n = _normalize_answer_text(text)
    if not text_n:
        return False
    lowered = text_n.lower()
    if not any(hint in lowered for hint in LOADING_TEXT_HINTS):
        return False
    if any(hint in text_n for hint in MEANINGFUL_ANSWER_HINTS):
        return False
    if len(text_n) > 120 and _looks_like_main_answer_shape(text_n):
        return False
    return True


def _looks_like_main_answer_shape(text: str) -> bool:
    if not text:
        return False
    if len(text) < MIN_MAIN_ANSWER_LEN:
        return False
    if "\n" not in text and text.endswith("?"):
        return False
    if "\n" not in text and text.endswith("요?"):
        return False
    return True


def _clean_bot_answer_candidate_details(
    text: str,
    question: str = "",
    baseline_last_answer: str = "",
    baseline_topic_family: str = "unknown",
) -> dict[str, Any]:
    text_n = _strip_answer_meta_prefixes(text)
    preserve_loading_prefix = text_n.startswith("답변 생성 중") and len(text_n) >= 80
    runtime = _RUNTIME
    if runtime is not None:
        runtime.logger.info("[ANSWER_EXTRACT][CLEAN_BEFORE] %s", text_n)
    if not text_n:
        return {
            "clean": "",
            "removed_followups": False,
            "noise_lines_removed": 0,
            "cta_stripped": False,
            "promo_stripped": False,
            "truncated_detected": False,
            "question_repetition_detected": False,
        }
    dom_details = _dom_clean_answer_candidate_details(
        text_n,
        question=question,
        baseline_last_answer=baseline_last_answer,
        baseline_topic_family=baseline_topic_family,
    )
    stripped = dom_details["cleaned_answer"]
    if preserve_loading_prefix and stripped and not stripped.startswith("답변 생성 중"):
        stripped = text_n
    noise_lines_removed = 0
    for line in text_n.splitlines():
        if _is_noise_line(line):
            noise_lines_removed += 1
    if _is_followup_question_chip(stripped):
        stripped = ""
    if _is_loading_answer_text(stripped):
        stripped = ""
    removed_followups = bool(dom_details.get("cta_stripped") or dom_details.get("promo_stripped"))
    if runtime is not None:
        runtime.logger.info(
            "[ANSWER_EXTRACT][CLEAN_AFTER] removed_followups=%s noise_lines_removed=%s text=%s",
            removed_followups,
            noise_lines_removed,
            stripped,
        )
    return {
        "clean": stripped.strip(),
        "removed_followups": removed_followups,
        "noise_lines_removed": noise_lines_removed,
        "cta_stripped": bool(dom_details.get("cta_stripped", False)),
        "promo_stripped": bool(dom_details.get("promo_stripped", False)),
        "truncated_detected": bool(dom_details.get("truncated_detected", False)),
        "question_repetition_detected": bool(dom_details.get("question_repetition_detected", False)),
    }


def _clean_bot_answer_candidate(text: str) -> str:
    return _clean_bot_answer_candidate_details(text).get("clean", "")


def _looks_like_main_answer(text: str) -> bool:
    text_n = _clean_bot_answer_candidate(text)
    return _looks_like_main_answer_shape(text_n)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        norm = _normalize_answer_text(item)
        if not norm:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        out.append(item)
    return out


def _split_history_fragments(item: str) -> list[str]:
    normalized = _normalize_answer_text(item)
    if not normalized:
        return []
    if " , " not in normalized:
        return [normalized]
    return [part.strip(" ,") for part in normalized.split(" , ") if part.strip(" ,")]


def _matches_question(text: str, question: str) -> bool:
    text_n = _normalize_text(_normalize_answer_text(text))
    question_n = _normalize_text(_normalize_answer_text(question))
    return bool(text_n and question_n and text_n == question_n)


def _is_followup_question_chip(text: str, question: str = "") -> bool:
    text_n = _normalize_answer_text(text)
    if not text_n:
        return False
    if question and _matches_question(text_n, question):
        return False
    if text_n in ANSWER_SUGGESTION_LINE_HINTS:
        return True
    if len(text_n) > 80:
        return False
    return text_n.endswith("?") or text_n.endswith("요?")


def _focus_message_history(items: list[str], question: str, actual_answer: str) -> list[str]:
    question_n = _normalize_answer_text(question)
    answer_n = _clean_bot_answer_candidate(actual_answer)
    if question_n and answer_n:
        return [question_n, answer_n]

    if not items:
        return []

    if question_n:
        for index in range(len(items) - 1, -1, -1):
            if _matches_question(items[index], question_n):
                tail = items[index:]
                focused = [question_n]
                for item in tail:
                    item_n = _normalize_answer_text(item)
                    if not item_n or _matches_question(item_n, question_n):
                        continue
                    if _is_followup_question_chip(item_n, question_n):
                        continue
                    focused.append(item_n)
                return _dedupe_preserve_order(focused)

    return items


def _clean_message_history(items: list[str], question: str = "", actual_answer: str = "") -> tuple[list[str], int]:
    cleaned_items: list[str] = []
    noise_removed = 0
    for item in items:
        for fragment in _split_history_fragments(item):
            normalized = _normalize_answer_text(fragment)
            if not normalized:
                continue
            if any(hint in normalized for hint in HISTORY_ALWAYS_DROP_HINTS):
                noise_removed += 1
                continue
            details = _clean_bot_answer_candidate_details(normalized)
            clean = details["clean"]
            if clean:
                if any(hint in clean for hint in HISTORY_ALWAYS_DROP_HINTS):
                    noise_removed += 1
                    continue
                if _is_followup_question_chip(clean, question):
                    continue
                cleaned_items.append(clean)
                noise_removed += int(details["noise_lines_removed"] or 0)
                continue
            if _is_noise_line(normalized):
                noise_removed += 1
    deduped = _dedupe_preserve_order(cleaned_items)
    focused = _focus_message_history(deduped, question, actual_answer)
    runtime = _RUNTIME
    if runtime is not None:
        runtime.logger.info("[HISTORY][NOISE_REMOVED] count=%s", noise_removed)
        runtime.logger.info("[HISTORY][DEDUPED] before=%s after=%s", len(cleaned_items), len(deduped))
        runtime.logger.info("[HISTORY][FOCUSED] before=%s after=%s", len(deduped), len(focused))
    return focused, noise_removed


def _extract_last_bot_message_locator(context: ResolvedChatContext) -> Locator | None:
    candidates = context.bot_message_candidates or BOT_MESSAGE_CANDIDATES
    for candidate in candidates:
        try:
            locator = build_locator(context.scope, candidate)
            count = locator.count()
        except Exception:
            continue
        for index in range(min(count, 20) - 1, -1, -1):
            current = locator.nth(index)
            try:
                if current.is_visible(timeout=300):
                    return current
            except Exception:
                continue
    return None


def extract_last_answer(context: ResolvedChatContext, question: str = "") -> dict[str, Any]:
    candidate_texts: list[str] = []
    last_bot_node = _extract_last_bot_message_locator(context)
    runtime = _runtime()

    if last_bot_node is not None:
        try:
            inner_blocks = last_bot_node.locator("p, div, span")
            block_count = min(inner_blocks.count(), 50)
        except Exception:
            block_count = 0
        for index in range(block_count):
            block = inner_blocks.nth(index)
            try:
                role = (block.get_attribute("role") or "").strip().lower()
            except Exception:
                role = ""
            if role == "button":
                continue
            try:
                tag_name = str(block.evaluate("el => (el.tagName || '').toLowerCase()"))
            except Exception:
                tag_name = ""
            if tag_name == "button":
                continue
            try:
                text = _normalize_answer_text(block.inner_text(timeout=1000))
            except Exception:
                continue
            if text:
                candidate_texts.append(text)

        try:
            bubble_text = _normalize_answer_text(last_bot_node.inner_text(timeout=2000))
            if bubble_text:
                candidate_texts.append(bubble_text)
        except Exception:
            pass

    cleaned: list[tuple[str, str, dict[str, Any]]] = []
    for raw in candidate_texts:
        details = _clean_bot_answer_candidate_details(raw)
        cleaned_text = details["clean"]
        if not cleaned_text or _is_followup_question_chip(cleaned_text, question):
            continue
        if not _has_minimal_question_alignment(question, cleaned_text):
            continue
        if _dom_is_stale_or_invalid_candidate(
            question,
            raw,
            cleaned_text,
            baseline_last_answer=context.baseline_last_answer,
            baseline_topic_family=context.baseline_topic_family,
        ):
            continue
        if _dom_looks_truncated(cleaned_text):
            continue
        if _dom_is_question_repetition(question, cleaned_text):
            continue
        if cleaned_text:
            cleaned.append((raw, cleaned_text, details))

    main_candidates = [item for item in cleaned if _looks_like_main_answer(item[1])]
    if main_candidates:
        main_candidates.sort(key=lambda item: len(item[1]), reverse=True)
        selected_raw, selected_clean, details = main_candidates[0]
        runtime.logger.info("[ANSWER_EXTRACT][MAIN_SELECTED] len=%s", len(selected_clean))
        return {
            "actual_answer": selected_clean,
            "actual_answer_clean": selected_clean,
            "answer_raw": selected_raw,
            "extraction_source": "dom_main_answer",
            "removed_followups": bool(details.get("removed_followups", False)),
            "noise_lines_removed": int(details.get("noise_lines_removed", 0) or 0),
        }

    if cleaned:
        cleaned.sort(key=lambda item: len(item[1]), reverse=True)
        selected_raw, selected_clean, details = cleaned[0]
        runtime.logger.warning("[ANSWER_EXTRACT][FALLBACK_SELECTED] len=%s", len(selected_clean))
        return {
            "actual_answer": selected_clean,
            "actual_answer_clean": selected_clean,
            "answer_raw": selected_raw,
            "extraction_source": "dom_fallback_cleaned",
            "removed_followups": bool(details.get("removed_followups", False)),
            "noise_lines_removed": int(details.get("noise_lines_removed", 0) or 0),
        }

    runtime.logger.warning("[ANSWER_EXTRACT][EMPTY]")
    return {
        "actual_answer": "",
        "actual_answer_clean": "",
        "answer_raw": "",
        "extraction_source": "unknown",
        "removed_followups": False,
        "noise_lines_removed": 0,
    }


def _select_report_answer(
    wait_answer: str,
    dom_answer: str,
    has_verified_response: bool,
    question: str = "",
    baseline_last_answer: str = "",
    baseline_topic_family: str = "unknown",
) -> str:
    """Prefer the verified cleaned answer over weaker DOM payload text."""

    def validate_candidate(raw_text: str) -> str:
        details = _clean_bot_answer_candidate_details(raw_text)
        clean_text = details["clean"]
        if not clean_text:
            return ""
        if looks_like_chat_history_dump(clean_text) or looks_like_chat_history_dump(raw_text):
            return ""
        if question:
            raw_normalized = _normalize_answer_text(raw_text)
            if details.get("question_repetition_detected"):
                return ""
            if details.get("truncated_detected"):
                return ""
            if _dom_looks_truncated(raw_normalized):
                return ""
            if _dom_is_question_repetition(question, clean_text):
                return ""
            if _dom_looks_truncated(clean_text):
                return ""
            if not _has_minimal_question_alignment(question, clean_text):
                return ""
            specific_keywords = [
                keyword
                for keyword in _extract_alignment_keywords(question)
                if keyword not in {"갤럭시", "삼성", "프로", "울트라", "플러스", "plus", "pro", "ultra"}
            ]
            lowered_clean = clean_text.lower()
            if specific_keywords and not any(keyword in lowered_clean for keyword in specific_keywords):
                return ""
            question_family = _dom_detect_topic_family(question)
            answer_family = _dom_detect_topic_family(clean_text)
            if question_family != "unknown" and answer_family != "unknown" and question_family != answer_family:
                return ""
            if _dom_is_stale_or_invalid_candidate(
                question,
                raw_text,
                clean_text,
                baseline_last_answer=baseline_last_answer,
                baseline_topic_family=baseline_topic_family,
            ):
                return ""
            baseline_clean = _clean_bot_answer_candidate(baseline_last_answer)
            first_sentence = clean_text.split(".", 1)[0].strip()
            if (
                baseline_clean
                and normalize_text_for_diff(baseline_clean) in normalize_text_for_diff(clean_text)
                and re.search(r"알려주(?:세요|어|실래요)|비교해|비교해 주세요|정리해", first_sentence)
            ):
                return ""
        return clean_text

    wait_clean = validate_candidate(wait_answer)
    dom_clean = validate_candidate(dom_answer)

    if has_verified_response and _looks_like_main_answer(wait_clean):
        return wait_clean
    if _looks_like_main_answer(dom_clean):
        return dom_clean
    if has_verified_response and wait_clean and not _is_followup_question_chip(wait_clean):
        return wait_clean
    if dom_clean and not _is_followup_question_chip(dom_clean):
        return dom_clean
    return wait_clean


def _recover_dom_response_candidate(
    question: str,
    dom_answer: str,
    last_answer_payload: dict[str, Any],
    message_history: list[str],
) -> dict[str, Any]:
    candidates: list[dict[str, str]] = []

    def add_candidate(raw_text: str, clean_text: str, source: str) -> None:
        raw_n = _normalize_answer_text(raw_text)
        clean_n = _clean_bot_answer_candidate(clean_text or raw_text)
        if looks_like_chat_history_dump(raw_n) or looks_like_chat_history_dump(clean_n):
            return
        if not raw_n or not clean_n or not _looks_like_main_answer(clean_n):
            return
        candidates.append(
            {
                "answer_raw": raw_n,
                "actual_answer": clean_n,
                "actual_answer_clean": clean_n,
                "source": source,
            }
        )

    add_candidate(
        str(last_answer_payload.get("answer_raw") or ""),
        str(last_answer_payload.get("actual_answer_clean") or last_answer_payload.get("actual_answer") or ""),
        str(last_answer_payload.get("extraction_source") or "dom_last_answer_recovered"),
    )
    add_candidate(dom_answer, dom_answer, "dom_payload_recovered")

    focused_history = _focus_message_history(message_history, question, "")
    for item in focused_history:
        if question and _matches_question(item, question):
            continue
        add_candidate(item, item, "message_history_recovered")

    if not candidates:
        return {
            "detected": False,
            "answer_raw": "",
            "actual_answer": "",
            "actual_answer_clean": "",
            "source": "unknown",
        }

    selected = max(candidates, key=lambda item: len(item["actual_answer_clean"]))
    selected["detected"] = True
    return selected


def _clear_unverified_answer_fields() -> dict[str, Any]:
    return {
        "answer": "",
        "answer_raw": "",
        "answer_normalized": "",
        "actual_answer": "",
        "actual_answer_clean": "",
        "extraction_source": "unknown",
        "extraction_source_detail": "no_verified_answer",
        "extraction_confidence": 0.0,
        "removed_followups": False,
        "noise_lines_removed": 0,
    }


def _contains_baseline_menu(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(menu_text in normalized for menu_text in BASELINE_MENU_TEXTS)


def capture_baseline_bot_snapshot(context: ResolvedChatContext) -> list[str]:
    """Capture the baseline bot text snapshot before a question is submitted."""

    baseline_messages = extract_bot_message_texts(context)
    context.baseline_bot_messages = baseline_messages
    context.baseline_bot_count = len(baseline_messages)
    context.baseline_last_answer = baseline_messages[-1] if baseline_messages else ""
    context.baseline_topic_family = _dom_detect_topic_family(context.baseline_last_answer)
    _runtime().logger.info("[ANSWER] baseline bot count: %s", context.baseline_bot_count)
    _runtime().logger.info("[ANSWER] baseline bot texts count: %s", len(context.baseline_bot_messages))
    return baseline_messages


def detect_new_bot_text(context: ResolvedChatContext, baseline_texts: list[str]) -> str:
    """Detect newly appeared bot text that was not present in the baseline snapshot."""

    baseline_normalized = {_normalize_text(item) for item in baseline_texts}
    for message in extract_bot_message_texts(context):
        normalized = _normalize_text(message)
        if not normalized:
            continue
        if normalized in baseline_normalized:
            continue
        if is_initial_menu_text(normalized):
            continue
        return message
    return ""


def _is_new_response_candidate(text: str, baseline_messages: list[str]) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    if _contains_baseline_menu(normalized):
        return False
    if normalized in {_normalize_text(item) for item in baseline_messages}:
        return False
    return True


def verify_user_echo(context: ResolvedChatContext, question: str) -> bool:
    logger = _runtime().logger
    scope = context.scope
    question_norm = " ".join(question.strip().split())

    for candidate in USER_MESSAGE_CANDIDATES:
        try:
            locator = build_locator(scope, candidate)
            for index in range(locator.count()):
                text = " ".join((locator.nth(index).inner_text(timeout=1000) or "").split())
                if question_norm and question_norm in text:
                    logger.info("[INPUT_V2][ECHO][FOUND]")
                    return True
        except Exception:
            continue

    for text in extract_message_history_candidates(context):
        if question_norm and question_norm in " ".join(text.split()):
            logger.info("[INPUT_V2][ECHO][FOUND]")
            return True

    visible_text = extract_visible_chat_text(context)
    if visible_text and question_norm in " ".join(str(visible_text).split()):
        logger.info("[INPUT_V2][ECHO][FOUND]")
        return True

    try:
        full_text = scope.evaluate(
            "() => { const el = document.body || document.documentElement; return el ? (el.innerText || el.textContent || '') : ''; }"
        )
        if full_text and question_norm in " ".join(str(full_text).split()):
            logger.info("[INPUT_V2][ECHO][FOUND]")
            return True
    except Exception:
        pass

    logger.info("[INPUT_V2][ECHO][NOT_FOUND]")
    return False


def verify_user_message_echo(context: ResolvedChatContext, question: str, logger: Any) -> bool:
    return verify_user_echo(context, question)


def _detect_login_gate(context: ResolvedChatContext) -> dict[str, Any]:
    logger = _runtime().logger
    scope = context.scope
    try:
        payload = scope.evaluate(
                        r"""
            () => {
              const text = (document.body?.innerText || document.documentElement?.innerText || '').replace(/\s+/g, ' ').trim();
              const buttons = Array.from(document.querySelectorAll('button, [role="button"]')).map((el) => ({
                text: (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim(),
                aria: (el.getAttribute('aria-label') || '').trim(),
                disabled: !!el.disabled || (el.getAttribute('aria-disabled') || '').toLowerCase() === 'true',
              }));
              return { text, buttons };
            }
            """
        )
    except Exception as exc:
        logger.debug("[INPUT][LOGIN_GATE] probe failed: %s", exc)
        return {"login_required": False, "reason": "", "button_text": ""}

    visible_text = _norm_text(str(payload.get("text") or ""))
    buttons = payload.get("buttons") or []
    button_text = ""
    for item in buttons:
        combined = _norm_text(f"{item.get('text', '')} {item.get('aria', '')}")
        if any(hint in combined for hint in LOGIN_REQUIRED_HINTS):
            button_text = combined
            break

    login_required = any(hint in visible_text for hint in LOGIN_REQUIRED_HINTS) or bool(button_text)
    if not login_required:
        return {"login_required": False, "reason": "", "button_text": ""}

    logger.info("[INPUT][LOGIN_GATE] detected button=%r text=%r", button_text, visible_text[:200])
    return {
        "login_required": True,
        "reason": "Chat requires Samsung account login before composer becomes available",
        "button_text": button_text,
    }


def find_chat_container(page: Page) -> Locator | None:
    """Find the visible chat container in the page or in a nested iframe."""

    for _, scope in _iter_scopes(page):
        container_locator, _ = first_visible_locator(scope, CONTAINER_CANDIDATES, timeout_ms=1500)
        if container_locator is not None:
            return container_locator
    return None


def find_input_locator(context: Page | Frame | ResolvedChatContext) -> Locator | None:
    """Find the visible input locator from a page, frame, or resolved chat context."""

    if isinstance(context, ResolvedChatContext):
        return context.input_locator
    input_locator, _ = first_visible_locator(context, INPUT_CANDIDATES, timeout_ms=1500)
    return input_locator


def find_send_button(context: Page | Frame | ResolvedChatContext) -> Locator | None:
    """Find the send button from a page, frame, or resolved chat context."""

    if isinstance(context, ResolvedChatContext):
        return context.send_locator
    send_locator, _ = first_visible_locator(context, SEND_BUTTON_CANDIDATES, timeout_ms=1200)
    return send_locator


def _try_fill(locator: Locator, question: str, input_type: str, logger: Any) -> bool:
    try:
        locator.fill(question, timeout=2500)
        if verify_input_text(locator, question, input_type):
            logger.info("[INPUT] fill attempt success")
            return True
        logger.warning("[INPUT] fill failed: empty or mismatched after fill")
        return False
    except Exception as exc:
        logger.warning("[INPUT] fill attempt failed: %s", exc)
        return False


def _try_press_sequentially(locator: Locator, question: str, input_type: str, logger: Any) -> bool:
    try:
        locator.press_sequentially(question, delay=30)
        if verify_input_text(locator, question, input_type):
            logger.info("[INPUT] press_sequentially success")
            return True
        logger.warning("[INPUT] press_sequentially failed: verification failed")
        return False
    except Exception as exc:
        logger.warning("[INPUT] press_sequentially attempt failed: %s", exc)
        return False


def _try_keyboard_type(
    scope: Page | Frame,
    locator: Locator,
    question: str,
    input_type: str,
    logger: Any,
) -> bool:
    try:
        locator.click(timeout=1500)
        if hasattr(scope, "keyboard"):
            scope.keyboard.type(question, delay=20)
        else:
            locator.press_sequentially(question, delay=20)
        if verify_input_text(locator, question, input_type):
            logger.info("[INPUT] keyboard.type attempt success")
            return True
        logger.warning("[INPUT] keyboard.type failed: verification failed")
        return False
    except Exception as exc:
        logger.warning("[INPUT] keyboard.type attempt failed: %s", exc)
        return False


def _try_js_fallback(locator: Locator, question: str, input_type: str, logger: Any) -> bool:
    logger.warning("[INPUT] JS fallback used")
    try:
        if not _input_is_editable(locator):
            logger.warning("[INPUT] JS fallback blocked because input is not editable")
            return False
        if input_type in ("input", "textarea"):
            locator.evaluate(
                "(el, v) => { el.value = v;"
                " el.dispatchEvent(new Event('input', {bubbles: true}));"
                " el.dispatchEvent(new Event('change', {bubbles: true})); }",
                question,
            )
        else:
            locator.evaluate(
                "(el, v) => { el.textContent = v;"
                " el.dispatchEvent(new Event('input', {bubbles: true}));"
                " el.dispatchEvent(new Event('change', {bubbles: true})); }",
                question,
            )
        if verify_input_text(locator, question, input_type):
            logger.info("[INPUT] JS fallback success")
            return True
        logger.warning("[INPUT] JS fallback failed: verification failed")
        return False
    except Exception as exc:
        logger.warning("[INPUT] JS fallback failed: %s", exc)
        return False


def enter_question_with_verification(
    scope: Page | Frame,
    input_locator: Locator,
    question: str,
    logger: Any,
    use_extended_fallbacks: bool = True,
) -> tuple[bool, str, Locator, str]:
    """Try multiple strategies to type *question* and verify it was accepted.

    Returns ``(input_verified, method_used)`` where *method_used* is one of
    ``"fill"``, ``"keyboard.type"``, ``"press_sequentially"``, ``"js_fallback"`` or ``""`` when all
    strategies fail.
    """

    input_type = _detect_input_type(input_locator)
    logger.info("[INPUT] locator found via resolved context")
    scope_name = getattr(scope, "name", None) or getattr(scope, "url", None) or type(scope).__name__
    logger.info("[INPUT] input scope: %s", scope_name)
    logger.info("[INPUT] detected type: %s", input_type)

    effective_locator = input_locator
    effective_selector = ""

    if not _input_is_editable(effective_locator):
        logger.info("[INPUT] locator is not editable; attempting focus-proxy resolution")
        _focus_input(effective_locator, logger)
        proxy_locator, proxy_selector = _resolve_focus_proxy_candidate(scope, effective_locator, logger)
        if proxy_locator is None:
            logger.warning("[INPUT] input is not editable; aborting entry attempts")
            return False, "", effective_locator, effective_selector
        effective_locator = proxy_locator
        effective_selector = proxy_selector
        input_type = _detect_input_type(effective_locator)
        logger.info("[INPUT] focus-proxy selected selector=%s type=%s", effective_selector or "(unknown)", input_type)
        if not _input_is_editable(effective_locator):
            logger.warning("[INPUT] focus-proxy target is still not editable")
            return False, "", effective_locator, effective_selector

    _focus_input(effective_locator, logger)
    _clear_input(effective_locator, input_type)

    if _try_fill(effective_locator, question, input_type, logger):
        return True, "fill", effective_locator, effective_selector

    _clear_input(effective_locator, input_type)
    _focus_input(effective_locator, logger)

    if _try_keyboard_type(scope, effective_locator, question, input_type, logger):
        return True, "keyboard.type", effective_locator, effective_selector

    if not use_extended_fallbacks:
        logger.info("[INPUT] extended fallback disabled for lean path")
        return False, "", effective_locator, effective_selector

    _clear_input(effective_locator, input_type)
    _focus_input(effective_locator, logger)

    if _try_press_sequentially(effective_locator, question, input_type, logger):
        return True, "press_sequentially", effective_locator, effective_selector

    _clear_input(effective_locator, input_type)
    _focus_input(effective_locator, logger)

    if _try_js_fallback(effective_locator, question, input_type, logger):
        return True, "js_fallback", effective_locator, effective_selector

    logger.error("[INPUT] all strategies failed for question: %.60s", question)
    return False, "", effective_locator, effective_selector


def capture_baseline_state(context: ResolvedChatContext) -> dict[str, Any]:
    """Capture the pre-submit bot-message baseline used for strict answer detection."""

    capture_baseline_bot_snapshot(context)
    structured_history = extract_structured_message_history(context)
    context.baseline_history = structured_history.get("history", [])
    context.baseline_visible_text = extract_visible_chat_text(context)
    context.baseline_visible_blocks = extract_visible_text_blocks(context)
    context.baseline_message_nodes_snapshot = extract_message_history_candidates(context)
    context.baseline_send_button_enabled = _is_send_button_enabled(context.send_locator)
    _runtime().logger.info("[ANSWER] baseline visible text length: %s", len(context.baseline_visible_text))
    _runtime().logger.info("[HISTORY] visible text block count: %s", len(context.baseline_visible_blocks))
    _runtime().logger.info("[HISTORY] structured message history count: %s", len(context.baseline_history))
    _runtime().logger.info("[ANSWER] baseline message nodes snapshot count: %s", len(context.baseline_message_nodes_snapshot))
    return {
        "baseline_bot_count": context.baseline_bot_count,
        "baseline_bot_messages": list(context.baseline_bot_messages),
        "baseline_history": list(context.baseline_history),
        "baseline_visible_text": context.baseline_visible_text,
        "baseline_message_nodes_snapshot": list(context.baseline_message_nodes_snapshot),
        "baseline_send_button_enabled": context.baseline_send_button_enabled,
    }


def extract_last_new_bot_message(context: ResolvedChatContext) -> str:
    """Return the latest post-baseline bot message that is not menu text."""

    bot_messages = extract_bot_message_texts(context)
    current_count = len(bot_messages)
    if current_count <= context.baseline_bot_count:
        return ""
    new_messages = bot_messages[context.baseline_bot_count:current_count]
    candidates = [
        message for message in new_messages if _is_new_response_candidate(message, context.baseline_bot_messages)
    ]
    return candidates[-1] if candidates else ""


def _capture_stage(
    page: Page,
    context: ResolvedChatContext | None,
    case_id: str,
    timestamp: str,
    stage: str,
    config: AppConfig,
    logger: Any,
    case_failed: bool = False,
) -> tuple[str, str]:
    """Capture fullpage + chatbox screenshots for a named stage.

    Returns ``(fullpage_path, chatbox_path)`` strings (empty on failure).
    """

    safe_id = sanitize_filename(case_id)
    fullpage_path = config.fullpage_dir / f"{timestamp}_{safe_id}_{stage}.png"
    chatbox_path = config.chatbox_dir / f"{timestamp}_{safe_id}_{stage}.png"

    fp_str = ""
    cb_str = ""

    if not _should_capture_fullpage(case_failed=case_failed, config=config) and not _should_capture_chatbox(stage, case_failed=case_failed, config=config):
        return "", ""

    if _should_capture_fullpage(case_failed=case_failed, config=config):
        try:
            page.screenshot(path=str(fullpage_path), full_page=True)
            fp_str = str(fullpage_path)
            _register_screenshot_capture()
        except Exception as exc:
            logger.warning("stage %s fullpage screenshot failed: %s", stage, exc)

    if _should_capture_chatbox(stage, case_failed=case_failed, config=config):
        try:
            if context is not None and context.container_locator is not None:
                context.container_locator.screenshot(path=str(chatbox_path))
            elif context is not None and context.input_locator is not None:
                context.input_locator.screenshot(path=str(chatbox_path))
            else:
                page.screenshot(path=str(chatbox_path))
            cb_str = str(chatbox_path)
            _register_screenshot_capture()
        except Exception as exc:
            logger.warning("stage %s chatbox screenshot failed: %s", stage, exc)

    if cb_str:
        logger.info("[ARTIFACT][SAVE] stage=%s path=%s", stage, cb_str)
    if fp_str:
        logger.info("[ARTIFACT][SAVE] stage=%s path=%s", stage, fp_str)

    return fp_str, cb_str


def capture_named_artifact(
    page: Page,
    context: ResolvedChatContext | None,
    case_id: str,
    stage: str,
    config: AppConfig,
    case_failed: bool = False,
) -> tuple[str, str]:
    runtime = _runtime()
    if not _should_capture_stage(stage, case_failed=case_failed, config=config):
        return "", ""

    if stage == "opened_footer" and context is not None and context.input_locator is not None:
        safe_id = sanitize_filename(case_id)
        chatbox_path = config.chatbox_dir / f"{runtime.current_case_timestamp}_{safe_id}_{stage}.png"
        fullpage_path = config.fullpage_dir / f"{runtime.current_case_timestamp}_{safe_id}_{stage}.png"
        target = context.input_locator
        try:
            target = context.input_locator.locator(
                "xpath=ancestor-or-self::*[self::footer or self::form or contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'footer') or contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'composer') or contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'input')][1]"
            ).first
        except Exception:
            target = context.input_locator
        fp_str = ""
        cb_str = ""
        if _should_capture_fullpage(case_failed=case_failed, config=config):
            try:
                page.screenshot(path=str(fullpage_path), full_page=True)
                fp_str = str(fullpage_path)
                _register_screenshot_capture()
                runtime.logger.info("[ARTIFACT][SAVE] stage=%s path=%s", stage, fp_str)
            except Exception:
                pass
        if _should_capture_chatbox(stage, case_failed=case_failed, config=config):
            try:
                target.screenshot(path=str(chatbox_path))
                cb_str = str(chatbox_path)
                _register_screenshot_capture()
                runtime.logger.info("[ARTIFACT][SAVE] stage=%s path=%s", stage, cb_str)
            except Exception:
                pass
        return fp_str, cb_str

    return _capture_stage(
        page,
        context,
        case_id,
        runtime.current_case_timestamp,
        stage,
        config,
        runtime.logger,
        case_failed=case_failed,
    )


def _capture_answer_screenshots(
    page: Page,
    context: ResolvedChatContext,
    case_id: str,
    timestamp: str,
    config: AppConfig,
    logger: Any,
) -> tuple[list[str], str, str, bool]:
    chat_paths: list[str] = []
    multi_page = False
    last_fullpage_path = ""
    last_chatbox_path = ""

    scroll_metrics = {"scrollHeight": 0, "clientHeight": 0, "scrollTop": 0}
    if context.container_locator is not None:
        try:
            scroll_metrics = context.container_locator.evaluate(
                "el => ({scrollHeight: el.scrollHeight || 0, clientHeight: el.clientHeight || 0, scrollTop: el.scrollTop || 0})"
            )
        except Exception:
            scroll_metrics = {"scrollHeight": 0, "clientHeight": 0, "scrollTop": 0}

    scroll_height = int(scroll_metrics.get("scrollHeight", 0) or 0)
    client_height = int(scroll_metrics.get("clientHeight", 0) or 0)
    max_parts = 4
    if client_height > 0 and scroll_height > client_height + 32:
        multi_page = True
        for part_index in range(max_parts):
            stage = f"after_answer_part_{part_index + 1:02d}"
            fullpage_path, chatbox_path = _capture_stage(page, context, case_id, timestamp, stage, config, logger)
            if chatbox_path:
                chat_paths.append(chatbox_path)
            if fullpage_path:
                last_fullpage_path = fullpage_path
            if chatbox_path:
                last_chatbox_path = chatbox_path
            try:
                if context.container_locator is not None:
                    state = context.container_locator.evaluate(
                        "(el, height) => {"
                        "  const nextTop = Math.min(el.scrollTop + height, Math.max(el.scrollHeight - el.clientHeight, 0));"
                        "  el.scrollTop = nextTop;"
                        "  return {scrollTop: el.scrollTop || 0, atEnd: nextTop >= Math.max(el.scrollHeight - el.clientHeight, 0)};"
                        "}",
                        max(client_height - 40, 120),
                    )
                    if state.get("atEnd"):
                        break
            except Exception:
                break
        final_fullpage_path, final_chatbox_path = _capture_stage(
            page,
            context,
            case_id,
            timestamp,
            "after_answer_final",
            config,
            logger,
        )
        if final_chatbox_path:
            chat_paths.append(final_chatbox_path)
            last_chatbox_path = final_chatbox_path
        if final_fullpage_path:
            last_fullpage_path = final_fullpage_path
        return chat_paths, last_chatbox_path, last_fullpage_path, multi_page

    fullpage_path, chatbox_path = _capture_stage(page, context, case_id, timestamp, "after_answer", config, logger)
    if chatbox_path:
        chat_paths.append(chatbox_path)
        last_chatbox_path = chatbox_path
    if fullpage_path:
        last_fullpage_path = fullpage_path
    return chat_paths, last_chatbox_path, last_fullpage_path, multi_page


def verify_submit_effect(context: ResolvedChatContext, question: str, input_locator: Locator, before_value: str) -> bool:
    """Verify that submitting the question had a real effect on the chat UI."""

    runtime = _runtime()
    input_type = detect_input_kind(input_locator)
    after_value = _read_input_value(input_locator, input_type)
    input_cleared = bool(before_value.strip()) and after_value == "" and after_value != before_value
    runtime.logger.info("[SUBMIT] after_send input value: %s", after_value)
    runtime.logger.info("[SUBMIT] input cleared %s", input_cleared)

    history_after = extract_message_history_candidates(context)
    history_count_changed = len(history_after) > len(context.baseline_history)
    history_contains_question = any(_normalize_text(question) in _normalize_text(item) for item in history_after)
    visible_text = extract_visible_chat_text(context)
    visible_text_changed = _normalize_text(visible_text) != _normalize_text(context.baseline_visible_text)
    visible_contains_question = _normalize_text(question) in _normalize_text(visible_text)
    user_echo = verify_user_message_echo(context, question, runtime.logger)
    send_button_enabled_after = _is_send_button_enabled(context.send_locator)
    send_button_state_changed = send_button_enabled_after != context.baseline_send_button_enabled

    runtime.logger.info("[HISTORY] history extracted count: %s", len(history_after))
    runtime.logger.info("[SUBMIT] history changed after submit %s", history_count_changed)
    runtime.logger.info("[SUBMIT] user echo verified %s", user_echo)
    runtime.logger.info("[SUBMIT] history count increased %s", history_count_changed)
    runtime.logger.info("[SUBMIT] history contains question %s", history_contains_question)
    runtime.logger.info("[SUBMIT] visible text changed %s", visible_text_changed)
    runtime.logger.info("[SUBMIT] send button state changed %s", send_button_state_changed)

    verified = any(
        [
            input_cleared,
            user_echo,
            history_count_changed,
            history_contains_question,
            send_button_state_changed,
            visible_contains_question and visible_text_changed,
        ]
    )
    runtime.logger.info("[SUBMIT] submit effect verified %s", verified)
    if not verified:
        runtime.logger.warning("[SUBMIT] after_send input value unchanged" if not input_cleared else "[SUBMIT] input cleared true")
        runtime.logger.warning("[SUBMIT] submission effect not verified")
    return verified


def trigger_submit(page: Page, context: ResolvedChatContext, question: str) -> tuple[bool, str, bool, str, str]:
    """Trigger submit using button click first, then Enter, and verify its effect."""

    runtime = _runtime()
    input_locator = context.input_locator
    before_value = _read_input_value(input_locator, detect_input_kind(input_locator))
    runtime.logger.info("[SUBMIT] before_send input value: %s", before_value)
    runtime.logger.info("[SUBMIT] send button found: %s", context.send_locator is not None)

    runtime.logger.info("[SUBMIT] send button enabled before submit: %s", _is_send_button_enabled(context.send_locator))

    methods: list[str] = []
    if context.send_locator is not None:
        methods.append("button_click")
    methods.extend(["enter_input", "enter_active_element", "enter_page"])

    for method_name in methods:
        runtime.logger.info("[SUBMIT] submit method attempted: %s", method_name)
        try:
            if method_name == "button_click" and context.send_locator is not None:
                context.send_locator.click(timeout=2500)
                runtime.logger.info("[SUBMIT] send click attempted")
            elif method_name == "enter_input":
                input_locator.click(timeout=1500)
                input_locator.press("Enter")
                runtime.logger.info("[SUBMIT] Enter attempted on input locator")
            elif method_name == "enter_active_element":
                active_entered = context.scope.evaluate(
                    "() => {"
                    "  const el = document.activeElement;"
                    "  if (!el) return false;"
                    "  el.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));"
                    "  el.dispatchEvent(new KeyboardEvent('keypress', {key: 'Enter', bubbles: true}));"
                    "  el.dispatchEvent(new KeyboardEvent('keyup', {key: 'Enter', bubbles: true}));"
                    "  return true;"
                    "}"
                )
                if not active_entered:
                    raise RuntimeError("active element not available")
                runtime.logger.info("[SUBMIT] Enter attempted on active element")
            else:
                page.keyboard.press("Enter")
                runtime.logger.info("[SUBMIT] Enter attempted on page")
        except Exception as exc:
            runtime.logger.warning("[SUBMIT] %s failed: %s", method_name, exc)
            continue

        after_send_fullpage, after_send_chatbox = _capture_stage(
            page,
            context,
            runtime.current_case_id,
            runtime.current_case_timestamp,
            "after_send",
            runtime.config,
            runtime.logger,
        )

        try:
            if hasattr(context.scope, "wait_for_timeout"):
                context.scope.wait_for_timeout(ECHO_RENDER_DELAY_MS)
            else:
                time.sleep(ECHO_RENDER_DELAY_SEC)
        except Exception:
            pass

        submit_effect_verified = verify_submit_effect(context, question, input_locator, before_value)
        user_echo_verified = verify_user_message_echo(context, question, runtime.logger)
        runtime.logger.info("[SUBMIT] submit method used: %s", method_name)
        if submit_effect_verified:
            return True, method_name, user_echo_verified, after_send_chatbox, after_send_fullpage

    return False, "unknown", False, "", ""


def submit_question(
    page: Page,
    context: ResolvedChatContext,
    question: str,
    ready_candidate: dict[str, Any] | None = None,
    ready_wait_result: dict[str, Any] | None = None,
) -> SubmissionEvidence:
    """Submit a question using only verified ready chat-input candidates."""

    runtime = _runtime()
    capture_baseline_state(context)
    ranked_candidates = _collect_chat_input_candidates(context)
    if not ranked_candidates:
        ranked_candidates = collect_ranked_input_candidates(context, preferred_scope=context.scope_name)
    if ready_candidate is not None:
        ranked_candidates = [ready_candidate, *[candidate for candidate in ranked_candidates if candidate != ready_candidate]]
    allowed_candidates = [candidate for candidate in ranked_candidates if _is_ready_candidate(candidate)]
    top_candidate_disabled = _candidate_is_disabled_like(ranked_candidates[0] if ranked_candidates else None)
    top_candidate_placeholder, top_candidate_aria = _top_candidate_texts(ranked_candidates)
    editable_candidates_count = len(allowed_candidates)
    max_candidates = max(1, runtime.config.rubicon_max_input_candidates)
    ready_state = ready_wait_result or {}

    result = SubmissionEvidence(
        input_dom_verified=False,
        submit_effect_verified=False,
        input_verified=False,
        input_method_used="",
        submit_method_used="unknown",
        input_scope="",
        input_selector="",
        input_candidate_score=0.0,
        top_candidate_disabled=top_candidate_disabled,
        top_candidate_placeholder=top_candidate_placeholder,
        top_candidate_aria=top_candidate_aria,
        input_ready_wait_attempted=bool(ready_wait_result is not None),
        input_ready_wait_result=str(ready_state.get("result", "") or "not_attempted"),
        transition_wait_attempted=bool(ready_wait_result is not None),
        transition_ready=bool(ready_state.get("ready", False)),
        transition_timeout=bool(ready_state.get("timeout", False)),
        transition_reason="ready" if ready_state.get("ready") else ("timeout" if ready_state.get("timeout") else ""),
        transition_history=json.dumps(ready_state.get("history", []), ensure_ascii=False),
        failover_attempts=0,
        final_input_value_verified=False,
        user_message_echo_verified=False,
        input_failure_category="",
        input_failure_reason="",
        editable_candidates_count=editable_candidates_count,
        final_input_target_frame="",
        input_candidates_debug="\n".join(_candidate_debug_line(candidate) for candidate in ranked_candidates),
        before_send_chatbox_path="",
        before_send_fullpage_path="",
        after_send_chatbox_path="",
        after_send_fullpage_path="",
        capture_reason="",
    )

    login_gate = _detect_login_gate(context)
    if login_gate.get("login_required"):
        result.input_failure_category = "login_required"
        result.input_failure_reason = str(login_gate.get("reason") or "Chat login required")
        result.capture_reason = result.input_failure_reason
        return result

    if ranked_candidates and _is_disabled_transition_candidate(ranked_candidates[0]):
        result.input_failure_category = "composer_transition_timeout"
        result.input_failure_reason = "Input stayed in disabled transition state"
        return result

    if not allowed_candidates:
        result.input_failure_category = "top_candidate_disabled" if top_candidate_disabled else "no_editable_candidate_after_transition"
        result.input_failure_reason = "No ready chat input candidate available"
        return result

    runtime.logger.info(
        "[INPUT][SUBMIT_READY] allowed=%s top=%s",
        len(allowed_candidates),
        ", ".join(f"{item['selector']}:{item.get('placeholder', '')}:{item.get('aria_label', '')}" for item in allowed_candidates[:max_candidates]) or "none",
    )

    last_failure_category = "failover_exhausted"
    last_failure_reason = "No ready candidate accepted the input"

    for rank, candidate in enumerate(allowed_candidates[:max_candidates], start=1):
        runtime.logger.info("[INPUT_V2][FAILOVER][TRY] rank=%s selector=%s", rank, candidate["selector"])
        result.failover_attempts = rank
        result.input_scope = candidate["scope_name"]
        result.input_selector = candidate["selector"]
        result.input_candidate_score = candidate["score"]
        result.final_input_target_frame = candidate["scope_name"]

        context.input_locator = candidate["locator"]
        context.input_scope = candidate["scope"]
        context.input_scope_name = candidate["scope_name"]
        context.input_selector = candidate["selector"]
        context.input_candidate_score = candidate["score"]
        context.send_locator, _ = first_visible_locator(candidate["scope"], SEND_BUTTON_CANDIDATES, timeout_ms=800)
        if context.send_locator is None:
            context.send_locator, _ = first_visible_locator(context.scope, SEND_BUTTON_CANDIDATES, timeout_ms=800)

        input_dom_verified, method_used, effective_locator, effective_selector = enter_question_with_verification(
            candidate["scope"],
            candidate["locator"],
            question,
            runtime.logger,
            use_extended_fallbacks=runtime.config.is_debug_mode or rank > 1,
        )
        if effective_locator is not None:
            context.input_locator = effective_locator
        if effective_selector:
            result.input_selector = effective_selector
            context.input_selector = effective_selector
        input_value_verified = input_dom_verified and verify_input_dom_state(context.input_locator or candidate["locator"], question)
        runtime.logger.info("[INPUT][VALUE_VERIFIED] verified=%s selector=%s", input_value_verified, result.input_selector or candidate["selector"])
        result.input_dom_verified = input_value_verified
        result.final_input_value_verified = input_value_verified
        result.input_method_used = method_used

        if not input_value_verified:
            last_failure_category = "failover_exhausted"
            last_failure_reason = "Input value was not reflected in the candidate"
            continue

        before_send_fullpage, before_send_chatbox = capture_named_artifact(
            page,
            context,
            runtime.current_case_id,
            "before_send",
            runtime.config,
        )
        result.before_send_fullpage_path = before_send_fullpage
        result.before_send_chatbox_path = before_send_chatbox

        submit_effect_verified, submit_method_used, echo_verified, after_send_chatbox, after_send_fullpage = trigger_submit(page, context, question)
        if submit_effect_verified and not echo_verified:
            try:
                context.scope.wait_for_timeout(ECHO_RENDER_DELAY_MS)
            except Exception:
                pass
            echo_verified = verify_user_message_echo(context, question, runtime.logger)
        result.submit_effect_verified = submit_effect_verified
        result.submit_method_used = submit_method_used
        result.user_message_echo_verified = echo_verified
        result.after_send_chatbox_path = after_send_chatbox
        result.after_send_fullpage_path = after_send_fullpage
        result.input_verified = input_value_verified and submit_effect_verified
        runtime.logger.info("[INPUT][ECHO_VERIFIED] verified=%s selector=%s", echo_verified, result.input_selector or candidate["selector"])

        if result.input_verified and echo_verified:
            runtime.logger.info("[INPUT_V2][FAILOVER][SUCCESS] selector=%s method=%s", candidate["selector"], method_used)
            return result

        if result.input_verified and not echo_verified:
            last_failure_category = "user_echo_not_found"
            last_failure_reason = "Question submit effect verified but user echo was not found"
            continue

        last_failure_category = "failover_exhausted"
        last_failure_reason = "Candidate did not produce a verified submit effect"

    runtime.logger.info("[INPUT_V2][FAILOVER][EXHAUSTED]")
    result.input_failure_category = last_failure_category
    result.input_failure_reason = last_failure_reason
    if not result.capture_reason:
        result.capture_reason = last_failure_reason
    return result


def _loading_visible(context: ResolvedChatContext) -> bool:
    for candidate in context.loading_candidates:
        locator = _maybe_visible(context.scope, candidate)
        if locator is not None:
            return True
    return False


def wait_for_answer_completion(context: ResolvedChatContext, question: str = "") -> AnswerWaitResult:
    """Wait until a post-baseline bot answer becomes stable or timeout occurs."""

    runtime = _runtime()
    started = time.perf_counter()
    timeout_sec, stable_target, interval_sec = _answer_wait_settings(runtime.config)
    deadline = started + timeout_sec
    stable_checks = 0
    previous_text = ""
    latest_text = ""
    baseline_menu_detected = False
    count_increase_observed = False
    text_diff_observed = False
    question_repetition_detected = False
    truncated_answer_detected = False
    truncation_retry_used = False
    baseline_last_answer = getattr(context, "baseline_last_answer", "")
    baseline_topic_family = getattr(context, "baseline_topic_family", "unknown")

    while time.perf_counter() < deadline:
        candidate_data = build_post_baseline_answer_candidates(context, question=question)
        current_count = int(candidate_data.get("current_bot_count", 0) or 0)
        count_increased = bool(candidate_data.get("bot_count_increased", False))
        new_bot_segments = candidate_data.get("new_bot_segments", [])
        visible_diff_segments = candidate_data.get("diff_segments", [])
        filtered_new_bot_segments = candidate_data.get("strict_candidates", [])
        filtered_diff_segments = candidate_data.get("fallback_candidates", [])
        new_text = candidate_data.get("answer", "")
        if candidate_data.get("question_repetition_detected"):
            question_repetition_detected = True
        if count_increased:
            count_increase_observed = True
        if new_text:
            text_diff_observed = True

        runtime.logger.info("[ANSWER] current bot count: %s", current_count)
        runtime.logger.info("[ANSWER] new bot count detected %s", count_increased)
        runtime.logger.info("[ANSWER] new bot text diff detected %s", bool(new_text))
        runtime.logger.info("[ANSWER] text diff segment count: %s", len(visible_diff_segments))
        runtime.logger.info("[ANSWER] static UI segments filtered: %s", max(len(visible_diff_segments) - len(filtered_diff_segments), 0))

        if count_increased or new_text:
            strict_candidates = candidate_data.get("strict_candidates", [])
            if strict_candidates:
                latest_text = choose_best_answer_segment(
                    strict_candidates,
                    question=question,
                    baseline_last_answer=baseline_last_answer,
                    baseline_topic_family=baseline_topic_family,
                )
            elif new_text:
                latest_text = new_text
            elif any(
                _contains_baseline_menu(message)
                or _normalize_text(message) in {_normalize_text(item) for item in context.baseline_bot_messages}
                for message in new_bot_segments
            ):
                baseline_menu_detected = True
                latest_text = ""
            if latest_text and _is_loading_answer_text(latest_text):
                runtime.logger.info("[ANSWER] loading-only candidate ignored: %s", latest_text)
                latest_text = ""
            if latest_text:
                if _dom_is_question_repetition(question, latest_text):
                    runtime.logger.info("[ANSWER] question repetition candidate rejected: %s", latest_text)
                    question_repetition_detected = True
                    latest_text = ""
                    stable_checks = 0
                    previous_text = ""
                    if hasattr(context.scope, "wait_for_timeout"):
                        context.scope.wait_for_timeout(int(interval_sec * 1000))
                    else:
                        time.sleep(interval_sec)
                    continue
                clean_latest_text = _clean_bot_answer_candidate(latest_text)
                if _dom_looks_truncated(clean_latest_text):
                    truncated_answer_detected = True
                    if not truncation_retry_used:
                        runtime.logger.info("[ANSWER] truncated candidate detected; waiting one extra cycle")
                        truncation_retry_used = True
                        stable_checks = 0
                        previous_text = ""
                        if hasattr(context.scope, "wait_for_timeout"):
                            context.scope.wait_for_timeout(int(interval_sec * 1000))
                        else:
                            time.sleep(interval_sec)
                        continue
                    runtime.logger.info("[ANSWER] truncated candidate persisted after retry; rejecting success adoption")
                    latest_text = ""
                    stable_checks = 0
                    previous_text = ""
                    if hasattr(context.scope, "wait_for_timeout"):
                        context.scope.wait_for_timeout(int(interval_sec * 1000))
                    else:
                        time.sleep(interval_sec)
                    continue
                is_meaningful = len(clean_latest_text) >= MIN_MAIN_ANSWER_LEN and _is_meaningful_answer_text(clean_latest_text)
                growing = bool(previous_text) and clean_latest_text.startswith(previous_text) and len(clean_latest_text) > len(previous_text)
                runtime.logger.info("[ANSWER] final answer segment chosen: %s", latest_text)
                if clean_latest_text == previous_text:
                    stable_checks += 1
                else:
                    stable_checks = 1
                    previous_text = clean_latest_text
                if runtime.config.is_speed_mode and is_meaningful and stable_checks >= stable_target and not growing and not _loading_visible(context):
                    response_ms = int((time.perf_counter() - started) * 1000)
                    runtime.logger.info("[ANSWER] fast answer stabilized true")
                    runtime.logger.info("[ANSWER][RESPONSE_DETECTED] response_ms=%s", response_ms)
                    return AnswerWaitResult(
                        answer=latest_text,
                        response_ms=response_ms,
                        new_bot_response_detected=True,
                        baseline_menu_detected=baseline_menu_detected,
                        reason="",
                        question_repetition_detected=question_repetition_detected,
                        truncated_answer_detected=False,
                        needs_retry_extraction=False,
                    )
                if stable_checks >= stable_target and not _loading_visible(context):
                    response_ms = int((time.perf_counter() - started) * 1000)
                    runtime.logger.info("[ANSWER] answer stabilized true")
                    runtime.logger.info("[ANSWER][RESPONSE_DETECTED] response_ms=%s", response_ms)
                    return AnswerWaitResult(
                        answer=latest_text,
                        response_ms=response_ms,
                        new_bot_response_detected=True,
                        baseline_menu_detected=baseline_menu_detected,
                        reason="",
                        question_repetition_detected=question_repetition_detected,
                        truncated_answer_detected=False,
                        needs_retry_extraction=False,
                    )

        if hasattr(context.scope, "wait_for_timeout"):
            context.scope.wait_for_timeout(int(interval_sec * 1000))
        else:
            time.sleep(interval_sec)

    runtime.logger.info("[ANSWER] answer stabilized false")
    recovered_last_answer = extract_last_answer(context, question=question)
    recovered_answer = _select_report_answer(
        "",
        str(recovered_last_answer.get("actual_answer_clean") or recovered_last_answer.get("actual_answer") or ""),
        count_increase_observed or text_diff_observed,
        question=question,
        baseline_last_answer=baseline_last_answer,
        baseline_topic_family=baseline_topic_family,
    )
    if recovered_answer and _is_meaningful_answer_text(recovered_answer):
        response_ms = int((time.perf_counter() - started) * 1000)
        runtime.logger.info(
            "[ANSWER][TIMEOUT_RECOVERY] source=%s len=%s",
            recovered_last_answer.get("extraction_source", "unknown"),
            len(recovered_answer),
        )
        runtime.logger.info("[ANSWER][RESPONSE_DETECTED] response_ms=%s", response_ms)
        return AnswerWaitResult(
            answer=recovered_answer,
            response_ms=response_ms,
            new_bot_response_detected=True,
            baseline_menu_detected=baseline_menu_detected,
            reason="",
            question_repetition_detected=False,
            truncated_answer_detected=False,
            needs_retry_extraction=False,
        )
    if truncated_answer_detected:
        reason = "truncated answer detected after retry"
    elif question_repetition_detected:
        reason = "question repetition answer detected"
    elif baseline_menu_detected:
        reason = "Baseline menu only; no answer generated"
    elif count_increase_observed or text_diff_observed:
        reason = "No valid answer text extracted after response detection"
    else:
        reason = "Question submission not reflected in chat history"
    return AnswerWaitResult(
        answer="",
        response_ms=int((time.perf_counter() - started) * 1000),
        new_bot_response_detected=count_increase_observed or text_diff_observed,
        baseline_menu_detected=baseline_menu_detected,
        reason=reason,
        question_repetition_detected=question_repetition_detected,
        truncated_answer_detected=truncated_answer_detected,
        needs_retry_extraction=question_repetition_detected or truncated_answer_detected,
    )


def wait_for_new_bot_response(context: ResolvedChatContext, baseline_bot_count: int, question: str = "") -> AnswerWaitResult:
    """Wait until a new bot response appears after the recorded baseline count."""

    context.baseline_bot_count = baseline_bot_count
    if not context.baseline_bot_messages:
        context.baseline_bot_messages = extract_bot_message_texts(context)[:baseline_bot_count]
    return wait_for_answer_completion(context, question=question)


def capture_artifacts(page: Page, context: ResolvedChatContext | None, case_id: str) -> BrowserArtifacts:
    """Capture full-page and chatbox screenshots plus optional DOM fragment."""

    runtime = _runtime()
    timestamp = runtime.current_case_timestamp or artifact_timestamp()

    fullpage_str, chatbox_str = _capture_stage(
        page,
        context,
        case_id,
        timestamp,
        "failure_state",
        runtime.config,
        runtime.logger,
        case_failed=True,
    )
    fullpage_path = Path(fullpage_str) if fullpage_str else None
    chatbox_path = Path(chatbox_str) if chatbox_str else None
    html_fragment = ""
    if _should_dump_dom_payload(case_failed=True, config=runtime.config):
        html_fragment = _dump_chat_html_fragment(context, case_id, timestamp)
    html_fragment_path = Path(html_fragment) if html_fragment else None

    runtime.logger.info("artifacts saved")
    return BrowserArtifacts(
        fullpage_screenshot=fullpage_path,
        chatbox_screenshot=chatbox_path,
        html_fragment_path=html_fragment_path,
    )


def _status_from_failure_category(category: str) -> str:
    if category in {
        "top_candidate_disabled",
        "composer_transition_timeout",
        "activation_exhausted",
        "no_editable_candidate_after_transition",
        "no_editable_candidate_after_rescan",
        "failover_exhausted",
        "user_echo_not_found",
        "waiting_for_composer_transition",
    }:
        return "invalid_capture"
    if category == "login_required":
        return "failed"
    if category == "answer_not_extracted":
        return "failed"
    return "failed"


def run_single_case(page: Page, test_case: TestCase) -> ExtractedPair:
    """Execute one public, non-login Rubicon chatbot scenario end-to-end."""

    runtime = _runtime()
    runtime.current_case_id = test_case.id
    runtime.current_case_timestamp = artifact_timestamp()
    _reset_case_artifact_state()

    context: ResolvedChatContext | None = None
    artifacts = BrowserArtifacts()
    answer = ""
    raw_answer = ""
    cleaned_answer = ""
    answer_raw = ""
    answer_normalized = ""
    actual_answer = ""
    actual_answer_clean = ""
    question_repetition_detected = False
    truncated_answer_detected = False
    needs_retry_extraction = False
    cta_stripped = False
    promo_stripped = False
    extraction_source = "unknown"
    extraction_source_detail = "unknown"
    extraction_confidence = 0.0
    ocr_text = ""
    ocr_confidence = 0.0
    response_ms = 0
    status = "passed"
    reason = ""
    error_message = ""
    fix_suggestion = ""
    input_dom_verified = False
    submit_effect_verified = False
    input_verified = False
    input_method_used = ""
    submit_method_used = "unknown"
    opened_chat_screenshot_path = ""
    opened_full_screenshot_path = ""
    opened_footer_screenshot_path = ""
    open_method_used = ""
    sdk_status = ""
    availability_status = "unknown"
    input_scope = ""
    input_scope_name = ""
    input_selector = ""
    input_failure_category = ""
    input_failure_reason = ""
    input_candidate_score = 0.0
    top_candidate_disabled = False
    top_candidate_placeholder = ""
    top_candidate_aria = ""
    transition_wait_attempted = False
    input_ready_wait_result = ""
    transition_ready = False
    transition_timeout = False
    transition_reason = ""
    transition_history = ""
    activation_attempted = False
    activation_steps_tried = ""
    editable_candidates_count = 0
    failover_attempts = 0
    final_input_target_frame = ""
    input_candidates_debug = ""
    input_candidate_logs: list[str] = []
    before_send_screenshot_path = ""
    before_send_full_screenshot_path = ""
    after_send_screenshot_path = ""
    after_send_full_screenshot_path = ""
    font_fix_applied = False
    user_message_echo_verified = False
    new_bot_response_detected = False
    baseline_menu_detected = False
    message_history: list[str] = []
    after_answer_screenshot_path = ""
    after_answer_full_screenshot_path = ""
    answer_screenshot_paths: list[str] = []
    after_answer_multi_page = False
    structured_message_history_count = 0
    fallback_diff_used = False
    message_history_clean = ""
    removed_followups = False
    noise_lines_removed = 0
    last_answer_payload = _clear_unverified_answer_fields()
    sdk_info: dict[str, Any] = {"has_sprchat": False, "trigger_exists": False}
    open_result: dict[str, Any] = {"open_method": "failed", "open_ok": False, "open_error": ""}
    activation_result: dict[str, Any] = {
        "activation_attempted": False,
        "activation_steps": [],
        "activation_success": False,
        "editable_candidates_after_activation": 0,
    }
    transition_result: dict[str, Any] = {
        "transition_ready": False,
        "transition_timeout": False,
        "transition_reason": "",
        "transition_history": [],
    }
    submission: SubmissionEvidence | None = None

    try:
        if runtime.config.reopen_homepage_per_case or not page.url:
            open_homepage(page)
        font_fix_applied = inject_korean_font(page)
        dismiss_popups(page)
        sdk_info = get_sprinklr_sdk_status(page)
        sdk_status = f"has_sprchat={sdk_info.get('has_sprchat', False)} trigger_exists={sdk_info.get('trigger_exists', False)}"
        bind_availability_probe(page)
        open_result = open_chat_widget_or_conversation(page)
        if runtime.config.reinject_font_css_after_open:
            font_fix_applied = inject_korean_font(page) or font_fix_applied
        open_method_used = str(open_result.get("open_method", "failed"))
        availability_status = get_availability_probe(page)

        if not open_result.get("open_ok"):
            input_failure_category = "sdk_not_available" if not sdk_info.get("has_sprchat") else "no_chat_open"
            input_failure_reason = str(open_result.get("open_error") or "Failed to open chat widget")

        opened_full_screenshot_path, opened_chat_screenshot_path = _capture_stage(
            page,
            None,
            test_case.id,
            runtime.current_case_timestamp,
            "opened",
            runtime.config,
            runtime.logger,
        )

        try:
            context = resolve_chat_context(page)
        except Exception as exc:
            retry_error = exc
            try:
                page.wait_for_timeout(_context_resolve_wait_ms(runtime.config))
                context = resolve_chat_context(page)
            except Exception:
                context = None
            if context is None and not input_failure_category:
                input_failure_category = "availability_unavailable" if availability_status.lower() in UNAVAILABLE_AVAILABILITY_VALUES else "no_chat_open"
                input_failure_reason = str(retry_error)

        if context is not None:
            context = ensure_clean_conversation(page, context)
            input_scope = context.input_scope_name or context.scope_name
            input_scope_name = context.input_scope_name or context.scope_name
            input_selector = context.input_selector
            input_candidate_score = context.input_candidate_score
            input_candidate_logs = list(context.input_candidate_logs)
            input_candidates_debug = "\n".join(input_candidate_logs)
            opened_full_screenshot_path, opened_chat_screenshot_path = _capture_stage(
                page,
                context,
                test_case.id,
                runtime.current_case_timestamp,
                "opened",
                runtime.config,
                runtime.logger,
            )
            _, opened_footer_screenshot_path = capture_named_artifact(
                page,
                context,
                test_case.id,
                "opened_footer",
                runtime.config,
                case_failed=False,
            )

            ranked_candidates = collect_ranked_input_candidates(context, preferred_scope=context.scope_name)
            top_candidate_placeholder, top_candidate_aria = _top_candidate_texts(ranked_candidates)
            top_candidate_disabled = _candidate_is_disabled_like(ranked_candidates[0] if ranked_candidates else None)

            needs_ready_wait = not ranked_candidates or top_candidate_disabled or not any(
                _is_ready_composer_candidate(candidate) for candidate in ranked_candidates
            )
            if needs_ready_wait:
                runtime.logger.info("[INPUT] waiting for ready composer before submit")
                transition_wait_attempted = True
                transition_result = wait_for_composer_transition(page, context, test_case.id, runtime.config)
                input_ready_wait_result = "ready" if transition_result.get("transition_ready") else "timeout"
                transition_ready = bool(transition_result.get("transition_ready", False))
                transition_timeout = bool(transition_result.get("transition_timeout", False))
                transition_reason = str(transition_result.get("transition_reason", "") or "")
                transition_history = json.dumps(transition_result.get("transition_history", []), ensure_ascii=False)

                if transition_ready:
                    ready_candidate = transition_result.get("ready_candidate")
                    if ready_candidate is not None:
                        _assign_candidate_to_context(context, ready_candidate)
                    ranked_candidates = collect_ranked_input_candidates(
                        context,
                        preferred_scope=str(transition_result.get("ready_scope", "") or context.scope_name),
                    )
                    top_candidate_placeholder, top_candidate_aria = _top_candidate_texts(ranked_candidates)
                    runtime.logger.info("[INPUT] composer transition completed; trying submit before activation")
                else:
                    runtime.logger.warning("[INPUT] composer transition timeout; entering activation fallback")
                    if runtime.config.rubicon_force_activation:
                        activation_result = ensure_composer_ready(page, context)
                        activation_attempted = True
                        activation_steps_tried = ", ".join(activation_result.get("activation_steps", []))
                        editable_candidates_count = int(activation_result.get("editable_candidates_after_activation", 0) or 0)
                        if activation_result.get("activation_success"):
                            ranked_candidates = collect_ranked_input_candidates(context, preferred_scope=context.scope_name)
                            top_candidate_placeholder, top_candidate_aria = _top_candidate_texts(ranked_candidates)
                            top_candidate_disabled = _candidate_is_disabled_like(ranked_candidates[0] if ranked_candidates else None)
                            input_ready_wait_result = "activation_ready"
                        else:
                            context.frame_inventory = scan_frame_inventory(page)
                            input_failure_category = "activation_exhausted"
                            input_failure_reason = "Activation fallback did not reveal a ready composer"
                    else:
                        input_failure_category = "composer_transition_timeout"
                        input_failure_reason = "Composer stayed in disabled transition state until timeout"
            else:
                input_ready_wait_result = "ready_already_present"
                runtime.logger.info("[INPUT] no transition-disabled top candidate; continue normal submit flow")

            _, opened_footer_screenshot_path = capture_named_artifact(
                page,
                context,
                test_case.id,
                "opened_footer",
                runtime.config,
                case_failed=False,
            )

            submission = submit_question(
                page,
                context,
                test_case.question,
                ready_candidate=transition_result.get("ready_candidate") if transition_result.get("transition_ready") else None,
                ready_wait_result={
                    "ready": transition_ready,
                    "timeout": transition_timeout,
                    "result": input_ready_wait_result or ("ready" if transition_ready else ("timeout" if transition_timeout else "not_attempted")),
                    "history": transition_result.get("transition_history", []),
                } if transition_wait_attempted or input_ready_wait_result else None,
            )
            if not activation_attempted:
                editable_candidates_count = submission.editable_candidates_count

            if submission is not None:
                input_dom_verified = submission.input_dom_verified
                submit_effect_verified = submission.submit_effect_verified
                input_verified = submission.input_verified
                input_method_used = submission.input_method_used
                submit_method_used = submission.submit_method_used
                input_scope = submission.input_scope or input_scope
                input_scope_name = submission.input_scope or input_scope_name
                input_selector = submission.input_selector or input_selector
                input_candidate_score = submission.input_candidate_score or input_candidate_score
                top_candidate_disabled = submission.top_candidate_disabled
                top_candidate_placeholder = submission.top_candidate_placeholder or top_candidate_placeholder
                top_candidate_aria = submission.top_candidate_aria or top_candidate_aria
                input_ready_wait_result = submission.input_ready_wait_result or input_ready_wait_result
                transition_wait_attempted = submission.transition_wait_attempted or transition_wait_attempted
                transition_ready = submission.transition_ready or transition_ready
                transition_timeout = submission.transition_timeout or transition_timeout
                transition_reason = submission.transition_reason or transition_reason
                transition_history = submission.transition_history or transition_history
                failover_attempts = submission.failover_attempts
                final_input_target_frame = submission.final_input_target_frame
                user_message_echo_verified = submission.user_message_echo_verified
                before_send_screenshot_path = submission.before_send_chatbox_path
                before_send_full_screenshot_path = submission.before_send_fullpage_path
                after_send_screenshot_path = submission.after_send_chatbox_path
                after_send_full_screenshot_path = submission.after_send_fullpage_path
                editable_candidates_count = submission.editable_candidates_count or editable_candidates_count
                input_candidates_debug = submission.input_candidates_debug or input_candidates_debug
                input_candidate_logs = [line for line in input_candidates_debug.splitlines() if line.strip()]
                if submission.input_failure_category:
                    if submission.input_failure_category != "waiting_for_composer_transition" or not transition_wait_attempted:
                        input_failure_category = submission.input_failure_category
                        input_failure_reason = submission.input_failure_reason
                        if submission.input_failure_category == "login_required":
                            availability_status = "login_required"

        if context is None or submission is None or not submission.input_verified:
            if not input_failure_category:
                input_failure_category = "no_editable_candidate_after_transition"
                input_failure_reason = "Submit flow never reached a verified editable input candidate"
            if context is not None:
                _, failure_capture_path = capture_named_artifact(
                    page,
                    context,
                    test_case.id,
                    "opened_footer",
                    runtime.config,
                    case_failed=True,
                )
                opened_footer_screenshot_path = opened_footer_screenshot_path or failure_capture_path
            else:
                opened_full_screenshot_path, opened_chat_screenshot_path = _capture_stage(
                    page,
                    None,
                    test_case.id,
                    runtime.current_case_timestamp,
                    "failure_state",
                    runtime.config,
                    runtime.logger,
                    case_failed=True,
                )
            status = _status_from_failure_category(input_failure_category)
            reason = input_failure_reason
            error_message = input_failure_reason
            if status == "invalid_capture":
                fix_suggestion = CAPTURE_INVALID_FIX
        else:
            wait_result = wait_for_new_bot_response(context, context.baseline_bot_count, question=test_case.question)
            last_answer_payload = extract_last_answer(context, question=test_case.question)
            question_repetition_detected = wait_result.question_repetition_detected
            truncated_answer_detected = wait_result.truncated_answer_detected
            needs_retry_extraction = wait_result.needs_retry_extraction
            wait_clean_details = _clean_bot_answer_candidate_details(wait_result.answer)
            answer_raw = wait_result.answer
            raw_answer = wait_result.answer
            actual_answer = wait_clean_details["clean"]
            actual_answer_clean = wait_clean_details["clean"]
            cleaned_answer = actual_answer_clean
            answer_normalized = actual_answer_clean or _normalize_answer_text(wait_result.answer)
            answer = actual_answer_clean or answer_normalized
            extraction_source = "dom" if wait_result.answer else "unknown"
            extraction_confidence = 0.85 if wait_result.answer else 0.0
            extraction_source_detail = "wait_verified" if wait_result.answer else "unknown"
            removed_followups = bool(wait_clean_details.get("removed_followups", False))
            noise_lines_removed = int(wait_clean_details.get("noise_lines_removed", 0) or 0)
            response_ms = wait_result.response_ms
            new_bot_response_detected = wait_result.new_bot_response_detected
            baseline_menu_detected = wait_result.baseline_menu_detected

            if _success_stage_enabled("after_answer", runtime.config):
                (
                    answer_screenshot_paths,
                    after_answer_screenshot_path,
                    after_answer_full_screenshot_path,
                    after_answer_multi_page,
                ) = _capture_answer_screenshots(
                    page,
                    context,
                    test_case.id,
                    runtime.current_case_timestamp,
                    runtime.config,
                    runtime.logger,
                )

            dom_payload = extract_dom_payload(context, None, question=test_case.question, scenario_meta=test_case)
            gate = _assess_dom_payload_acceptance(test_case, dom_payload)
            if not gate["passed"]:
                runtime.logger.info("[ANSWER] DOM acceptance gate rejected candidate; waiting one more extraction cycle")
                _wait_one_more_extraction_cycle(context, runtime.config.answer_stable_interval_sec)
                dom_payload = extract_dom_payload(context, None, question=test_case.question, scenario_meta=test_case)
                gate = _assess_dom_payload_acceptance(test_case, dom_payload)

            question_repetition_detected = question_repetition_detected or bool(gate["question_repetition_detected"])
            truncated_answer_detected = truncated_answer_detected or bool(gate["truncated_detected"])
            needs_retry_extraction = needs_retry_extraction or not gate["passed"]
            cta_stripped = bool(dom_payload.get("cta_stripped", False))
            promo_stripped = bool(dom_payload.get("promo_stripped", False))
            if _should_dump_dom_payload(case_failed=False, config=runtime.config):
                _dump_chat_html_fragment(context, test_case.id, runtime.current_case_timestamp)
            dom_answer = str(dom_payload.get("cleaned_answer") or "")
            dom_raw_answer = str(dom_payload.get("raw_answer") or "")
            dom_source = str(dom_payload.get("extraction_source") or "unknown")
            dom_confidence = float(dom_payload.get("extraction_confidence", 0.0) or 0.0)
            selected_report_answer = _select_report_answer(
                wait_result.answer,
                dom_answer or str(last_answer_payload.get("actual_answer_clean") or last_answer_payload.get("actual_answer") or ""),
                new_bot_response_detected,
                question=test_case.question,
                baseline_last_answer=context.baseline_last_answer,
                baseline_topic_family=context.baseline_topic_family,
            )
            if selected_report_answer and (not dom_answer or not gate["passed"]):
                runtime.logger.info(
                    "[ANSWER][REPORT_RECOVERED] source=%s len=%s",
                    last_answer_payload.get("extraction_source") or dom_source or "report_answer_selected",
                    len(selected_report_answer),
                )
                dom_answer = selected_report_answer
                dom_raw_answer = str(last_answer_payload.get("answer_raw") or dom_raw_answer or selected_report_answer)
                dom_source = "dom"
                dom_confidence = max(dom_confidence, 0.82)
            raw_answer = dom_raw_answer
            answer_raw = dom_raw_answer
            answer_normalized = dom_answer or _normalize_answer_text(dom_raw_answer)
            answer = dom_answer
            actual_answer = dom_answer or answer_normalized
            actual_answer_clean = dom_answer
            cleaned_answer = dom_answer
            extraction_source = "dom" if dom_answer else (dom_source or "unknown")
            extraction_confidence = max(dom_confidence, 0.72 if dom_answer else 0.0)
            extraction_source_detail = "dom_payload_cleaned" if dom_answer else (dom_source or "unknown")

            selected_details = _clean_bot_answer_candidate_details(
                dom_raw_answer,
                question=test_case.question,
                baseline_last_answer=context.baseline_last_answer,
                baseline_topic_family=context.baseline_topic_family,
            )
            removed_followups = bool(selected_details.get("cta_stripped", False) or selected_details.get("promo_stripped", False))
            noise_lines_removed = int(selected_details.get("noise_lines_removed", 0) or 0)
            raw_history = dom_payload.get("history", [])
            if _should_store_success_message_history(runtime.config):
                message_history, history_noise_removed = _clean_message_history(
                    raw_history,
                    question=test_case.question,
                    actual_answer=actual_answer_clean or actual_answer,
                )
                message_history_clean = "\n".join(message_history).strip()
                noise_lines_removed += history_noise_removed
                structured_message_history_count = int(dom_payload.get("structured_message_history_count", 0) or 0)
                fallback_diff_used = bool(dom_payload.get("fallback_diff_used", False))
                runtime.logger.info("[HISTORY] visible text block count: %s", len(dom_payload.get("visible_text_blocks", [])))
                if not message_history:
                    runtime.logger.warning(
                        "[HISTORY] no structured message history extracted; falling back to visible chat text scan"
                    )
                    visible_text = dom_payload.get("visible_chat_text", "")
                    message_history, history_noise_removed = _clean_message_history(
                        visible_text.splitlines(),
                        question=test_case.question,
                        actual_answer=actual_answer_clean or actual_answer,
                    )
                    message_history_clean = "\n".join(message_history).strip()
                    noise_lines_removed += history_noise_removed
                    runtime.logger.info("[HISTORY] visible chat text fallback used")
                    fallback_diff_used = True
                runtime.logger.info("[HISTORY] history extracted count: %s", len(message_history))
                runtime.logger.info("[HISTORY] structured message history count: %s", structured_message_history_count)
                runtime.logger.info("[HISTORY] fallback diff used: %s", fallback_diff_used)
            else:
                message_history = []
                message_history_clean = ""
                structured_message_history_count = 0
                fallback_diff_used = False
                runtime.logger.info("[HISTORY] success-path history capture skipped in %s mode", runtime.config.run_mode)

            if not new_bot_response_detected:
                recovered_payload = _recover_dom_response_candidate(
                    test_case.question,
                    last_answer_payload.get("answer_raw") or dom_answer,
                    last_answer_payload,
                    message_history,
                )
                if recovered_payload.get("detected") and submit_effect_verified and user_message_echo_verified:
                    new_bot_response_detected = True
                    answer_raw = str(recovered_payload.get("answer_raw") or "")
                    raw_answer = answer_raw
                    actual_answer = str(recovered_payload.get("actual_answer") or "")
                    actual_answer_clean = str(recovered_payload.get("actual_answer_clean") or "")
                    cleaned_answer = actual_answer_clean
                    answer_normalized = actual_answer_clean or _normalize_answer_text(answer_raw)
                    answer = actual_answer_clean or answer_normalized
                    extraction_source = "dom"
                    extraction_source_detail = str(recovered_payload.get("source") or "dom_recovered_response")
                    extraction_confidence = max(extraction_confidence, 0.9)
                    runtime.logger.info(
                        "[ANSWER][DOM_RECOVERED_RESPONSE] source=%s len=%s",
                        extraction_source_detail,
                        len(actual_answer_clean or answer_normalized),
                    )

            dom_candidate = cleaned_answer or actual_answer_clean or actual_answer or answer_normalized or answer_raw or dom_answer
            dom_answer_verified = (
                new_bot_response_detected
                and gate["passed"]
                and _is_meaningful_answer_text(dom_candidate)
                and _has_minimal_question_alignment(test_case.question, dom_candidate)
            )

            if dom_answer_verified:
                extraction_source = "dom"
                extraction_confidence = max(extraction_confidence, dom_confidence, 0.85)
                runtime.logger.info("DOM extracted")
            elif _should_run_ocr_fallback(dom_candidate, new_bot_response_detected, runtime.config):
                _, ocr_target_path = capture_named_artifact(
                    page,
                    context,
                    test_case.id,
                    "ocr_target",
                    runtime.config,
                    case_failed=True,
                )
                if ocr_target_path:
                    after_answer_screenshot_path = after_answer_screenshot_path or ocr_target_path
                ocr_text, confidence = extract_text_from_image(Path(ocr_target_path), runtime.logger) if ocr_target_path else ("", 0.0)
                if ocr_text:
                    answer_raw = ocr_text
                    raw_answer = ocr_text
                    ocr_details = _clean_bot_answer_candidate_details(ocr_text)
                    actual_answer = ocr_details["clean"] or _normalize_answer_text(ocr_text)
                    actual_answer_clean = actual_answer
                    cleaned_answer = actual_answer_clean
                    answer_normalized = actual_answer_clean
                    answer = actual_answer_clean
                    extraction_source = "ocr"
                    extraction_source_detail = "ocr_fallback"
                    extraction_confidence = confidence
                    ocr_text = answer_raw
                    ocr_confidence = confidence
                    removed_followups = bool(ocr_details.get("removed_followups", False))
                    noise_lines_removed += int(ocr_details.get("noise_lines_removed", 0) or 0)
                    runtime.logger.info("OCR fallback used")
                else:
                    after_answer_full_screenshot_path, failure_after_answer = capture_named_artifact(
                        page,
                        context,
                        test_case.id,
                        "after_answer",
                        runtime.config,
                        case_failed=True,
                    )
                    after_answer_screenshot_path = after_answer_screenshot_path or failure_after_answer

            if (cleaned_answer or actual_answer_clean or answer_raw) and extraction_source == "unknown":
                runtime.logger.warning(
                    "[ANSWER][INVALID_STATE] non-empty answer with unknown extraction source detail=%s",
                    extraction_source_detail,
                )
                extraction_source = "dom"
                extraction_confidence = max(extraction_confidence, dom_confidence, 0.65)

            if not gate["passed"]:
                if (
                    dom_answer
                    and _is_meaningful_answer_text(dom_answer)
                    and _has_minimal_question_alignment(test_case.question, dom_answer)
                ):
                    runtime.logger.info("[ANSWER][GATE_OVERRIDE] recovered answer accepted after report selection")
                    gate = {
                        **gate,
                        "passed": True,
                        "status": "passed",
                        "reason": "Harness acceptance gate accepted the recovered answer",
                        "fix_suggestion": "",
                        "question_repetition_detected": False,
                        "truncated_detected": False,
                    }
                    question_repetition_detected = False
                    truncated_answer_detected = False
                    needs_retry_extraction = False
                else:
                    status = gate["status"]
                    reason = gate["reason"]
                    error_message = reason
                    fix_suggestion = gate["fix_suggestion"]
                    input_failure_category = gate["status"]
                    input_failure_reason = reason
                    if not after_answer_screenshot_path:
                        _, failure_after_answer = capture_named_artifact(
                            page,
                            context,
                            test_case.id,
                            "after_answer",
                            runtime.config,
                            case_failed=True,
                        )
                        after_answer_screenshot_path = failure_after_answer
            elif not answer_raw:
                input_failure_category = "answer_not_extracted"
                input_failure_reason = wait_result.reason or "No answer text extracted"
                status = "failed"
                reason = input_failure_reason
                error_message = error_message or reason
            elif not user_message_echo_verified:
                input_failure_category = "user_echo_not_found"
                input_failure_reason = "Question submission not reflected as a user echo"
                status = "invalid_capture"
                reason = input_failure_reason
                error_message = reason
                fix_suggestion = CAPTURE_INVALID_FIX
                if not after_answer_screenshot_path:
                    _, failure_after_answer = capture_named_artifact(
                        page,
                        context,
                        test_case.id,
                        "after_answer",
                        runtime.config,
                        case_failed=True,
                    )
                    after_answer_screenshot_path = failure_after_answer
            elif status == "passed":
                reason = gate["reason"]
    except RuntimeError as exc:
        err_str = str(exc)
        status = "failed"
        reason = err_str
        error_message = err_str
        runtime.logger.error("exception details: %s", exc)
        try:
            if artifacts.fullpage_screenshot is None and artifacts.chatbox_screenshot is None:
                artifacts = capture_artifacts(page, context, test_case.id)
        except Exception:
            pass
    except Exception as exc:
        status = "failed"
        reason = str(exc)
        error_message = str(exc)
        runtime.logger.exception("exception details: %s", exc)
        try:
            if artifacts.fullpage_screenshot is None and artifacts.chatbox_screenshot is None:
                artifacts = capture_artifacts(page, context, test_case.id)
        except Exception:
            pass

    return ExtractedPair(
        run_timestamp=utc_now_timestamp(),
        case_id=test_case.id,
        category=test_case.category,
        page_url=test_case.page_url,
        locale=test_case.locale,
        question=test_case.question,
        answer=answer,
        raw_answer=raw_answer or answer_raw,
        cleaned_answer=cleaned_answer or actual_answer_clean or answer,
        final_answer=cleaned_answer or actual_answer_clean or actual_answer or answer,
        answer_raw=answer_raw,
        answer_normalized=answer_normalized,
        actual_answer=actual_answer or answer,
        actual_answer_clean=actual_answer_clean or actual_answer or answer,
        extraction_source=extraction_source,
        extraction_source_detail=extraction_source_detail,
        extraction_confidence=extraction_confidence,
        response_ms=response_ms,
        status=status,
        reason=reason,
        error_message=error_message,
        run_mode=runtime.config.run_mode,
        fast_path_used=runtime.config.is_speed_mode and input_method_used in {"fill", "keyboard.type"} and not ocr_text,
        full_screenshot_path=after_answer_full_screenshot_path or str(artifacts.fullpage_screenshot or ""),
        chat_screenshot_path=after_answer_screenshot_path or str(artifacts.chatbox_screenshot or ""),
        submitted_chat_screenshot_path=after_send_screenshot_path,
        answered_chat_screenshot_path=after_answer_screenshot_path,
        video_path="",
        trace_path="",
        html_fragment_path=str(artifacts.html_fragment_path or runtime.latest_html_fragment_path or ""),
        evidence_markdown_path="",
        evidence_json_path="",
        fix_suggestion=fix_suggestion,
        cta_stripped=cta_stripped,
        promo_stripped=promo_stripped,
        ui_noise_stripped=bool(dom_payload.get("ui_noise_stripped", False)) if 'dom_payload' in locals() else False,
        input_dom_verified=input_dom_verified,
        submit_effect_verified=submit_effect_verified,
        input_verified=input_verified,
        input_method_used=input_method_used,
        submit_method_used=submit_method_used,
        opened_chat_screenshot_path=opened_chat_screenshot_path,
        opened_full_screenshot_path=opened_full_screenshot_path,
        opened_footer_screenshot_path=opened_footer_screenshot_path,
        open_method_used=open_method_used,
        sdk_status=sdk_status,
        availability_status=availability_status,
        input_scope=input_scope,
        input_scope_name=input_scope_name,
        input_selector=input_selector,
        input_failure_category=input_failure_category,
        input_failure_reason=input_failure_reason,
        input_candidate_score=input_candidate_score,
        top_candidate_disabled=top_candidate_disabled,
        top_candidate_placeholder=top_candidate_placeholder,
        top_candidate_aria=top_candidate_aria,
        input_ready_wait_result=input_ready_wait_result,
        transition_wait_attempted=transition_wait_attempted,
        transition_ready=transition_ready,
        transition_timeout=transition_timeout,
        transition_reason=transition_reason,
        transition_history=transition_history,
        activation_attempted=activation_attempted,
        activation_steps_tried=activation_steps_tried,
        editable_candidates_count=editable_candidates_count,
        failover_attempts=failover_attempts,
        final_input_target_frame=final_input_target_frame,
        input_candidates_debug=input_candidates_debug,
        input_candidate_logs=input_candidate_logs,
        before_send_screenshot_path=before_send_screenshot_path,
        before_send_full_screenshot_path=before_send_full_screenshot_path,
        after_send_screenshot_path=after_send_screenshot_path,
        after_send_full_screenshot_path=after_send_full_screenshot_path,
        after_answer_screenshot_path=after_answer_screenshot_path,
        after_answer_full_screenshot_path=after_answer_full_screenshot_path,
        font_fix_applied=font_fix_applied,
        user_message_echo_verified=user_message_echo_verified,
        new_bot_response_detected=new_bot_response_detected,
        baseline_menu_detected=baseline_menu_detected,
        answer_screenshot_paths=answer_screenshot_paths,
        after_answer_multi_page=after_answer_multi_page,
        ocr_text=ocr_text,
        ocr_confidence=ocr_confidence,
        structured_message_history_count=structured_message_history_count,
        fallback_diff_used=fallback_diff_used,
        question_repetition_detected=question_repetition_detected,
        truncated_detected=truncated_answer_detected,
        truncated_answer_detected=truncated_answer_detected,
        carryover_detected=bool(dom_payload.get("carryover_detected", False)) if 'dom_payload' in locals() else False,
        stale_answer_detected=bool(dom_payload.get("stale_answer_detected", False)) if 'dom_payload' in locals() else False,
        keyword_coverage_score=float(dom_payload.get("keyword_coverage_score", 0.0) or 0.0) if 'dom_payload' in locals() else 0.0,
        needs_retry_extraction=needs_retry_extraction,
        candidate_count=int(dom_payload.get("candidate_count", 0) or 0) if 'dom_payload' in locals() else 0,
        selected_candidate_rank=int(dom_payload.get("selected_candidate_rank", 0) or 0) if 'dom_payload' in locals() else 0,
        released_override=test_case.released_override,
        message_history=message_history,
        message_history_clean=message_history_clean,
        removed_followups=removed_followups,
        noise_lines_removed=noise_lines_removed,
    )

