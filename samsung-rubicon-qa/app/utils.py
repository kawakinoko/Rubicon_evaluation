"""Shared helper functions used across the QA automation modules."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeAlias

from playwright.sync_api import Frame, Locator, Page, TimeoutError as PlaywrightTimeoutError


Scope: TypeAlias = Page | Frame


def utc_now_timestamp() -> str:
    """Return an ISO-8601 timestamp in UTC."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def artifact_timestamp() -> str:
    """Return a filename-friendly local timestamp."""

    return datetime.now().strftime("%Y%m%d_%H%M%S")


def sanitize_filename(value: str) -> str:
    """Convert arbitrary text into a filesystem-safe token."""

    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return sanitized.strip("_") or "case"


def ensure_parent(path: Path) -> Path:
    """Create the parent directory of a file path and return the path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Any) -> None:
    """Write JSON using UTF-8 and indentation."""

    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def compile_regex(pattern: str) -> re.Pattern[str]:
    """Compile a case-insensitive regex string."""

    return re.compile(pattern, re.IGNORECASE)


def build_locator(scope: Scope, candidate: dict[str, Any]) -> Locator:
    """Build a Playwright locator from a normalized candidate specification."""

    locator_type = candidate["type"]
    if locator_type == "role":
        return scope.get_by_role(candidate["role"], name=candidate.get("name"))
    if locator_type == "label":
        return scope.get_by_label(candidate["value"])
    if locator_type == "placeholder":
        return scope.get_by_placeholder(candidate["value"])
    if locator_type == "text":
        return scope.get_by_text(candidate["value"])
    if locator_type == "testid":
        return scope.get_by_test_id(candidate["value"])
    if locator_type == "css":
        return scope.locator(candidate["value"])
    raise ValueError(f"Unsupported locator candidate: {locator_type}")


def first_visible_locator(
    scope: Scope,
    candidates: list[dict[str, Any]],
    timeout_ms: int,
) -> tuple[Locator | None, dict[str, Any] | None]:
    """Return the first candidate whose first match becomes visible."""

    for candidate in candidates:
        locator = build_locator(scope, candidate).first
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
            return locator, candidate
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    return None, None


def collect_locators(scope: Scope, candidates: list[dict[str, Any]]) -> list[Locator]:
    """Collect locators that currently match at least one DOM node."""

    matched: list[Locator] = []
    seen: set[str] = set()
    for candidate in candidates:
        locator = build_locator(scope, candidate)
        try:
            count = locator.count()
        except Exception:
            continue
        if count <= 0:
            continue
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        matched.append(locator)
    return matched


def locator_text(locator: Locator) -> str:
    """Return normalized inner text for a locator."""

    try:
        text = locator.inner_text(timeout=1500)
    except Exception:
        return ""
    return " ".join(text.split())


def relative_to_root(path: Path | None, root: Path) -> str:
    """Return a project-relative POSIX path when possible."""

    if path is None:
        return ""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)
