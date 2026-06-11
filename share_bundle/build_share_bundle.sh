#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
PAYLOAD_ROOT="${WORK_DIR}/Rubicon_evaluation"
PAYLOAD_ZIP="${WORK_DIR}/rubicon-evaluation-payload.zip"
BUNDLE_DIR="${WORK_DIR}/bundle"
OUTPUT_ZIP="${ROOT_DIR}/rubicon-qa-share.zip"

cleanup() {
    rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

mkdir -p "${PAYLOAD_ROOT}" "${BUNDLE_DIR}"

rsync -a \
    --exclude '.git/' \
    --exclude '.pytest_cache/' \
    --exclude '.vscode/' \
    --exclude 'rubicon-qa-share.zip' \
    --exclude 'samsung-rubicon-qa/.venv/' \
    --exclude 'samsung-rubicon-qa/__pycache__/' \
    --exclude 'samsung-rubicon-qa/tests/__pycache__/' \
    --exclude 'samsung-rubicon-qa/app/__pycache__/' \
    --exclude 'samsung-rubicon-qa/artifacts/' \
    --exclude 'samsung-rubicon-qa/reports/experiments/' \
    --exclude 'samsung-rubicon-qa/reports/isolated_runs/' \
    --exclude 'samsung-rubicon-qa/reports/rerun_backup/' \
    --exclude 'samsung-rubicon-qa/reports/*.log' \
    --exclude 'samsung-rubicon-qa/reports/latest_conversation.md' \
    --exclude 'samsung-rubicon-qa/reports/latest_results.json' \
    --exclude 'samsung-rubicon-qa/reports/latest_results.csv' \
    --exclude 'samsung-rubicon-qa/reports/latest_results_detailed.csv' \
    --exclude 'samsung-rubicon-qa/reports/latest_results_table.md' \
    --exclude 'samsung-rubicon-qa/reports/summary.md' \
    --exclude 'share_bundle/' \
    "${ROOT_DIR}/" "${PAYLOAD_ROOT}/"

(
    cd "${WORK_DIR}"
    zip -rq "${PAYLOAD_ZIP}" Rubicon_evaluation
)

cp "${ROOT_DIR}/share_bundle/setup_bundle.sh" "${BUNDLE_DIR}/setup_bundle.sh"
cp "${ROOT_DIR}/share_bundle/setup_bundle.bat" "${BUNDLE_DIR}/setup_bundle.bat"
cp "${ROOT_DIR}/share_bundle/BUNDLE_README.txt" "${BUNDLE_DIR}/README.txt"
cp "${PAYLOAD_ZIP}" "${BUNDLE_DIR}/rubicon-evaluation-payload.zip"

rm -f "${OUTPUT_ZIP}"
(
    cd "${BUNDLE_DIR}"
    zip -rq "${OUTPUT_ZIP}" .
)

printf 'Created %s\n' "${OUTPUT_ZIP}"