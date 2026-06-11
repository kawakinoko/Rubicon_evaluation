"""Runtime configuration for the Samsung Rubicon QA automation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from app.scenario_tags import RELEASED_PRODUCT_OVERRIDES


def _to_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value
    return None


def _normalize_capture_mode(value: str | None) -> str:
    normalized = str(value or "fail_only").strip().lower()
    if normalized not in {"lean", "fail_only", "debug"}:
        return "fail_only"
    return normalized


def _normalize_run_mode(value: str | None) -> str:
    normalized = str(value or "speed").strip().lower()
    if normalized not in {"speed", "standard", "debug"}:
        return "speed"
    return normalized


def _parse_case_ids(value: str | None) -> list[str]:
    if not value:
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in value.replace("\n", ",").split(","):
        case_id = raw.strip()
        if not case_id or case_id in seen:
            continue
        seen.add(case_id)
        ordered.append(case_id)
    return ordered


@dataclass(slots=True)
class AppConfig:
    """All environment-driven configuration used by the application."""

    project_root: Path
    openai_api_key: str
    samsung_base_url: str
    headless: bool
    default_locale: str
    max_questions: int
    openai_model: str
    playwright_timeout_ms: int
    answer_stable_checks: int
    answer_stable_interval_sec: float
    enable_video: bool
    enable_trace: bool
    enable_ocr_fallback: bool
    rubicon_chat_debug: bool
    rubicon_force_activation: bool
    rubicon_disable_sdk: bool
    rubicon_max_input_candidates: int
    rubicon_frame_rescan_rounds: int
    rubicon_before_send_screenshot: bool
    rubicon_opened_footer_screenshot: bool
    rubicon_after_answer_screenshot: bool
    capture_mode: str = "fail_only"
    enable_screenshots: bool = False
    enable_fullpage_screenshots: bool = False
    enable_chatbox_screenshots: bool = False
    enable_ocr_on_failure: bool = True
    enable_ocr_always: bool = False
    save_before_send_on_success: bool = False
    save_after_answer_on_success: bool = False
    upload_artifacts_on_success: bool = False
    keep_only_failure_artifacts: bool = True
    max_screenshots_per_case: int = 2
    selected_case_ids: list[str] = field(default_factory=list)
    run_mode: str = "speed"
    enable_fullpage_screenshot: bool = False
    enable_chat_screenshot_on_success: bool = False
    enable_message_history_on_success: bool = False
    enable_dom_dump_on_success: bool = False
    fast_context_resolve_rounds: int = 2
    fast_context_resolve_wait_ms: int = 1200
    fast_answer_timeout_ms: int = 12000
    fast_answer_stable_checks: int = 2
    fast_answer_stable_interval_sec: float = 0.4
    reopen_homepage_per_case: bool = True
    reinject_font_css_after_open: bool = False
    harness_mode: str = "standard"
    acceptance_min_length: int = 40
    acceptance_keyword_threshold: float = 0.30
    retry_on_truncation: bool = True
    retry_on_carryover: bool = True
    strip_ui_noise: bool = True
    strip_followup_cta: bool = True
    strip_promo_review: bool = True
    released_product_overrides: list[str] = field(default_factory=lambda: list(RELEASED_PRODUCT_OVERRIDES))
    report_debug_fields_on_success: bool = False

    @property
    def is_speed_mode(self) -> bool:
        return self.run_mode == "speed"

    @property
    def is_debug_mode(self) -> bool:
        return self.run_mode == "debug"

    @property
    def video_recording_enabled(self) -> bool:
        return self.is_debug_mode and self.enable_video

    @property
    def trace_recording_enabled(self) -> bool:
        return self.is_debug_mode and self.enable_trace

    @property
    def artifacts_dir(self) -> Path:
        return self.project_root / "artifacts"

    @property
    def fullpage_dir(self) -> Path:
        return self.artifacts_dir / "fullpage"

    @property
    def chatbox_dir(self) -> Path:
        return self.artifacts_dir / "chatbox"

    @property
    def video_dir(self) -> Path:
        return self.artifacts_dir / "video"

    @property
    def trace_dir(self) -> Path:
        return self.artifacts_dir / "trace"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    @property
    def secrets_dir(self) -> Path:
        return self.project_root / ".secrets"

    @property
    def samsung_storage_state_path(self) -> Path:
        return self.secrets_dir / "samsung_storage_state.json"

    @property
    def questions_csv_path(self) -> Path:
        return self.project_root / "testcases" / "questions.csv"

    @property
    def runtime_log_path(self) -> Path:
        return self.reports_dir / "runtime.log"

    def ensure_directories(self) -> None:
        """Create output directories required by the workflow."""

        for path in [
            self.artifacts_dir,
            self.fullpage_dir,
            self.chatbox_dir,
            self.video_dir,
            self.trace_dir,
            self.reports_dir,
            self.secrets_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)


def load_config(project_root: Path | None = None) -> AppConfig:
    """Load environment variables and create a normalized config object."""

    resolved_root = project_root or Path(__file__).resolve().parent.parent
    env_path = resolved_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    run_mode = _normalize_run_mode(_first_env("RUN_MODE"))
    capture_mode = _normalize_capture_mode(_first_env("RUBICON_CAPTURE_MODE"))
    if run_mode == "debug":
        capture_mode = "debug"
    else:
        capture_mode = "fail_only"

    enable_video = _to_bool(_first_env("RUBICON_ENABLE_VIDEO", "ENABLE_VIDEO"), False)
    enable_screenshots = _to_bool(_first_env("RUBICON_ENABLE_SCREENSHOTS"), False)
    enable_fullpage_screenshots = _to_bool(
        _first_env("RUBICON_ENABLE_FULLPAGE_SCREENSHOTS", "ENABLE_FULLPAGE_SCREENSHOT"),
        False,
    )
    enable_chatbox_screenshots = _to_bool(_first_env("RUBICON_ENABLE_CHATBOX_SCREENSHOTS"), False)
    enable_ocr_on_failure = _to_bool(_first_env("RUBICON_ENABLE_OCR_ON_FAILURE", "ENABLE_OCR_FALLBACK"), False)
    enable_ocr_always = _to_bool(_first_env("RUBICON_ENABLE_OCR_ALWAYS"), False)
    save_before_send_on_success = _to_bool(_first_env("RUBICON_SAVE_BEFORE_SEND_ON_SUCCESS", "RUBICON_BEFORE_SEND_SCREENSHOT"), False)
    save_after_answer_on_success = _to_bool(_first_env("RUBICON_SAVE_AFTER_ANSWER_ON_SUCCESS", "RUBICON_AFTER_ANSWER_SCREENSHOT"), False)
    upload_artifacts_on_success = _to_bool(_first_env("RUBICON_UPLOAD_ARTIFACTS_ON_SUCCESS"), False)
    keep_only_failure_artifacts = _to_bool(
        _first_env("RUBICON_KEEP_ONLY_FAILURE_ARTIFACTS"),
        run_mode != "debug",
    )
    max_screenshots_per_case = max(0, int(_first_env("RUBICON_MAX_SCREENSHOTS_PER_CASE") or ("1" if run_mode == "speed" else "2")))
    enable_chat_screenshot_on_success = _to_bool(_first_env("ENABLE_CHAT_SCREENSHOT_ON_SUCCESS"), False)
    enable_message_history_on_success = _to_bool(_first_env("ENABLE_MESSAGE_HISTORY_ON_SUCCESS"), False)
    enable_dom_dump_on_success = _to_bool(_first_env("ENABLE_DOM_DUMP_ON_SUCCESS"), False)
    fast_context_resolve_rounds = max(1, int(_first_env("FAST_CONTEXT_RESOLVE_ROUNDS") or "2"))
    fast_context_resolve_wait_ms = max(100, int(_first_env("FAST_CONTEXT_RESOLVE_WAIT_MS") or "1200"))
    fast_answer_timeout_ms = max(1000, int(_first_env("FAST_ANSWER_TIMEOUT_MS") or "12000"))
    fast_answer_stable_checks = max(1, int(_first_env("FAST_ANSWER_STABLE_CHECKS") or "2"))
    fast_answer_stable_interval_sec = max(0.1, float(_first_env("FAST_ANSWER_STABLE_INTERVAL_SEC") or "0.4"))
    reopen_homepage_per_case = _to_bool(_first_env("REOPEN_HOMEPAGE_PER_CASE"), True)
    reinject_font_css_after_open = _to_bool(_first_env("REINJECT_FONT_CSS_AFTER_OPEN"), False)
    harness_mode = str(_first_env("HARNESS_MODE") or "standard").strip().lower()
    if harness_mode not in {"lean", "standard", "debug"}:
        harness_mode = "standard"
    released_product_overrides = _parse_case_ids(_first_env("RELEASED_PRODUCT_OVERRIDES")) or list(RELEASED_PRODUCT_OVERRIDES)

    if run_mode == "speed":
        enable_video = False
        enable_screenshots = False
        enable_fullpage_screenshots = False
        enable_chatbox_screenshots = False
        enable_chat_screenshot_on_success = False
        enable_message_history_on_success = False
        enable_dom_dump_on_success = False
        enable_ocr_on_failure = False
        enable_ocr_always = False
    elif run_mode != "debug":
        enable_video = False
        enable_fullpage_screenshots = False

    enable_trace = _to_bool(os.getenv("ENABLE_TRACE"), False)
    if run_mode != "debug":
        enable_trace = False

    enable_fullpage_screenshot = enable_fullpage_screenshots
    if run_mode == "debug":
        save_before_send_on_success = _to_bool(_first_env("RUBICON_SAVE_BEFORE_SEND_ON_SUCCESS", "RUBICON_BEFORE_SEND_SCREENSHOT"), False)
        save_after_answer_on_success = _to_bool(_first_env("RUBICON_SAVE_AFTER_ANSWER_ON_SUCCESS", "RUBICON_AFTER_ANSWER_SCREENSHOT"), False)
    else:
        save_before_send_on_success = False
        save_after_answer_on_success = False

    return AppConfig(
        project_root=resolved_root,
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        samsung_base_url=os.getenv("SAMSUNG_BASE_URL", "https://www.samsung.com/sec/").strip(),
        headless=_to_bool(os.getenv("HEADLESS"), False),
        default_locale=os.getenv("DEFAULT_LOCALE", "ko-KR").strip(),
        max_questions=int(os.getenv("MAX_QUESTIONS", "5")),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o").strip(),
        playwright_timeout_ms=int(os.getenv("PLAYWRIGHT_TIMEOUT_MS", "30000")),
        answer_stable_checks=int(os.getenv("ANSWER_STABLE_CHECKS", "3")),
        answer_stable_interval_sec=float(os.getenv("ANSWER_STABLE_INTERVAL_SEC", "1.0")),
        enable_video=enable_video,
        enable_trace=enable_trace,
        enable_ocr_fallback=enable_ocr_on_failure or enable_ocr_always,
        rubicon_chat_debug=_to_bool(os.getenv("RUBICON_CHAT_DEBUG"), False),
        rubicon_force_activation=_to_bool(os.getenv("RUBICON_FORCE_ACTIVATION"), True),
        rubicon_disable_sdk=_to_bool(os.getenv("RUBICON_DISABLE_SDK"), False),
        rubicon_max_input_candidates=int(os.getenv("RUBICON_MAX_INPUT_CANDIDATES", "5")),
        rubicon_frame_rescan_rounds=int(os.getenv("RUBICON_FRAME_RESCAN_ROUNDS", "3")),
        rubicon_before_send_screenshot=save_before_send_on_success,
        rubicon_opened_footer_screenshot=_to_bool(_first_env("RUBICON_OPENED_FOOTER_SCREENSHOT"), False),
        rubicon_after_answer_screenshot=save_after_answer_on_success,
        capture_mode=capture_mode,
        enable_screenshots=enable_screenshots,
        enable_fullpage_screenshots=enable_fullpage_screenshots,
        enable_chatbox_screenshots=enable_chatbox_screenshots,
        enable_ocr_on_failure=enable_ocr_on_failure,
        enable_ocr_always=enable_ocr_always,
        save_before_send_on_success=save_before_send_on_success,
        save_after_answer_on_success=save_after_answer_on_success,
        upload_artifacts_on_success=upload_artifacts_on_success,
        keep_only_failure_artifacts=keep_only_failure_artifacts,
        max_screenshots_per_case=max_screenshots_per_case,
        selected_case_ids=_parse_case_ids(_first_env("RUBICON_CASE_IDS", "CASE_IDS")),
        run_mode=run_mode,
        enable_fullpage_screenshot=enable_fullpage_screenshot,
        enable_chat_screenshot_on_success=enable_chat_screenshot_on_success,
        enable_message_history_on_success=enable_message_history_on_success,
        enable_dom_dump_on_success=enable_dom_dump_on_success,
        fast_context_resolve_rounds=fast_context_resolve_rounds,
        fast_context_resolve_wait_ms=fast_context_resolve_wait_ms,
        fast_answer_timeout_ms=fast_answer_timeout_ms,
        fast_answer_stable_checks=fast_answer_stable_checks,
        fast_answer_stable_interval_sec=fast_answer_stable_interval_sec,
        reopen_homepage_per_case=reopen_homepage_per_case,
        reinject_font_css_after_open=reinject_font_css_after_open,
        harness_mode=harness_mode,
        acceptance_min_length=max(1, int(_first_env("ACCEPTANCE_MIN_LENGTH") or "40")),
        acceptance_keyword_threshold=max(0.0, min(1.0, float(_first_env("ACCEPTANCE_KEYWORD_THRESHOLD") or "0.30"))),
        retry_on_truncation=_to_bool(_first_env("RETRY_ON_TRUNCATION"), True),
        retry_on_carryover=_to_bool(_first_env("RETRY_ON_CARRYOVER"), True),
        strip_ui_noise=_to_bool(_first_env("STRIP_UI_NOISE"), True),
        strip_followup_cta=_to_bool(_first_env("STRIP_FOLLOWUP_CTA"), True),
        strip_promo_review=_to_bool(_first_env("STRIP_PROMO_REVIEW"), True),
        released_product_overrides=released_product_overrides,
        report_debug_fields_on_success=_to_bool(_first_env("REPORT_DEBUG_FIELDS_ON_SUCCESS"), False),
    )
