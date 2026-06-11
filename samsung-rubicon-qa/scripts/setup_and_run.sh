#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

START_VNC=0
LOGIN_ONLY=0
SETUP_ONLY=0
SKIP_PIP_INSTALL=0
SKIP_PLAYWRIGHT_INSTALL=0
INSTALL_KO_FONTS=0

usage() {
    cat <<'EOF'
Usage: bash scripts/setup_and_run.sh [options]

Options:
  --start-vnc               Start the Codespaces remote desktop before running.
  --login                   Open Samsung login helper and save storage state, then exit.
  --setup-only              Prepare the environment only, then exit.
  --skip-pip-install        Skip pip install -r requirements.txt.
  --skip-playwright-install Skip playwright chromium installation.
  --install-ko-fonts        Install Korean fonts with apt-get.
  -h, --help                Show this help message.

Examples:
  bash scripts/setup_and_run.sh
  bash scripts/setup_and_run.sh --start-vnc --login
  bash scripts/setup_and_run.sh --start-vnc
EOF
}

log() {
    printf '[setup_and_run] %s\n' "$*"
}

require_cmd() {
    local cmd="$1"
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "${cmd}" >&2
        exit 1
    fi
}

ensure_venv() {
    if [[ ! -d "${VENV_DIR}" ]]; then
        log "Creating virtual environment at ${VENV_DIR}"
        "${PYTHON_BIN}" -m venv "${VENV_DIR}"
    fi

    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"
}

ensure_env_file() {
    if [[ ! -f "${ROOT_DIR}/.env" ]]; then
        cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
        log "Created .env from .env.example. Fill OPENAI_API_KEY if evaluation is needed."
    fi

    if ! grep -Eq '^OPENAI_API_KEY=.+' "${ROOT_DIR}/.env"; then
        log "OPENAI_API_KEY is empty in .env. Browser run can continue, but GPT evaluation will fail."
    fi
}

maybe_install_fonts() {
    if [[ "${INSTALL_KO_FONTS}" -eq 0 ]]; then
        return
    fi

    require_cmd sudo
    require_cmd apt-get
    log "Installing Korean fonts"
    sudo apt-get update
    sudo apt-get install -y fonts-noto-cjk fonts-nanum
    fc-cache -f -v
}

start_vnc_desktop() {
    log "Starting remote browser desktop"
    bash "${ROOT_DIR}/scripts/start_vnc_browser.sh"
}

install_dependencies() {
    if [[ "${SKIP_PIP_INSTALL}" -eq 0 ]]; then
        log "Installing Python dependencies"
        python -m pip install --upgrade pip
        python -m pip install -r "${ROOT_DIR}/requirements.txt"
    fi

    if [[ "${SKIP_PLAYWRIGHT_INSTALL}" -eq 0 ]]; then
        log "Installing Playwright Chromium"
        python -m playwright install chromium
    fi
}

warn_display_if_needed() {
    local headless_value
    headless_value="$(grep -E '^HEADLESS=' "${ROOT_DIR}/.env" | tail -n 1 | cut -d '=' -f 2- || true)"
    if [[ "${headless_value,,}" == "false" ]] && [[ -z "${DISPLAY:-}" ]]; then
        log "HEADLESS=false and DISPLAY is not set. If you are in Codespaces, run with --start-vnc or export DISPLAY=:99."
    fi
}

run_login_flow() {
    log "Launching Samsung login helper"
    python "${ROOT_DIR}/scripts/login_samsung.py"
}

run_main() {
    local effective_run_mode
    effective_run_mode="${RUN_MODE:-standard}"

    if [[ ! -f "${ROOT_DIR}/.secrets/samsung_storage_state.json" ]]; then
        log "No saved Samsung session found at .secrets/samsung_storage_state.json"
        log "If login is required, run: bash scripts/setup_and_run.sh --start-vnc --login"
    fi

    if [[ -z "${RUN_MODE:-}" ]]; then
        log "RUN_MODE is not set; defaulting setup_and_run.sh execution to standard"
    else
        log "Using RUN_MODE=${effective_run_mode}"
    fi

    warn_display_if_needed
    log "Running Samsung Rubicon QA"
    cd "${ROOT_DIR}"
    RUN_MODE="${effective_run_mode}" python run.py
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --start-vnc)
            START_VNC=1
            ;;
        --login)
            LOGIN_ONLY=1
            ;;
        --setup-only)
            SETUP_ONLY=1
            ;;
        --skip-pip-install)
            SKIP_PIP_INSTALL=1
            ;;
        --skip-playwright-install)
            SKIP_PLAYWRIGHT_INSTALL=1
            ;;
        --install-ko-fonts)
            INSTALL_KO_FONTS=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n\n' "$1" >&2
            usage >&2
            exit 1
            ;;
    esac
    shift
done

require_cmd "${PYTHON_BIN}"

cd "${ROOT_DIR}"
maybe_install_fonts
ensure_venv
install_dependencies
ensure_env_file

if [[ "${START_VNC}" -eq 1 ]]; then
    start_vnc_desktop
fi

if [[ "${SETUP_ONLY}" -eq 1 ]]; then
    log "Environment setup completed"
    exit 0
fi

if [[ "${LOGIN_ONLY}" -eq 1 ]]; then
    run_login_flow
    exit 0
fi

run_main