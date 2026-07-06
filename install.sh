#!/usr/bin/env bash
# Install Terminal Hub as two systemd services (terminal-hub + terminal-hub-ttyd).
#
# Usage:
#   ./install.sh [--dry-run]
#
# Configure via environment (all optional):
#   HUB_BIND_HOST   interface to bind to        (default 127.0.0.1)
#   HUB_BIND_PORT   UI port                      (default 8073)
#   HUB_TTYD_PORT   ttyd port                    (default 8071)
#
# There is NO authentication — set HUB_BIND_HOST to a trusted interface
# (a Tailscale/VPN IP, or keep 127.0.0.1 behind a reverse proxy).
#
#   HUB_BIND_HOST=100.x.y.z ./install.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="${SUDO_USER:-$USER}"
BIND_HOST="${HUB_BIND_HOST:-127.0.0.1}"
BIND_PORT="${HUB_BIND_PORT:-8073}"
TTYD_PORT="${HUB_TTYD_PORT:-8071}"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# --- dependencies ---
PYTHON_BIN="$(command -v python3 || true)"
TMUX_BIN="$(command -v tmux || true)"
TTYD_BIN="$(command -v ttyd || true)"
missing=""
[ -z "$PYTHON_BIN" ] && missing="$missing python3"
[ -z "$TMUX_BIN" ]   && missing="$missing tmux"
[ -z "$TTYD_BIN" ]   && missing="$missing ttyd"
if [ -n "$missing" ]; then
  if [ "$DRY_RUN" = 1 ]; then
    warn "missing dependencies:$missing (continuing for dry-run)"
    PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
    TTYD_BIN="${TTYD_BIN:-/usr/bin/ttyd}"
  else
    die "missing dependencies:$missing — install them and re-run."
  fi
fi

# --- local session targets ---
if [ ! -f "$REPO_DIR/targets.json" ]; then
  cp "$REPO_DIR/targets.example.json" "$REPO_DIR/targets.json"
  info "created targets.json — edit it to add ssh targets (the picker hides itself if only 'local' remains)"
fi

# --- render unit files from the .example templates ---
render_hub() {
  sed -e "s|YOUR_USER|$SERVICE_USER|g" \
      -e "s|/path/to/terminal-hub|$REPO_DIR|g" \
      -e "s|/usr/bin/python3|$PYTHON_BIN|g" \
      -e "s|HUB_BIND_HOST=127.0.0.1|HUB_BIND_HOST=$BIND_HOST|" \
      -e "s|HUB_BIND_PORT=8073|HUB_BIND_PORT=$BIND_PORT|" \
      -e "s|HUB_TTYD_PORT=8071|HUB_TTYD_PORT=$TTYD_PORT|" \
      "$REPO_DIR/systemd/terminal-hub.service.example"
}
render_ttyd() {
  sed -e "s|YOUR_USER|$SERVICE_USER|g" \
      -e "s|/path/to/terminal-hub|$REPO_DIR|g" \
      -e "s|/usr/bin/ttyd|$TTYD_BIN|" \
      -e "s|--port 8071|--port $TTYD_PORT|" \
      -e "s|--interface 127.0.0.1|--interface $BIND_HOST|" \
      "$REPO_DIR/systemd/terminal-hub-ttyd.service.example"
}

if [ "$DRY_RUN" = 1 ]; then
  info "user=$SERVICE_USER  dir=$REPO_DIR  host=$BIND_HOST  ui=$BIND_PORT  ttyd=$TTYD_PORT"
  echo "----- /etc/systemd/system/terminal-hub-ttyd.service -----"; render_ttyd
  echo "----- /etc/systemd/system/terminal-hub.service -----";      render_hub
  info "dry run — nothing installed."
  exit 0
fi

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

info "installing systemd units (user=$SERVICE_USER, host=$BIND_HOST)"
render_ttyd | $SUDO tee /etc/systemd/system/terminal-hub-ttyd.service >/dev/null
render_hub  | $SUDO tee /etc/systemd/system/terminal-hub.service      >/dev/null
$SUDO systemctl daemon-reload
$SUDO systemctl enable --now terminal-hub-ttyd.service terminal-hub.service

info "done. UI: http://$BIND_HOST:$BIND_PORT/"
[ "$BIND_HOST" = "127.0.0.1" ] && \
  warn "bound to localhost only — set HUB_BIND_HOST to reach it from your phone (e.g. a Tailscale IP)."
