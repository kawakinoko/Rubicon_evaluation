"""Report generation for JSON, CSV, and Markdown summaries."""

from __future__ import annotations

import csv
from statistics import mean
from typing import Any

from app.config import AppConfig
from app.models import HarnessSummary, RunResult
from app.utils import write_json


def write_reports(
    config: AppConfig,
    run_results: list[RunResult],
    runtime_metadata: dict[str, str] | None = None,
    harness_summary: HarnessSummary | None = None,
) -> dict[str, str]:
    """Write the latest JSON, CSV, Markdown summary, and conversation report files."""

    json_path = config.reports_dir / "latest_results.json"
    csv_path = config.reports_dir / "latest_results.csv"
    summary_path = config.reports_dir / "summary.md"
    conversation_path = config.reports_dir / "latest_conversation.md"
    table_path = config.reports_dir / "latest_results_table.md"

    records = [result.to_result_record() for result in run_results]
    write_json(json_path, records)

    flat_rows = [result.to_flat_dict() for result in run_results]
    fieldnames = sorted({key for row in flat_rows for key in row.keys()})
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat_rows)

    summary_path.write_text(
        _build_summary(run_results, config, runtime_metadata=runtime_metadata, harness_summary=harness_summary),
        encoding="utf-8",
    )
    _write_latest_conversation(run_results, conversation_path, config, runtime_metadata=runtime_metadata)
    table_path.write_text(_build_results_table(run_results, runtime_metadata=runtime_metadata), encoding="utf-8")
    return {
        "json": str(json_path),
        "csv": str(csv_path),
        "summary": str(summary_path),
        "conversation": str(conversation_path),
        "table": str(table_path),
    }


def _write_latest_conversation(results: list[RunResult], path, config: AppConfig, runtime_metadata: dict[str, str] | None = None) -> None:
    path.write_text(_build_conversation(results, config, runtime_metadata=runtime_metadata), encoding="utf-8")


def _show_detailed_case(item: RunResult, config: AppConfig | None = None) -> bool:
    return item.pair.status != "passed" or item.pair.run_mode == "debug" or bool(getattr(config, "report_debug_fields_on_success", False))


def _format_flags(flags: list[str]) -> str:
    return " | ".join(flags) if flags else "(none)"


def _reason_text(result: RunResult) -> str:
    return result.evaluation.reason or result.pair.reason or "(none)"


def _fix_suggestion_text(result: RunResult) -> str:
    return result.evaluation.fix_suggestion or result.pair.fix_suggestion or "(none)"


def _score_text(result: RunResult) -> str:
    return f"{result.evaluation.overall_score:.1f} / 10"


def _score_breakdown_text(result: RunResult) -> str:
    evaluation = result.evaluation
    return (
        f"correctness={evaluation.correctness_score:.1f}, "
        f"relevance={evaluation.relevance_score:.1f}, "
        f"completeness={evaluation.completeness_score:.1f}, "
        f"clarity={evaluation.clarity_score:.1f}, "
        f"groundedness={evaluation.groundedness_score:.1f}"
    )


def _error_category_text(result: RunResult) -> str:
    return str(result.to_result_record().get("error_category", "(none)"))


def _primary_error_text(result: RunResult) -> str:
    if result.pair.primary_error_category and result.pair.primary_error_category != "(none)":
        return result.pair.primary_error_category
    return _error_category_text(result)


def _language_policy_check_text(result: RunResult) -> str:
    return str(result.to_result_record().get("language_policy_check", "pass"))


def _cleaning_applied_text(result: RunResult) -> str:
    return result.pair.cleaning_applied.replace("|", " | ") if result.pair.cleaning_applied else "(none)"


def _raw_clean_diff_text(result: RunResult) -> str:
    return result.pair.raw_clean_diff


def _final_answer_text(result: RunResult) -> str:
    return result.pair.final_answer or "(none)"


def _runtime_metadata_lines(runtime_metadata: dict[str, str] | None) -> list[str]:
    if not runtime_metadata:
        return []
    return [
        "",
        "## Runtime Metadata",
        "",
        f"- Branch: {runtime_metadata.get('branch', 'unknown')}",
        f"- Commit SHA: {runtime_metadata.get('commit_sha', 'unknown')}",
        f"- Extractor Version: {runtime_metadata.get('extractor_version', 'unknown')}",
        f"- Evaluator Version: {runtime_metadata.get('evaluator_version', 'unknown')}",
        f"- Harness Version: {runtime_metadata.get('harness_version', 'unknown')}",
        f"- Run Mode: {runtime_metadata.get('run_mode', 'unknown')}",
    ]


def _markdown_table_cell(value: Any, *, max_length: int = 100) -> str:
    text = str(value or "(none)").strip()
    if not text:
        text = "(none)"
    text = " ".join(text.split())
    if len(text) > max_length:
        text = f"{text[: max_length - 3].rstrip()}..."
    return text.replace("|", r"\|")


def _build_results_table(
    run_results: list[RunResult],
    runtime_metadata: dict[str, str] | None = None,
) -> str:
    lines = [
        "# Samsung Rubicon QA Results Table",
        "",
        "GitHub Actions 요약이나 빠른 결과 확인용 표다.",
    ]
    lines.extend(_runtime_metadata_lines(runtime_metadata))
    lines.extend(
        [
            "",
            "| Case | Question | Run | Extraction | Acceptance | Quality | Score | Final Answer | Reason |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )

    for item in run_results:
        pair = item.pair
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown_table_cell(pair.case_id, max_length=20),
                    _markdown_table_cell(pair.question, max_length=80),
                    _markdown_table_cell(pair.run_status, max_length=20),
                    _markdown_table_cell(pair.extraction_status, max_length=20),
                    _markdown_table_cell(pair.acceptance_status, max_length=20),
                    _markdown_table_cell(pair.quality_status, max_length=20),
                    _markdown_table_cell(f"{item.evaluation.overall_score:.1f}/10", max_length=12),
                    _markdown_table_cell(_final_answer_text(item), max_length=140),
                    _markdown_table_cell(_reason_text(item), max_length=120),
                ]
            )
            + " |"
        )

    if not run_results:
        lines.append("| (none) | (none) | (none) | (none) | (none) | (none) | 0.0/10 | (none) | 결과 없음 |")

    return "\n".join(lines) + "\n"


def _extraction_rejected_reason(result: RunResult) -> str:
    if result.pair.question_repetition_detected:
        return "question_repetition_detected"
    if result.pair.truncated_answer_detected:
        return "truncated_detected"
    return "(none)"


def format_case_console_block(result: RunResult) -> str:
    pair = result.pair
    evaluation = result.evaluation
    lines = ["=" * 50, f"CASE: {pair.case_id}", f"QUESTION: {pair.question}", f"STATUS: {pair.status}"]
    lines.extend(
        [
            f"RUN STATUS: {pair.run_status}",
            f"EXTRACTION STATUS: {pair.extraction_status}",
            f"ACCEPTANCE STATUS: {pair.acceptance_status}",
            f"QUALITY STATUS: {pair.quality_status}",
        ]
    )

    if pair.status == "passed":
        lines.extend(
            [
                f"ANSWER: {pair.final_answer}",
                f"EXTRACTION SOURCE: {pair.extraction_source}",
                f"SCORE: {_score_text(result)}",
                f"REASON: {_reason_text(result)}",
                f"FIX SUGGESTION: {_fix_suggestion_text(result)}",
                f"PRIMARY ERROR CATEGORY: {_primary_error_text(result)}",
                f"FLAGS: {'|'.join(evaluation.flags) if evaluation.flags else '(none)'}",
                f"NEEDS HUMAN REVIEW: {evaluation.needs_human_review}",
            ]
        )
    else:
        lines.extend(
            [
                f"INPUT DOM VERIFIED: {pair.input_dom_verified}",
                f"SUBMIT EFFECT VERIFIED: {pair.submit_effect_verified}",
                f"INPUT VERIFIED: {pair.input_verified}",
                f"INPUT METHOD: {pair.input_method_used or '(none)'}",
                f"SUBMIT METHOD USED: {pair.submit_method_used}",
                f"EVALUATION LANGUAGE: {evaluation.evaluation_language}",
                f"SCORE: {_score_text(result)}",
                f"SCORE BREAKDOWN: {_score_breakdown_text(result)}",
                f"SCORE BREAKDOWN EXPLANATION: {evaluation.score_breakdown_explanation or '(none)'}",
                f"REASON: {_reason_text(result)}",
                f"FIX SUGGESTION: {_fix_suggestion_text(result)}",
                f"PRIMARY ERROR CATEGORY: {pair.primary_error_category or _error_category_text(result)}",
                f"FLAGS: {'|'.join(evaluation.flags) if evaluation.flags else '(none)'}",
            ]
        )
    lines.append("CHECK FIRST: reports/latest_conversation.md")
    lines.append("=" * 50)
    return "\n".join(lines)


def _build_conversation(
    run_results: list[RunResult],
    config: AppConfig | None = None,
    runtime_metadata: dict[str, str] | None = None,
) -> str:
    """Build the main per-case evidence report for human review."""

    lines = [
        "# Samsung Rubicon QA Latest Conversation",
        "",
        "가장 먼저 확인해야 할 파일이다.",
        "이 파일에 질문, 입력 검증 여부, 새 응답 여부, 실제 답변, 평가 결과, 스크린샷 경로를 함께 기록한다.",
    ]
    lines.extend(_runtime_metadata_lines(runtime_metadata))

    for index, item in enumerate(run_results):
        pair = item.pair
        ev = item.evaluation
        heading_suffix = f" ({pair.case_id})"

        if not _show_detailed_case(item, config):
            if index != 0:
                lines.append("")
            lines.extend(
                [
                    f"## {pair.case_id}",
                    "",
                    f"- Question: {pair.question}",
                    f"- Final Answer: {_final_answer_text(item)}",
                    f"- Extraction Source: {pair.extraction_source}",
                    f"- Run Status: {pair.run_status}",
                    f"- Extraction Status: {pair.extraction_status}",
                    f"- Acceptance Status: {pair.acceptance_status}",
                    f"- Quality Status: {pair.quality_status}",
                    f"- Score: {_score_text(item)}",
                    f"- Reason: {_reason_text(item)}",
                    f"- Fix Suggestion: {_fix_suggestion_text(item)}",
                    f"- Primary Error Category: {_primary_error_text(item)}",
                    f"- Error Category: {_primary_error_text(item)}",
                    f"- Flags: {_format_flags(ev.flags)}",
                    f"- Needs Human Review: {ev.needs_human_review}",
                ]
            )
            if index != len(run_results) - 1:
                lines.append("")
            continue

        if index != 0:
            lines.append("")
        lines.extend(
            [
                f"## {pair.case_id}",
                "",
                f"- Question: {pair.question}",
                f"- Input DOM Verified: {pair.input_dom_verified}",
                f"- Submit Effect Verified: {pair.submit_effect_verified}",
                f"- Input Scope: {pair.input_scope or pair.input_scope_name or '(none)'}",
                f"- Input Selector: {pair.input_selector or '(none)'}",
                f"- Input Candidate Score: {pair.input_candidate_score}",
                f"- Input Failure Category: {pair.input_failure_category or '(none)'}",
                f"- Input Failure Reason: {pair.input_failure_reason or '(none)'}",
                f"- Top Candidate Placeholder: {pair.top_candidate_placeholder or '(none)'}",
                f"- Top Candidate Aria: {pair.top_candidate_aria or '(none)'}",
                f"- Input Ready Wait Attempted: {pair.transition_wait_attempted}",
                f"- Input Ready Wait Result: {pair.input_ready_wait_result or '(none)'}",
                f"- Input Verified: {pair.input_verified}",
                f"- Input Method: {pair.input_method_used or '(none)'}",
                f"- Submit Method Used: {pair.submit_method_used or 'unknown'}",
                f"- User Message Echo Verified: {pair.user_message_echo_verified}",
                f"- New Bot Response Detected: {pair.new_bot_response_detected}",
                f"- Failure Reason: {pair.reason or pair.input_failure_reason or pair.error_message or '(none)'}",
                f"- Top Candidate Disabled: {pair.top_candidate_disabled}",
                f"- Transition Ready: {pair.transition_ready}",
                f"- Transition Timeout: {pair.transition_timeout}",
                f"- Transition Reason: {pair.transition_reason or '(none)'}",
                f"- Transition History: {pair.transition_history or '(none)'}",
                f"- Activation Attempted: {pair.activation_attempted}",
                f"- Activation Steps Tried: {pair.activation_steps_tried or '(none)'}",
                f"- Editable Candidates Count: {pair.editable_candidates_count}",
                f"- Failover Attempts: {pair.failover_attempts}",
                f"- Final Input Target Frame: {pair.final_input_target_frame or '(none)'}",
                f"- SDK Status: {pair.sdk_status or '(none)'}",
                f"- Availability Status: {pair.availability_status or 'unknown'}",
                f"- Open Method Used: {pair.open_method_used or '(none)'}",
                f"- Status: {pair.status}",
                f"- Run Status: {pair.run_status}",
                f"- Extraction Status: {pair.extraction_status}",
                f"- Acceptance Status: {pair.acceptance_status}",
                f"- Quality Status: {pair.quality_status}",
                f"- Extraction Rejected Reason: {_extraction_rejected_reason(item)}",
                f"- Final Answer: {_final_answer_text(item)}",
                f"- Actual Answer: {pair.actual_answer or pair.final_answer or '(none)'}",
                f"- Actual Answer Clean: {pair.actual_answer_clean or pair.actual_answer or pair.final_answer or '(none)'}",
                f"- Raw Answer: {pair.debug_raw_answer or '(none)'}",
                f"- Cleaned Answer: {pair.debug_cleaned_answer or '(none)'}",
                f"- Raw/Clean Diff: {_raw_clean_diff_text(item)}",
                f"- Cleaning Applied: {_cleaning_applied_text(item)}",
                f"- Candidate Count: {pair.candidate_count}",
                f"- Selected Candidate Rank: {pair.selected_candidate_rank}",
                f"- question_repetition_detected: {pair.question_repetition_detected}",
                f"- truncated_detected: {pair.truncated_detected or pair.truncated_answer_detected}",
                f"- carryover_detected: {pair.carryover_detected}",
                f"- stale_answer_detected: {pair.stale_answer_detected}",
                f"- keyword_coverage_score: {pair.keyword_coverage_score:.2f}",
                f"- Answer Raw: {pair.answer_raw or '(none)'}",
                f"- Extraction Source: {pair.extraction_source}",
                f"- Message History Clean: {pair.message_history_clean or '(none)'}",
                f"- Evaluation Language: {ev.evaluation_language}",
                f"- Score: {_score_text(item)}",
                f"- Score Breakdown: {_score_breakdown_text(item)}",
                f"- Score Breakdown Explanation: {ev.score_breakdown_explanation or '(none)'}",
                f"- Reason: {_reason_text(item)}",
                f"- Fix Suggestion: {_fix_suggestion_text(item)}",
                f"- Primary Error Category: {_primary_error_text(item)}",
                f"- Error Category: {_primary_error_text(item)}",
                f"- Language Policy Check: {_language_policy_check_text(item)}",
                f"- Flags: {_format_flags(ev.flags)}",
                f"- Needs Human Review: {ev.needs_human_review}",
                f"- Screenshot Path: {pair.after_answer_screenshot_path or pair.before_send_screenshot_path or pair.opened_footer_screenshot_path or pair.chat_screenshot_path or '(none)'}",
                f"- Opened Footer Screenshot: {pair.opened_footer_screenshot_path or '(none)'}",
                f"- Before Send Screenshot: {pair.before_send_screenshot_path or '(none)'}",
                f"- After Answer Screenshot: {pair.after_answer_screenshot_path or '(none)'}",
                f"- Fullpage Screenshot: {pair.full_screenshot_path or pair.after_answer_full_screenshot_path or '(none)'}",
                f"- Chat Screenshot: {pair.chat_screenshot_path or '(none)'}",
                f"- Video Path: {pair.video_path or '(none)'}",
                "",
                f"### Input Candidates{heading_suffix}",
                "",
            ]
        )

        candidate_lines = [line for line in (pair.input_candidates_debug or "").splitlines() if line.strip()]
        if not candidate_lines and pair.input_candidate_logs:
            candidate_lines = pair.input_candidate_logs
        if candidate_lines:
            for candidate_log in candidate_lines[:10]:
                lines.append(f"- {candidate_log}")
        else:
            lines.append("- (empty)")

        lines.extend(
            [
                "",
                f"### Answer Extraction Debug{heading_suffix}",
                "",
                f"- selected_source={pair.extraction_source_detail or pair.extraction_source or 'unknown'}",
                f"- raw_len={len(pair.answer_raw or '')}",
                f"- clean_len={len(pair.actual_answer_clean or pair.actual_answer or pair.answer or '')}",
                f"- removed_followups={pair.removed_followups}",
                f"- noise_lines_removed={pair.noise_lines_removed}",
                "",
                f"### Message History{heading_suffix}",
                "",
            ]
        )

        if pair.message_history:
            for msg in pair.message_history:
                lines.append(f"- {msg}")
        else:
            lines.append("- (empty)")

        if index != len(run_results) - 1:
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _build_summary(
    run_results: list[RunResult],
    config: AppConfig | None = None,
    runtime_metadata: dict[str, str] | None = None,
    harness_summary: HarnessSummary | None = None,
) -> str:
    total = len(run_results)
    passed = sum(1 for item in run_results if item.pair.status == "passed")
    retry_extractions = sum(1 for item in run_results if item.pair.status == "retry_extraction")
    invalid_answers = sum(1 for item in run_results if item.pair.status == "invalid_answer")
    invalid_captures = sum(1 for item in run_results if item.pair.status == "invalid_capture")
    failures = sum(1 for item in run_results if item.pair.status == "failed")
    dom_successes = sum(1 for item in run_results if item.pair.extraction_source == "dom")
    ocr_used = sum(1 for item in run_results if item.pair.extraction_source == "ocr")
    human_review = sum(1 for item in run_results if item.evaluation.needs_human_review)
    new_response_detected = sum(1 for item in run_results if item.pair.new_bot_response_detected)
    avg_score = mean(item.evaluation.overall_score for item in run_results) if run_results else 0.0
    lowest = min(run_results, key=lambda item: item.evaluation.overall_score, default=None)
    error_cases = [item for item in run_results if item.pair.error_message]
    harness_summary = harness_summary or HarnessSummary(total_cases=total)

    lines = [
        "# Samsung Rubicon QA Summary",
        "",
        "결과 확인 우선순위: `reports/latest_conversation.md` -> `reports/latest_results.json` -> `reports/latest_results.csv` -> `reports/summary.md`",
        "성공 케이스는 스크린샷이나 비디오 경로가 비어 있어도 정상이며, 실패 케이스에서만 최소 증거 캡처가 남을 수 있다.",
        "",
    ]
    lines.extend(_runtime_metadata_lines(runtime_metadata))
    lines.extend([
        "",
        "## 집계",
        "",
        f"- 총 케이스 수: {total}",
        f"- passed 수: {passed}",
        f"- retry_extraction 수: {retry_extractions}",
        f"- invalid_answer 수: {invalid_answers}",
        f"- failed 수: {failures}",
        f"- invalid_capture 수: {invalid_captures}",
        f"- DOM 추출 성공 수: {dom_successes}",
        f"- OCR fallback 사용 수: {ocr_used}",
        f"- baseline 이후 새 응답 감지 수: {new_response_detected}",
        f"- 평균 overall score: {avg_score:.2f}",
        f"- human review 필요 건수: {human_review}",
        f"- run_ok count: {harness_summary.run_ok_count}",
        f"- answer_extracted count: {harness_summary.answer_extracted_count}",
        f"- answer_accepted count: {harness_summary.answer_accepted_count}",
        f"- quality_passed count: {harness_summary.quality_passed_count}",
        f"- accepted rate: {harness_summary.accepted_rate:.2%}",
        f"- quality pass rate: {harness_summary.quality_pass_rate:.2%}",
        f"- invalid answer rate: {harness_summary.invalid_answer_rate:.2%}",
        f"- ui_noise_leak count: {harness_summary.ui_noise_leak_count}",
        f"- truncation count: {harness_summary.truncation_count}",
        f"- carryover count: {harness_summary.carryover_count}",
        f"- speculative count: {harness_summary.speculative_count}",
    ])

    lines.extend(["", "## Primary Error Distribution", ""])
    if harness_summary.primary_error_distribution:
        for category, count in sorted(harness_summary.primary_error_distribution.items()):
            lines.append(f"- {category}: {count}")
    else:
        lines.append("- (none)")

    lines.extend(["", "## 케이스 요약", ""])
    if not run_results:
        lines.append("- 없음")
    else:
        for item in run_results:
            pair = item.pair
            evaluation = item.evaluation
            lines.extend(
                [
                    f"### {pair.case_id}",
                    "",
                    f"- Question: {pair.question}",
                    f"- Final Answer: {_final_answer_text(item)}",
                    f"- Extraction Source: {pair.extraction_source}",
                    f"- Run Status: {pair.run_status}",
                    f"- Extraction Status: {pair.extraction_status}",
                    f"- Acceptance Status: {pair.acceptance_status}",
                    f"- Quality Status: {pair.quality_status}",
                    f"- Score: {_score_text(item)}",
                    f"- Reason: {_reason_text(item)}",
                    f"- Fix Suggestion: {_fix_suggestion_text(item)}",
                    f"- Flags: {_format_flags(evaluation.flags)}",
                    f"- Needs Human Review: {evaluation.needs_human_review}",
                    f"- Primary Error Category: {_primary_error_text(item)}",
                    "",
                ]
            )

    if lowest is not None:
        lines.extend(
            [
                "",
                "## 최저 점수 케이스",
                "",
                f"- case_id: {lowest.pair.case_id}",
                f"- evaluation_language: {lowest.evaluation.evaluation_language}",
                f"- score: {_score_text(lowest)}",
                f"- score_breakdown: {_score_breakdown_text(lowest)}",
                f"- score_breakdown_explanation: {lowest.evaluation.score_breakdown_explanation or '(none)'}",
                f"- reason: {lowest.evaluation.reason}",
                f"- fix_suggestion: {_fix_suggestion_text(lowest)}",
                f"- flags: {_format_flags(lowest.evaluation.flags)}",
            ]
        )

    lines.extend(["", "## 에러 케이스", ""])
    if not error_cases:
        lines.append("- 없음")
    else:
        for item in error_cases:
            lines.append(f"- {item.pair.case_id}: {item.pair.error_message}")

    return "\n".join(lines).rstrip() + "\n"
