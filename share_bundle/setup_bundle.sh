#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD_ZIP="${SCRIPT_DIR}/rubicon-evaluation-payload.zip"
TARGET_PARENT="${1:-${PWD}/bundle-output}"
BRANCH_NAME="${2:-import/rubicon-bundle}"
REMOTE_URL="${3:-}"
REPO_DIR="${TARGET_PARENT}/Rubicon_evaluation"

if [[ ! -f "${PAYLOAD_ZIP}" ]]; then
    printf 'Payload zip not found: %s\n' "${PAYLOAD_ZIP}" >&2
    exit 1
fi

if ! command -v unzip >/dev/null 2>&1; then
    printf 'unzip is required but not installed.\n' >&2
    exit 1
fi

if ! command -v git >/dev/null 2>&1; then
    printf 'git is required but not installed.\n' >&2
    exit 1
fi

mkdir -p "${TARGET_PARENT}"
unzip -oq "${PAYLOAD_ZIP}" -d "${TARGET_PARENT}"

if [[ ! -d "${REPO_DIR}" ]]; then
    printf 'Expected repo directory was not created: %s\n' "${REPO_DIR}" >&2
    exit 1
fi

if [[ ! -d "${REPO_DIR}/.git" ]]; then
    git -C "${REPO_DIR}" init -b main >/dev/null
fi

git -C "${REPO_DIR}" checkout -B "${BRANCH_NAME}" >/dev/null

if ! git -C "${REPO_DIR}" config user.name >/dev/null; then
    git -C "${REPO_DIR}" config user.name "Rubicon Bundle"
fi
if ! git -C "${REPO_DIR}" config user.email >/dev/null; then
    git -C "${REPO_DIR}" config user.email "bundle@local.invalid"
fi

if [[ -n "${REMOTE_URL}" ]]; then
    if git -C "${REPO_DIR}" remote get-url origin >/dev/null 2>&1; then
        git -C "${REPO_DIR}" remote set-url origin "${REMOTE_URL}"
    else
        git -C "${REPO_DIR}" remote add origin "${REMOTE_URL}"
    fi
fi

git -C "${REPO_DIR}" add .
if [[ -n "$(git -C "${REPO_DIR}" status --short)" ]]; then
    git -C "${REPO_DIR}" commit -m "Import Rubicon evaluation bundle" >/dev/null
fi

printf 'Bundle restored to %s\n' "${REPO_DIR}"
printf 'Active branch: %s\n' "${BRANCH_NAME}"
if [[ -n "${REMOTE_URL}" ]]; then
    printf 'Remote origin: %s\n' "${REMOTE_URL}"
fi
printf 'Next: cd %s && git push -u origin %s\n' "${REPO_DIR}" "${BRANCH_NAME}"