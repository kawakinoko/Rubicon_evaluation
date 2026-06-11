"""Playwright browser lifecycle management for per-case execution."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from app.config import AppConfig
from app.utils import ensure_parent


_CHAT_STATE_COOKIE_PREFIXES = (
    "spr-chat-token-",
)

_CHAT_STATE_DOMAIN_HINTS = (
    "sprinklr.com",
)

_CHAT_STATE_ORIGIN_HINTS = (
    "sprinklr.com",
)


def _is_chat_state_cookie(cookie: dict[str, Any]) -> bool:
    name = str(cookie.get("name") or "")
    domain = str(cookie.get("domain") or "")
    if any(name.startswith(prefix) for prefix in _CHAT_STATE_COOKIE_PREFIXES):
        return True
    return any(hint in domain for hint in _CHAT_STATE_DOMAIN_HINTS)


def _is_chat_state_origin(origin_entry: dict[str, Any]) -> bool:
    origin = str(origin_entry.get("origin") or "")
    return any(hint in origin for hint in _CHAT_STATE_ORIGIN_HINTS)


def _load_sanitized_storage_state(storage_state_path: Path, logger: Any) -> dict[str, Any]:
    payload = json.loads(storage_state_path.read_text(encoding="utf-8"))
    cookies = payload.get("cookies") or []
    origins = payload.get("origins") or []

    filtered_cookies = [cookie for cookie in cookies if not _is_chat_state_cookie(cookie)]
    filtered_origins = [origin for origin in origins if not _is_chat_state_origin(origin)]

    removed_cookies = len(cookies) - len(filtered_cookies)
    removed_origins = len(origins) - len(filtered_origins)
    if removed_cookies or removed_origins:
        logger.info(
            "sanitized storage state: removed chat cookies=%s origins=%s",
            removed_cookies,
            removed_origins,
        )

    return {
        "cookies": filtered_cookies,
        "origins": filtered_origins,
    }


@dataclass(slots=True)
class CaseBrowserSession:
    """Per-case browser session holding context and page objects."""

    case_id: str
    context: BrowserContext
    page: Page
    config: AppConfig

    def close(self, trace_target: Path | None = None, video_target: Path | None = None) -> tuple[str, str]:
        """Stop tracing, close the context, and move the recorded video if present."""

        video_source: Any = self.page.video if self.config.video_recording_enabled else None
        trace_path = ""
        video_path = ""

        if self.config.trace_recording_enabled:
            if trace_target is not None:
                ensure_parent(trace_target)
                self.context.tracing.stop(path=str(trace_target))
                trace_path = str(trace_target)
            else:
                self.context.tracing.stop()

        self.context.close()

        if self.config.video_recording_enabled and video_source is not None:
            raw_video_path = Path(video_source.path())
            if video_target is not None:
                ensure_parent(video_target)
                shutil.copy2(raw_video_path, video_target)
                video_path = str(video_target)
            else:
                video_path = str(raw_video_path)

        return trace_path, video_path


class BrowserManager:
    """Manage the shared Playwright browser and create isolated case contexts."""

    def __init__(self, config: AppConfig, logger: Any) -> None:
        self.config = config
        self.logger = logger
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._xvfb_process: subprocess.Popen[str] | None = None

    def _ensure_display(self) -> None:
        """Start Xvfb automatically when headed mode runs without a DISPLAY."""

        if self.config.headless or os.environ.get("DISPLAY"):
            return

        display = ":99"
        self.logger.warning("DISPLAY is not set; starting Xvfb on %s", display)
        self._xvfb_process = subprocess.Popen(
            ["Xvfb", display, "-screen", "0", "1440x1200x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        os.environ["DISPLAY"] = display
        time.sleep(1)

    def start(self) -> None:
        """Start Playwright and launch Chromium."""

        self._ensure_display()
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(headless=self.config.headless)
        except Exception as exc:
            message = str(exc)
            if "Executable doesn't exist" not in message and "browserType.launch" not in message:
                raise
            self.logger.warning("Chromium is missing; attempting Playwright install")
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                check=True,
            )
            self._browser = self._playwright.chromium.launch(headless=self.config.headless)

    def new_case_session(self, case_id: str) -> CaseBrowserSession:
        """Create a new isolated browser context and page for a single case."""

        if self._browser is None:
            raise RuntimeError("BrowserManager.start() must be called first")
        if not self.config.samsung_storage_state_path.exists():
            raise FileNotFoundError(
                "Samsung login storage state is required but missing: "
                f"{self.config.samsung_storage_state_path}. "
                "Complete samsung.com/sec login via noVNC and save storage state first."
            )

        context_kwargs: dict[str, Any] = {
            "locale": self.config.default_locale,
            "viewport": {"width": 1440, "height": 1200},
        }
        self.logger.info("loading samsung storage state from %s", self.config.samsung_storage_state_path)
        try:
            context_kwargs["storage_state"] = _load_sanitized_storage_state(
                self.config.samsung_storage_state_path,
                self.logger,
            )
        except Exception as error:
            self.logger.warning("failed to sanitize storage state; using raw file: %s", error)
            context_kwargs["storage_state"] = str(self.config.samsung_storage_state_path)
        if self.config.video_recording_enabled:
            context_kwargs["record_video_dir"] = str(self.config.video_dir)
            context_kwargs["record_video_size"] = {"width": 1440, "height": 1200}

        context = self._browser.new_context(**context_kwargs)
        context.set_default_timeout(self.config.playwright_timeout_ms)
        page = context.new_page()
        page.set_default_timeout(self.config.playwright_timeout_ms)

        if self.config.trace_recording_enabled:
            context.tracing.start(screenshots=True, snapshots=True, sources=True)

        return CaseBrowserSession(case_id=case_id, context=context, page=page, config=self.config)

    def stop(self) -> None:
        """Close browser and Playwright runtime."""

        if self._browser is not None:
            try:
                self._browser.close()
            except Exception as error:
                self.logger.warning("browser close failed: %s", error)
            finally:
                self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception as error:
                self.logger.warning("playwright stop failed: %s", error)
            finally:
                self._playwright = None
        if self._xvfb_process is not None:
            try:
                self._xvfb_process.terminate()
                self._xvfb_process.wait(timeout=5)
            except Exception as error:
                self.logger.warning("xvfb shutdown failed: %s", error)
            finally:
                self._xvfb_process = None
