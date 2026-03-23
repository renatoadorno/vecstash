#!/usr/bin/env bash
set -euo pipefail

# ── Constants ────────────────────────────────────────────────────────

REQUIRED_PYTHON_MAJOR=3
REQUIRED_PYTHON_MINOR=12
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.vecstash.daemon"
PLIST_SRC="${PROJECT_DIR}/support/${PLIST_NAME}.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/${PLIST_NAME}.plist"

# ── Helpers ──────────────────────────────────────────────────────────

info()  { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
ok()    { printf '\033[1;32m  ✓\033[0m %s\n' "$1"; }
error() { printf '\033[1;31mERROR:\033[0m %s\n' "$1" >&2; exit 1; }

# ── Step 1: Check architecture ───────────────────────────────────────

info "Checking architecture..."
ARCH="$(uname -m)"
if [ "$ARCH" != "arm64" ]; then
    error "Apple Silicon (arm64) is required. Detected: ${ARCH}"
fi
ok "arm64"

# ── Step 2: Check Python ────────────────────────────────────────────

info "Checking Python..."
if ! command -v python3 &>/dev/null; then
    error "python3 not found. Install Python ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}+ via:
  brew install python@${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}
  or: uv python install ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}"
fi
PY_VERSION="$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
PY_MAJOR="$(echo "$PY_VERSION" | cut -d. -f1)"
PY_MINOR="$(echo "$PY_VERSION" | cut -d. -f2)"
if [ "$PY_MAJOR" -lt "$REQUIRED_PYTHON_MAJOR" ] || \
   { [ "$PY_MAJOR" -eq "$REQUIRED_PYTHON_MAJOR" ] && [ "$PY_MINOR" -lt "$REQUIRED_PYTHON_MINOR" ]; }; then
    error "Python >= ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR} required. Found: ${PY_VERSION}"
fi
ok "Python ${PY_VERSION}"

# ── Step 3: Check uv ────────────────────────────────────────────────

info "Checking uv..."
if ! command -v uv &>/dev/null; then
    error "uv not found. Install via:
  brew install uv
  or: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi
ok "uv $(uv --version 2>/dev/null | head -1)"

# ── Step 4: Install vecstash ───────────────────────────────────────

info "Installing vecstash..."
uv tool install "${PROJECT_DIR}" --force
ok "Installed"

# ── Step 5: Verify binaries on PATH ─────────────────────────────────

info "Verifying binaries on PATH..."
if ! command -v vecstash &>/dev/null || ! command -v vecstash-daemon &>/dev/null; then
    error "Binaries not found on PATH. Run 'uv tool update-shell' and restart your terminal."
fi
ok "vecstash: $(which vecstash)"
ok "vecstash-daemon: $(which vecstash-daemon)"

# ── Step 6: Bootstrap model ─────────────────────────────────────────

info "Downloading embedding model (this may take a few minutes on first run)..."
vecstash models bootstrap
ok "Model ready"

# ── Step 7: Verify status ───────────────────────────────────────────

info "Verifying installation..."
vecstash status
ok "Status OK"

# ── Step 8: Install launchd plist ───────────────────────────────────

info "Setting up daemon auto-start via launchd..."
mkdir -p "${HOME}/Library/LaunchAgents"
sed "s|__HOME__|${HOME}|g" "${PLIST_SRC}" > "${PLIST_DST}"
launchctl bootout "gui/$(id -u)" "${PLIST_DST}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DST}"
ok "launchd plist installed"

# ── Step 9: Start daemon ────────────────────────────────────────────

info "Starting daemon..."
launchctl kickstart -k "gui/$(id -u)/${PLIST_NAME}" 2>/dev/null || true
sleep 2
if [ -S "${HOME}/.vecstash/daemon.sock" ]; then
    ok "Daemon is running"
else
    printf '\033[1;33m  ⚠\033[0m Daemon socket not found yet. It may take a moment to start.\n'
fi

# ── Done ─────────────────────────────────────────────────────────────

printf '\n'
info "Installation complete!"
printf '
  Commands:
    vecstash status          Check configuration and storage
    vecstash ingest <files>  Ingest documents
    vecstash models show     Show model configuration

  Daemon:
    The daemon is running in the background via launchd.
    It will restart automatically on login or crash.

    Test it:
      printf '"'"'{"jsonrpc":"2.0","id":1,"method":"healthcheck","params":{}}\n'"'"' | nc -U ~/.vecstash/daemon.sock

  Management:
    make status                    Show status
    make daemon-stop               Stop daemon
    make launchd-uninstall         Remove auto-start
    make uninstall                 Full uninstall
\n'
