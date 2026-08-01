#!/usr/bin/env bash
# Install a desktop launcher + optional autostart for the transcript relay tray app.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${ROOT}/.venv/bin/python"
APP="${ROOT}/scripts/transcript_relay_app.py"
ICON_DIR="${HOME}/.local/share/icons"
APP_DIR="${HOME}/.local/share/applications"
AUTOSTART_DIR="${HOME}/.config/autostart"

if [[ ! -x "$PY" ]]; then
  echo "Missing venv python at $PY — run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt PySide6-Essentials" >&2
  exit 1
fi

"$PY" -c "from PySide6.QtWidgets import QApplication" 2>/dev/null || {
  echo "Installing PySide6-Essentials…"
  "$PY" -m pip install -q 'PySide6-Essentials'
}

mkdir -p "$ICON_DIR" "$APP_DIR"
# Generate a simple PNG icon via the app's painter (inline)
"$PY" - <<'PY'
from pathlib import Path
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, Qt
from PySide6.QtWidgets import QApplication
import sys
app = QApplication(sys.argv)
pix = QPixmap(128, 128)
pix.fill(Qt.GlobalColor.transparent)
p = QPainter(pix)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
p.setBrush(QColor("#3b82f6"))
p.setPen(Qt.PenStyle.NoPen)
p.drawEllipse(8, 8, 112, 112)
p.setPen(QColor("#ffffff"))
f = p.font(); f.setBold(True); f.setPointSize(36); p.setFont(f)
p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "YT")
p.end()
out = Path.home() / ".local" / "share" / "icons" / "ai-conversation-relay.png"
out.parent.mkdir(parents=True, exist_ok=True)
pix.save(str(out))
print(out)
PY

DESKTOP="${APP_DIR}/ai-conversation-relay.desktop"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=AI Conversation Transcript Relay
Comment=Start/stop home YouTube transcript relay for AWS hub
Exec=${PY} ${APP}
Icon=${ICON_DIR}/ai-conversation-relay.png
Terminal=false
Categories=Network;Utility;
StartupNotify=true
EOF
chmod +x "$DESKTOP"

echo "Installed launcher: $DESKTOP"
echo "Search your app menu for: AI Conversation Transcript Relay"
echo
echo "Optional — copy to autostart so it runs on login:"
echo "  mkdir -p ${AUTOSTART_DIR}"
echo "  cp ${DESKTOP} ${AUTOSTART_DIR}/"
echo
echo "Run now:"
echo "  ${PY} ${APP}"
