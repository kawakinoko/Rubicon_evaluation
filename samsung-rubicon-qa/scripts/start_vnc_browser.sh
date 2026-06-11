#!/usr/bin/env bash

set -euo pipefail

DISPLAY_NUM="${DISPLAY_NUM:-99}"
DISPLAY=":${DISPLAY_NUM}"
SCREEN_GEOMETRY="${SCREEN_GEOMETRY:-1440x1200x24}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
PID_DIR="${PID_DIR:-.codespaces-vnc}"
LOG_DIR="${LOG_DIR:-${PID_DIR}/logs}"

mkdir -p "${PID_DIR}" "${LOG_DIR}"

require_cmd() {
    local cmd="$1"
    if command -v "${cmd}" >/dev/null 2>&1; then
        return
    fi

    if [[ "${cmd}" == "websockify" ]] && python3 -m websockify --help >/dev/null 2>&1; then
        return
    fi

    echo "Missing required command: ${cmd}" >&2
    echo "Install the desktop stack first, for example:" >&2
    echo "  sudo apt-get update" >&2
    echo "  sudo apt-get install -y xvfb fluxbox x11vnc novnc websockify" >&2
    exit 1
}

kill_if_running() {
    local pid_file="$1"
    if [[ -f "${pid_file}" ]]; then
        local pid
        pid="$(cat "${pid_file}")"
        if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
            kill "${pid}" >/dev/null 2>&1 || true
            wait "${pid}" 2>/dev/null || true
        fi
        rm -f "${pid_file}"
    fi
}

find_novnc_web() {
    local candidate
    for candidate in \
        "/usr/share/novnc" \
        "/usr/share/novnc/utils/../" \
        "/opt/novnc"; do
        if [[ -f "${candidate}/vnc.html" ]]; then
            printf '%s\n' "$(cd "${candidate}" && pwd)"
            return 0
        fi
    done
    return 1
}

require_cmd Xvfb
require_cmd fluxbox
require_cmd x11vnc

if ! NOVNC_WEB="$(find_novnc_web)"; then
    echo "Could not find noVNC web assets." >&2
    echo "Install the noVNC package, for example: sudo apt-get install -y novnc websockify" >&2
    exit 1
fi

if command -v websockify >/dev/null 2>&1; then
    WEBSOCKIFY_CMD=(websockify)
elif python3 -m websockify --help >/dev/null 2>&1; then
    WEBSOCKIFY_CMD=(python3 -m websockify)
else
    echo "websockify is not available." >&2
    exit 1
fi

export DISPLAY

kill_if_running "${PID_DIR}/xvfb.pid"
kill_if_running "${PID_DIR}/fluxbox.pid"
kill_if_running "${PID_DIR}/x11vnc.pid"
kill_if_running "${PID_DIR}/websockify.pid"

Xvfb "${DISPLAY}" -screen 0 "${SCREEN_GEOMETRY}" -nolisten tcp -ac >"${LOG_DIR}/xvfb.log" 2>&1 &
echo $! > "${PID_DIR}/xvfb.pid"

for _ in $(seq 1 20); do
    if xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

fluxbox >"${LOG_DIR}/fluxbox.log" 2>&1 &
echo $! > "${PID_DIR}/fluxbox.pid"

x11vnc -display "${DISPLAY}" -rfbport "${VNC_PORT}" -forever -shared -nopw >"${LOG_DIR}/x11vnc.log" 2>&1 &
echo $! > "${PID_DIR}/x11vnc.pid"

"${WEBSOCKIFY_CMD[@]}" --web "${NOVNC_WEB}" "${NOVNC_PORT}" "localhost:${VNC_PORT}" >"${LOG_DIR}/websockify.log" 2>&1 &
echo $! > "${PID_DIR}/websockify.pid"

cat <<EOF
Remote browser desktop is starting.

DISPLAY=${DISPLAY}
VNC_PORT=${VNC_PORT}
NOVNC_PORT=${NOVNC_PORT}
noVNC URL: http://127.0.0.1:${NOVNC_PORT}/vnc.html

If you are in GitHub Codespaces, open the forwarded port ${NOVNC_PORT} in the browser.
Keep this desktop running while you complete Samsung account login in the remote Chromium window.
EOF