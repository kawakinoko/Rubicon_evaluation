#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${ROOT_DIR}/samsung-rubicon-qa"

if [[ ! -d "${PROJECT_DIR}" ]]; then
    printf 'Project directory not found: %s\n' "${PROJECT_DIR}" >&2
    exit 1
fi

exec bash "${PROJECT_DIR}/scripts/setup_and_run.sh" "$@"