"""Main orchestration for the Samsung Rubicon QA automation workflow."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

from app.browser import BrowserManager
from app.config import load_config
from app.csv_loader import load_test_cases
from app.dom_extractor import EXTRACTOR_VERSION
from app.evaluator import EVALUATOR_VERSION, build_input_not_verified_evaluation, detect_evaluation_language, evaluate_pair
from app.harness import HARNESS_VERSION, build_harness_summary, finalize_pair_for_harness
from app.logger import create_logger
from app.models import HarnessSummary, RunResult, RuntimeMetadata
from app.report_writer import format_case_console_block, write_reports
from app.samsung_rubicon import configure_runtime, run_single_case
from app.utils import artifact_timestamp, sanitize_filename


def _git_value(project_root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=project_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or "unknown"
    except Exception:
        return "unknown"


def _collect_runtime_metadata(project_root: Path, run_mode: str) -> RuntimeMetadata:
    return RuntimeMetadata(
        branch=_git_value(project_root, "rev-parse", "--abbrev-ref", "HEAD"),
        commit_sha=_git_value(project_root, "rev-parse", "HEAD"),
        extractor_version=EXTRACTOR_VERSION,
        evaluator_version=EVALUATOR_VERSION,
        harness_version=HARNESS_VERSION,
        run_mode=run_mode,
    )


def _display_path(project_root: Path, value: str) -> str:
    if not value:
        return ""
    target = Path(value)
    try:
        return str(target.relative_to(project_root))
    except Exception:
        return value


def _print_case_summary(project_root: Path, result: RunResult) -> None:
    del project_root
    print(format_case_console_block(result))


def _delete_artifact(path_value: str) -> None:
    if not path_value:
        return
    try:
        Path(path_value).unlink(missing_ok=True)
    except Exception:
        return


def _cleanup_success_artifacts(pair):
    removable_paths = [
        pair.full_screenshot_path,
        pair.chat_screenshot_path,
        pair.video_path,
        pair.trace_path,
        pair.html_fragment_path,
        pair.opened_chat_screenshot_path,
        pair.opened_full_screenshot_path,
        pair.opened_footer_screenshot_path,
        pair.before_send_screenshot_path,
        pair.before_send_full_screenshot_path,
        pair.after_send_screenshot_path,
        pair.after_send_full_screenshot_path,
        pair.after_answer_screenshot_path,
        pair.after_answer_full_screenshot_path,
        *pair.answer_screenshot_paths,
    ]
    for artifact_path in removable_paths:
        _delete_artifact(artifact_path)

    return replace(
        pair,
        full_screenshot_path="",
        chat_screenshot_path="",
        video_path="",
        trace_path="",
        html_fragment_path="",
        opened_chat_screenshot_path="",
        opened_full_screenshot_path="",
        opened_footer_screenshot_path="",
        before_send_screenshot_path="",
        before_send_full_screenshot_path="",
        after_send_screenshot_path="",
        after_send_full_screenshot_path="",
        after_answer_screenshot_path="",
        after_answer_full_screenshot_path="",
        answer_screenshot_paths=[],
        after_answer_multi_page=False,
    )


def _ensure_input_not_verified_flag(pair, evaluation, target_language: str):
    if pair.input_verified and "input_not_verified" not in evaluation.flags:
        return evaluation

    if pair.status == "invalid_capture" or not pair.submit_effect_verified or not pair.new_bot_response_detected:
        return build_input_not_verified_evaluation(
            pair.question,
            pair.locale,
            reason=evaluation.reason,
            fix_suggestion=evaluation.fix_suggestion,
        )

    if "input_not_verified" in evaluation.flags:
        return evaluation

    return replace(
        evaluation,
        score_scale="0-10",
        evaluation_language=target_language,
        flags=[*evaluation.flags, "input_not_verified"],
    )


def run(project_root: Path | None = None, return_summary: bool = False) -> list[RunResult] | tuple[list[RunResult], HarnessSummary]:
    """Execute the configured batch and return all case results."""

    config = load_config(project_root)
    config.ensure_directories()
    logger = create_logger(config.runtime_log_path)
    logger.info("app start")
    logger.info("config loaded")
    runtime_metadata = _collect_runtime_metadata(config.project_root, config.run_mode)
    logger.info(
        "runtime metadata: branch=%s commit=%s extractor=%s evaluator=%s run_mode=%s",
        runtime_metadata.branch,
        runtime_metadata.commit_sha,
        runtime_metadata.extractor_version,
        runtime_metadata.evaluator_version,
        runtime_metadata.run_mode,
    )

    test_cases = load_test_cases(
        config.questions_csv_path,
        max_questions=config.max_questions,
        selected_case_ids=config.selected_case_ids,
    )
    browser_manager = BrowserManager(config=config, logger=logger)
    browser_manager.start()
    configure_runtime(config, logger)

    results: list[RunResult] = []
    try:
        for test_case in test_cases:
            session = browser_manager.new_case_session(test_case.id)
            pair = run_single_case(session.page, test_case)
            target_language = detect_evaluation_language(test_case.question, pair.locale)

            timestamp = artifact_timestamp()
            safe_case_id = sanitize_filename(test_case.id)
            trace_target = config.trace_dir / f"{timestamp}_{safe_case_id}.zip" if config.enable_trace else None
            video_target = config.video_dir / f"{timestamp}_{safe_case_id}.webm" if config.video_recording_enabled else None

            trace_path, video_path = session.close(trace_target=trace_target, video_target=video_target)
            pair = replace(pair, trace_path=trace_path, video_path=video_path)
            if pair.status == "passed" and config.keep_only_failure_artifacts:
                pair = _cleanup_success_artifacts(pair)

            evaluation = _ensure_input_not_verified_flag(
                pair,
                evaluate_pair(config, test_case, pair, logger, target_language=target_language),
                target_language,
            )
            pair = finalize_pair_for_harness(test_case, pair, evaluation)
            run_result = RunResult(
                test_case=test_case,
                pair=pair,
                evaluation=evaluation,
                runtime_metadata=runtime_metadata,
            )
            results.append(run_result)
            _print_case_summary(config.project_root, run_result)
    finally:
        try:
            browser_manager.stop()
        except Exception as error:
            logger.warning("browser manager stop failed: %s", error)

    harness_summary = build_harness_summary(results)
    report_paths = write_reports(config, results, runtime_metadata={
        "branch": runtime_metadata.branch,
        "commit_sha": runtime_metadata.commit_sha,
        "extractor_version": runtime_metadata.extractor_version,
        "evaluator_version": runtime_metadata.evaluator_version,
        "harness_version": runtime_metadata.harness_version,
        "run_mode": runtime_metadata.run_mode,
    }, harness_summary=harness_summary)
    logger.info("report written")
    logger.info("check results in this order:")
    logger.info("1. %s", report_paths["conversation"])
    logger.info("2. %s", report_paths["json"])
    logger.info("3. %s", report_paths["csv"])
    logger.info("4. %s", report_paths["summary"])
    logger.info("5. %s", config.chatbox_dir)
    if return_summary:
        return results, harness_summary
    return results
