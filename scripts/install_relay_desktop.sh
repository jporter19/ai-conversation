#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACK="$(cd "$ROOT/../../local/desktop-pack" && pwd)"
# shellcheck source=../../../local/desktop-pack/lib/install-common.sh
source "$PACK/lib/install-common.sh"

APP_ID="ai-conversation-relay"
SKIP_BUILD=0
[[ "${1:-}" == "--skip-build" ]] && SKIP_BUILD=1

install_custom_menu
VENV="${ROOT}/.venv"
ensure_venv "$VENV"
venv_pip "$VENV" install -q --upgrade pip
(cd "$ROOT" && venv_pip "$VENV" install -q -r "$ROOT/requirements.txt")
venv_pip "$VENV" install -q 'PySide6-Essentials' pyinstaller

DIST="$ROOT/dist/$APP_ID"
if [[ "$SKIP_BUILD" -eq 0 ]]; then
  (cd "$ROOT" && venv_pyinstaller "$VENV" --noconfirm ai-conversation-relay.spec)
fi
[[ -x "$DIST/$APP_ID" ]] || die "freeze missing: $DIST/$APP_ID"

install_onedir "$APP_ID" "$DIST" "$APP_ID"
install_hicolor_svg "$APP_ID" "$PACK/icons/ai-conversation-relay.svg"
# Drop the old loose PNG so the menu does not keep a dead absolute Icon=
rm -f "$HOME/.local/share/icons/ai-conversation-relay.png"

TMP="$(mktemp)"
render_desktop "$ROOT/packaging/ai-conversation-relay.desktop" "$TMP" "$XDG_BIN/$APP_ID" "$APP_ID"
install_desktop_file "$TMP" "$APP_ID.desktop"
rm -f "$TMP"
refresh_desktop
log "Installed $APP_ID → $XDG_BIN/$APP_ID"
