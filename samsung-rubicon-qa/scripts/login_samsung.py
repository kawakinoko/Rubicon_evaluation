"""Launch a headed Samsung browser in Codespaces and persist Playwright storage state."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


DEFAULT_SIGNAL_FILE = ".secrets/login_complete.signal"
DEFAULT_STORAGE_STATE = ".secrets/samsung_storage_state.json"
DEFAULT_URL = "https://www.samsung.com/sec/"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Samsung landing page to open before login")
    parser.add_argument(
        "--project-root",
        default=Path(__file__).resolve().parent.parent,
        type=Path,
        help="Project root containing the .secrets directory",
    )
    parser.add_argument(
        "--storage-state",
        default=DEFAULT_STORAGE_STATE,
        help="Path relative to project root where Playwright storage state will be saved",
    )
    parser.add_argument(
        "--signal-file",
        default=DEFAULT_SIGNAL_FILE,
        help="Path relative to project root used as a non-interactive completion signal",
    )
    parser.add_argument(
        "--wait-timeout-sec",
        default=900,
        type=int,
        help="Maximum wait time for interactive login completion",
    )
    return parser.parse_args()


def wait_for_completion(signal_path: Path, timeout_sec: int) -> None:
    deadline = time.monotonic() + timeout_sec
    print("로그인이 끝나면 이 터미널에서 Enter 를 누르거나 신호 파일을 만들어 주세요.")
    print(f"신호 파일: {signal_path}")

    while time.monotonic() < deadline:
        if signal_path.exists():
            print("신호 파일을 감지했습니다. storage state 저장을 진행합니다.")
            return

        try:
            if sys.stdin in __import__("select").select([sys.stdin], [], [], 1.0)[0]:
                sys.stdin.readline()
                print("Enter 입력을 감지했습니다. storage state 저장을 진행합니다.")
                return
        except (OSError, ValueError):
            time.sleep(1)
            continue

    raise TimeoutError(f"로그인 완료 신호를 {timeout_sec}초 안에 받지 못했습니다.")


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    storage_state_path = (project_root / args.storage_state).resolve()
    signal_path = (project_root / args.signal_file).resolve()
    storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    signal_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(locale="ko-KR", viewport={"width": 1440, "height": 1200})
        page = context.new_page()

        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                pass

            print("Samsung 페이지를 열었습니다. Codespaces noVNC 화면에서 로그인하세요.")
            wait_for_completion(signal_path=signal_path, timeout_sec=args.wait_timeout_sec)
            context.storage_state(path=str(storage_state_path))
            print(f"저장 완료: {storage_state_path}")
        finally:
            if signal_path.exists():
                signal_path.unlink()
            context.close()
            browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())