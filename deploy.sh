#!/usr/bin/env bash
set -euo pipefail

APP_NAME="window-bot"
DEFAULT_INSTALL_DIR="/opt/window-bot"
DEFAULT_CONFIG_DIR="/etc/window-bot"
DEFAULT_SERVICE_PATH="/etc/systemd/system/window-bot.service"
DEFAULT_STATE_PATH="/var/lib/window-bot/window-bot-state.json"

SCRIPT_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
  pwd -P
)"

INSTALL_DIR="${WINDOW_BOT_INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
CONFIG_DIR="${WINDOW_BOT_CONFIG_DIR:-$DEFAULT_CONFIG_DIR}"
SERVICE_PATH="${WINDOW_BOT_SERVICE_PATH:-$DEFAULT_SERVICE_PATH}"
STATE_PATH="${WINDOW_BOT_STATE_PATH:-$DEFAULT_STATE_PATH}"
PYTHON_BIN="${WINDOW_BOT_PYTHON:-python3}"
UNIT_NAME="$(basename -- "${SERVICE_PATH}")"

NO_SYNC=0
SKIP_SYSTEMD=0

log() {
  printf '[%s] %s\n' "$APP_NAME" "$*"
}

die() {
  printf '[%s] ERROR: %s\n' "$APP_NAME" "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: ./deploy.sh [options]

Installs/updates window-bot on a Raspberry Pi (or other systemd Linux host).
Defaults:
  code:   /opt/window-bot
  config: /etc/window-bot
  unit:   /etc/systemd/system/window-bot.service

Options:
  --no-sync         Do not copy this repo into /opt/window-bot
  --skip-systemd    Do not install/enable the systemd unit
  -h, --help        Show this help

Environment overrides:
  WINDOW_BOT_INSTALL_DIR   (default: /opt/window-bot)
  WINDOW_BOT_CONFIG_DIR    (default: /etc/window-bot)
  WINDOW_BOT_SERVICE_PATH  (default: /etc/systemd/system/window-bot.service)
  WINDOW_BOT_STATE_PATH    (default: /var/lib/window-bot/window-bot-state.json)
  WINDOW_BOT_PYTHON        (default: python3)
EOF
}

require_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    return
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    die "Must run as root (sudo not found)."
  fi
  exec sudo -E bash "${SCRIPT_DIR}/deploy.sh" "$@"
}

require_repo_root() {
  [[ -f "${SCRIPT_DIR}/pyproject.toml" ]] || die "Run from a window-bot repo checkout (missing pyproject.toml)."
  [[ -f "${SCRIPT_DIR}/config.example.toml" ]] || die "Missing config.example.toml; is this the repo root?"
  [[ -f "${SCRIPT_DIR}/contrib/window-bot.service" ]] || die "Missing contrib/window-bot.service; is this the repo root?"
}

require_python_311() {
  command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Missing ${PYTHON_BIN}. Install Python 3.11+."
  "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1 || die "Python 3.11+ is required (tomllib)."
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY
}

empty_install_dir() {
  [[ "${INSTALL_DIR}" == /* ]] || die "INSTALL_DIR must be an absolute path (got: ${INSTALL_DIR})"
  case "${INSTALL_DIR}" in
    /|/bin|/boot|/dev|/etc|/home|/lib|/lib64|/media|/mnt|/opt|/proc|/root|/run|/sbin|/sys|/tmp|/usr|/var)
      die "Refusing to clear unsafe INSTALL_DIR: ${INSTALL_DIR}"
      ;;
  esac

  rm -rf --one-file-system \
    "${INSTALL_DIR:?}/"* \
    "${INSTALL_DIR:?}/".[!.]* \
    "${INSTALL_DIR:?}/"..?* \
    2>/dev/null || true
}

sync_repo() {
  if [[ "$NO_SYNC" -eq 1 ]]; then
    log "Skipping repo sync (--no-sync)."
    return
  fi

  if [[ "${SCRIPT_DIR}" == "${INSTALL_DIR}" ]]; then
    log "Repo already at ${INSTALL_DIR}; skipping sync."
    return
  fi

  log "Syncing repo to ${INSTALL_DIR} ..."
  install -d -m 0755 "${INSTALL_DIR}"

  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
      --exclude '.git/' \
      --exclude '.venv/' \
      --exclude '__pycache__/' \
      --exclude '*.pyc' \
      --exclude '.env' \
      --exclude 'config.toml' \
      --exclude 'state/' \
      --exclude 'tests/' \
      "${SCRIPT_DIR}/" "${INSTALL_DIR}/"
    return
  fi

  log "rsync not found; falling back to tar copy."
  empty_install_dir
  tar \
    --exclude-vcs \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.env' \
    --exclude 'config.toml' \
    --exclude 'state' \
    --exclude 'tests' \
    -C "${SCRIPT_DIR}" -cf - . | tar -C "${INSTALL_DIR}" -xf -
}

install_config_files() {
  log "Ensuring config directory at ${CONFIG_DIR} ..."
  install -d -m 0755 "${CONFIG_DIR}"

  local config_path="${CONFIG_DIR}/config.toml"
  if [[ ! -f "${config_path}" ]]; then
    log "Installing default config to ${config_path} ..."
    sed -E \
      "s|^state_file\\s*=\\s*\"state/window-bot-state\\.json\"\\s*$|state_file = \"${STATE_PATH}\"|" \
      "${INSTALL_DIR}/config.example.toml" >"${config_path}"
  else
    log "Config already exists at ${config_path}; leaving unchanged."
  fi

  local env_path="${CONFIG_DIR}/window-bot.env"
  if [[ ! -f "${env_path}" ]]; then
    log "Installing env template to ${env_path} ..."
    install -m 0600 "${INSTALL_DIR}/contrib/window-bot.env.example" "${env_path}"
  else
    log "Env file already exists at ${env_path}; leaving unchanged."
    chmod 0600 "${env_path}" || true
  fi

  log "Ensuring state directory exists for ${STATE_PATH} ..."
  install -d -m 0755 "$(dirname -- "${STATE_PATH}")"
}

install_systemd_unit() {
  if [[ "$SKIP_SYSTEMD" -eq 1 ]]; then
    log "Skipping systemd install (--skip-systemd)."
    return
  fi

  command -v systemctl >/dev/null 2>&1 || die "systemctl not found; cannot install service."

  log "Installing systemd unit to ${SERVICE_PATH} ..."
  install -d -m 0755 "$(dirname -- "${SERVICE_PATH}")"
  local unit_tmp
  unit_tmp="$(mktemp)"
  sed \
    -e "s|/opt/window-bot|${INSTALL_DIR}|g" \
    -e "s|/etc/window-bot|${CONFIG_DIR}|g" \
    "${INSTALL_DIR}/contrib/window-bot.service" >"${unit_tmp}"
  install -m 0644 "${unit_tmp}" "${SERVICE_PATH}"
  rm -f "${unit_tmp}"

  log "Reloading systemd ..."
  systemctl daemon-reload

  log "Enabling and restarting ${UNIT_NAME} ..."
  systemctl enable "${UNIT_NAME}"
  systemctl restart "${UNIT_NAME}"

  log "Tip: view logs with: journalctl -u ${UNIT_NAME} -f"
}

main() {
  require_repo_root
  require_root "$@"

  while [[ "${#}" -gt 0 ]]; do
    case "$1" in
      --no-sync) NO_SYNC=1 ;;
      --skip-systemd) SKIP_SYSTEMD=1 ;;
      -h|--help)
        usage
        return 0
        ;;
      *)
        die "Unknown option: $1 (try --help)"
        ;;
    esac
    shift
  done

  require_python_311

  # Stop service early to avoid running code being swapped underneath it.
  if command -v systemctl >/dev/null 2>&1; then
    systemctl stop "${UNIT_NAME}" >/dev/null 2>&1 || true
  fi

  sync_repo
  install_config_files
  install_systemd_unit

  log "Done."
}

main "$@"
