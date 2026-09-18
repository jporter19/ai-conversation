#!/usr/bin/env python3
"""
Desktop controller for the YouTube transcript home relay.

Opens a reverse SSH tunnel from your home PC to the cloud hub
(Lightsail or EC2) so the hub can fetch YouTube transcripts via your
residential IP.

- System tray icon
- Tabs for Lightsail and EC2 connection settings
- Settings saved under ~/.config/ai-conversation/relay_app.json

Run (from repo, with venv):
  .venv/bin/python scripts/transcript_relay_app.py
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Qt ────────────────────────────────────────────────────────────────────────
try:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSystemTrayIcon,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
        QMenu,
        QFileDialog,
    )
except ImportError:
    print(
        "PySide6 is required. Install with:\n"
        "  .venv/bin/pip install PySide6-Essentials",
        file=sys.stderr,
    )
    raise SystemExit(1)

def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _runtime_root() -> Path:
    if _frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def _default_python() -> str:
    if _frozen():
        return sys.executable
    venv = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python"
    return str(venv) if venv.is_file() else sys.executable


def _relay_script() -> Path:
    if _frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "transcript_relay.py"
    return Path(__file__).resolve().parent / "transcript_relay.py"


ROOT = _runtime_root()
CONFIG_DIR = Path.home() / ".config" / "ai-conversation"
CONFIG_PATH = CONFIG_DIR / "relay_app.json"

# Per-cloud-hub connection profile
TARGET_KEYS = ("deploy_host", "deploy_user", "deploy_key", "relay_port", "relay_token")

TARGET_PRESETS: Dict[str, Dict[str, Any]] = {
    "lightsail": {
        "label": "Lightsail",
        "deploy_host": "54.175.0.107",
        "deploy_user": "ec2-user",
        "deploy_key": str(Path.home() / ".ssh" / "lightsail-ai-hub.pem"),
        "relay_port": 8791,
        "relay_token": "",
    },
    "ec2": {
        "label": "EC2",
        "deploy_host": "44.208.175.27",
        "deploy_user": "ec2-user",
        "deploy_key": str(Path.home() / ".ssh" / "grok-small-ec2.pem"),
        "relay_port": 8791,
        "relay_token": "",
    },
}

DEFAULTS: Dict[str, Any] = {
    "active_target": "lightsail",
    "targets": deepcopy(TARGET_PRESETS),
    "python_bin": _default_python(),
    "autostart": False,
    "start_minimized": False,
}


def _blank_target(preset_id: str) -> Dict[str, Any]:
    base = deepcopy(TARGET_PRESETS.get(preset_id) or TARGET_PRESETS["lightsail"])
    return base


def load_config() -> Dict[str, Any]:
    """Load config; migrate flat EC2-era keys into targets.lightsail / targets.ec2."""
    cfg = deepcopy(DEFAULTS)
    raw: Dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                raw = data
        except (json.JSONDecodeError, OSError):
            raw = {}

    # Shared fields
    for k in ("python_bin", "autostart", "start_minimized", "active_target"):
        if k in raw:
            cfg[k] = raw[k]

    # New multi-target shape
    if isinstance(raw.get("targets"), dict) and raw["targets"]:
        for tid, preset in TARGET_PRESETS.items():
            t = deepcopy(preset)
            incoming = raw["targets"].get(tid) or {}
            if isinstance(incoming, dict):
                for k in TARGET_KEYS:
                    if k in incoming and incoming[k] is not None:
                        t[k] = incoming[k]
                if incoming.get("label"):
                    t["label"] = incoming["label"]
            cfg["targets"][tid] = t
        # Preserve any custom target ids (optional)
        for tid, incoming in raw["targets"].items():
            if tid not in cfg["targets"] and isinstance(incoming, dict):
                t = _blank_target("lightsail")
                t.update({k: incoming[k] for k in TARGET_KEYS if k in incoming})
                t["label"] = incoming.get("label") or tid
                cfg["targets"][tid] = t
    else:
        # Legacy flat config (single deploy_host / key / token)
        legacy_host = (raw.get("deploy_host") or "").strip()
        legacy_user = (raw.get("deploy_user") or "ec2-user").strip()
        legacy_key = (raw.get("deploy_key") or "").strip()
        legacy_port = raw.get("relay_port", 8791)
        legacy_token = (raw.get("relay_token") or "").strip()
        try:
            legacy_port = int(legacy_port)
        except (TypeError, ValueError):
            legacy_port = 8791

        # Guess which target the old host belonged to
        active = "lightsail"
        if legacy_host in ("44.208.175.27",) or "ec2" in legacy_key.lower() or "grok-small" in legacy_key:
            active = "ec2"
        elif legacy_host in ("54.175.0.107",) or "lightsail" in legacy_key.lower():
            active = "lightsail"
        cfg["active_target"] = active

        if legacy_host or legacy_key or legacy_token:
            t = dict(cfg["targets"][active])
            if legacy_host:
                t["deploy_host"] = legacy_host
            if legacy_user:
                t["deploy_user"] = legacy_user
            if legacy_key:
                t["deploy_key"] = legacy_key
            t["relay_port"] = legacy_port
            if legacy_token:
                t["relay_token"] = legacy_token
            cfg["targets"][active] = t
            # Shared token applies to every hub — copy into other tabs so
            # switching to Lightsail/EC2 does not look "missing".
            if legacy_token:
                for tid, other in cfg["targets"].items():
                    if not (other.get("relay_token") or "").strip():
                        other["relay_token"] = legacy_token

    if cfg.get("active_target") not in cfg["targets"]:
        cfg["active_target"] = "lightsail"

    # Prefer token from env if a target has none
    env_tok = (os.environ.get("YOUTUBE_TRANSCRIPT_RELAY_TOKEN") or "").strip()
    if env_tok:
        for tid, t in cfg["targets"].items():
            if not (t.get("relay_token") or "").strip():
                t["relay_token"] = env_tok

    # If any tab has a token and another does not, share it (one secret for the hub)
    any_tok = ""
    for t in cfg["targets"].values():
        if (t.get("relay_token") or "").strip():
            any_tok = t["relay_token"].strip()
            break
    if any_tok:
        for t in cfg["targets"].values():
            if not (t.get("relay_token") or "").strip():
                t["relay_token"] = any_tok

    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass


def make_icon(color: str = "#3b82f6") -> QIcon:
    """Simple tray/window icon (no external assets)."""
    size = 64
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(4, 4, size - 8, size - 8)
    p.setPen(QColor("#ffffff"))
    font = p.font()
    font.setBold(True)
    font.setPointSize(18)
    p.setFont(font)
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "YT")
    p.end()
    return QIcon(pix)


# Cap tray UI log growth (unbounded QTextEdit was a freeze risk).
MAX_LOG_BLOCKS = 400
# Recreate tray icons only when color changes (was every 1s → memory/CPU pressure).
_ICON_CACHE: Dict[str, QIcon] = {}


def icon_for(color: str) -> QIcon:
    if color not in _ICON_CACHE:
        _ICON_CACHE[color] = make_icon(color)
    return _ICON_CACHE[color]


class ProcessSlot:
    """Tracks one subprocess and its log pump."""

    def __init__(self, name: str):
        self.name = name
        self.proc: Optional[subprocess.Popen] = None
        self.pump_generation: int = 0  # invalidate pending log timers on stop/restart

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, timeout: float = 5.0) -> None:
        self.pump_generation += 1  # stop scheduled _pump_output callbacks
        if not self.proc:
            return
        proc = self.proc
        self.proc = None
        if proc.poll() is None:
            try:
                proc.send_signal(signal.SIGTERM)
            except OSError:
                pass
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        # Close pipes so the child cannot block on a full pipe buffer
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass


class TargetTab(QWidget):
    """Connection settings for one cloud hub (Lightsail or EC2)."""

    def __init__(self, target_id: str, data: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.target_id = target_id
        form = QFormLayout(self)

        self.host_edit = QLineEdit(str(data.get("deploy_host") or ""))
        self.user_edit = QLineEdit(str(data.get("deploy_user") or "ec2-user"))
        self.key_edit = QLineEdit(str(data.get("deploy_key") or ""))
        self.port_edit = QLineEdit(str(data.get("relay_port") or 8791))
        self.token_edit = QLineEdit(str(data.get("relay_token") or ""))
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)

        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit)
        key_browse = QPushButton("Browse…")
        key_browse.clicked.connect(self._browse_key)
        key_row.addWidget(key_browse)
        key_wrap = QWidget()
        key_wrap.setLayout(key_row)

        host_label = "Static IP / host" if target_id == "lightsail" else "Elastic IP / host"
        form.addRow(host_label, self.host_edit)
        form.addRow("SSH user", self.user_edit)
        form.addRow("SSH key (.pem)", key_wrap)
        form.addRow("Relay port", self.port_edit)
        form.addRow("Shared token", self.token_edit)

        hint = QLabel(
            "Token must match YOUTUBE_TRANSCRIPT_RELAY_TOKEN on the hub "
            "(/etc/ai-conversation/env). Hub URL stays http://127.0.0.1:PORT."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b; font-size: 12px;")
        form.addRow(hint)

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select SSH private key",
            str(Path.home() / ".ssh"),
            "PEM / key files (*.pem *);;All files (*)",
        )
        if path:
            self.key_edit.setText(path)

    def collect(self) -> Dict[str, Any]:
        try:
            port = int(self.port_edit.text().strip() or "8791")
        except ValueError:
            port = 8791
        return {
            "label": TARGET_PRESETS.get(self.target_id, {}).get("label") or self.target_id,
            "deploy_host": self.host_edit.text().strip(),
            "deploy_user": self.user_edit.text().strip() or "ec2-user",
            "deploy_key": self.key_edit.text().strip(),
            "relay_port": port,
            "relay_token": self.token_edit.text().strip(),
        }

    def apply_data(self, data: Dict[str, Any]) -> None:
        self.host_edit.setText(str(data.get("deploy_host") or ""))
        self.user_edit.setText(str(data.get("deploy_user") or "ec2-user"))
        self.key_edit.setText(str(data.get("deploy_key") or ""))
        self.port_edit.setText(str(data.get("relay_port") or 8791))
        self.token_edit.setText(str(data.get("relay_token") or ""))


class RelayControllerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AI Conversation — Transcript Relay")
        self.setMinimumSize(560, 560)
        self.setWindowIcon(make_icon())

        self.cfg = load_config()
        self.relay = ProcessSlot("relay")
        self.tunnel = ProcessSlot("tunnel")
        self._target_tabs: Dict[str, TargetTab] = {}
        self._last_tray_color = ""

        intro = QLabel(
            "Home YouTube relay for the cloud hub. "
            "Choose <b>Lightsail</b> or <b>EC2</b>, save settings, then Start both. "
            "The tunnel uses SSH reverse port-forward so the hub calls "
            "<code>127.0.0.1</code> while YouTube sees your home IP."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)

        # ── tabs: Lightsail | EC2 ───────────────────────────────────────────
        self.tabs = QTabWidget()
        order: List[str] = ["lightsail", "ec2"]
        for tid in order:
            data = self.cfg.get("targets", {}).get(tid) or _blank_target(tid)
            tab = TargetTab(tid, data)
            self._target_tabs[tid] = tab
            label = data.get("label") or TARGET_PRESETS.get(tid, {}).get("label") or tid
            self.tabs.addTab(tab, str(label))

        # Select last active target
        active = self.cfg.get("active_target") or "lightsail"
        if active in self._target_tabs:
            idx = list(self._target_tabs.keys()).index(active)
            self.tabs.setCurrentIndex(idx)

        # ── shared settings ───────────────────────────────────────────────
        shared_form = QFormLayout()
        self.python_edit = QLineEdit(self.cfg.get("python_bin") or "")
        self.autostart_cb = QCheckBox("Start relay + tunnel when app opens (active tab)")
        self.autostart_cb.setChecked(bool(self.cfg.get("autostart")))
        self.minimized_cb = QCheckBox("Start minimized to tray")
        self.minimized_cb.setChecked(bool(self.cfg.get("start_minimized")))
        shared_form.addRow("Python (venv)", self.python_edit)
        shared_form.addRow("", self.autostart_cb)
        shared_form.addRow("", self.minimized_cb)
        shared_box = QGroupBox("Shared")
        shared_box.setLayout(shared_form)

        # ── status + buttons ──────────────────────────────────────────────
        self.status_target = QLabel("Active target: —")
        self.status_relay = QLabel("Relay: stopped")
        self.status_tunnel = QLabel("Tunnel: stopped")
        self.status_overall = QLabel("Status: idle")
        for lab in (
            self.status_target,
            self.status_relay,
            self.status_tunnel,
            self.status_overall,
        ):
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("Start both")
        self.btn_stop = QPushButton("Stop both")
        self.btn_save = QPushButton("Save settings")
        self.btn_start.setToolTip("Start local relay + SSH tunnel for the selected tab")
        self.btn_start.clicked.connect(self.start_both)
        self.btn_stop.clicked.connect(self.stop_both)
        self.btn_save.clicked.connect(self.save_settings)
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        btn_row.addWidget(self.btn_save)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Log output…")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(intro)
        layout.addWidget(self.tabs)
        layout.addWidget(shared_box)
        layout.addWidget(self.status_target)
        layout.addWidget(self.status_overall)
        layout.addWidget(self.status_relay)
        layout.addWidget(self.status_tunnel)
        layout.addLayout(btn_row)
        layout.addWidget(QLabel("Log"))
        layout.addWidget(self.log, stretch=1)
        self.setCentralWidget(central)

        # ── tray ──────────────────────────────────────────────────────────
        self.tray = QSystemTrayIcon(make_icon("#64748b"), self)
        self.tray.setToolTip("Transcript relay: stopped")
        menu = QMenu()
        act_show = QAction("Show window", self)
        act_show.triggered.connect(self.show_normal_raise)
        act_start = QAction("Start both", self)
        act_start.triggered.connect(self.start_both)
        act_stop = QAction("Stop both", self)
        act_stop.triggered.connect(self.stop_both)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.quit_app)
        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(act_start)
        menu.addAction(act_stop)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

        self.poll = QTimer(self)
        self.poll.timeout.connect(self.refresh_status)
        self.poll.start(1000)

        self.append_log("Ready. Pick Lightsail or EC2 tab, save settings, then Start both.")
        self.append_log(f"Config file: {CONFIG_PATH}")
        self._update_target_label()

        if self.cfg.get("autostart"):
            QTimer.singleShot(400, self.start_both)

    # ── helpers ───────────────────────────────────────────────────────────

    def append_log(self, msg: str) -> None:
        from PySide6.QtGui import QTextCursor

        ts = time.strftime("%H:%M:%S")
        # Truncate pathological lines (child process spam)
        text = str(msg)
        if len(text) > 500:
            text = text[:500] + "…"
        self.log.append(f"[{ts}] {text}")
        # Bound memory: drop oldest blocks when the log grows too large
        doc = self.log.document()
        if doc.blockCount() > MAX_LOG_BLOCKS:
            cursor = self.log.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            # Remove roughly the oldest half of the log
            while doc.blockCount() > MAX_LOG_BLOCKS // 2:
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()  # remove the newline

    def show_normal_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_normal_raise()

    def current_target_id(self) -> str:
        idx = self.tabs.currentIndex()
        keys = list(self._target_tabs.keys())
        if 0 <= idx < len(keys):
            return keys[idx]
        return "lightsail"

    def _update_target_label(self) -> None:
        tid = self.current_target_id()
        tab = self._target_tabs.get(tid)
        label = (tab.collect().get("label") if tab else None) or tid
        host = (tab.collect().get("deploy_host") if tab else "") or "—"
        self.status_target.setText(f"Active target: {label} ({host})")

    def collect_settings(self) -> Dict[str, Any]:
        targets = {}
        for tid, tab in self._target_tabs.items():
            targets[tid] = tab.collect()
        active = self.current_target_id()
        return {
            "active_target": active,
            "targets": targets,
            "python_bin": self.python_edit.text().strip() or _default_python(),
            "autostart": self.autostart_cb.isChecked(),
            "start_minimized": self.minimized_cb.isChecked(),
        }

    def active_target_settings(self) -> Dict[str, Any]:
        cfg = self.collect_settings()
        tid = cfg["active_target"]
        t = dict(cfg["targets"].get(tid) or {})
        t["_target_id"] = tid
        t["python_bin"] = cfg["python_bin"]
        return t

    def save_settings(self) -> None:
        self.cfg = self.collect_settings()
        save_config(self.cfg)
        self._update_target_label()
        tid = self.cfg["active_target"]
        label = self.cfg["targets"].get(tid, {}).get("label") or tid
        self.append_log(f"Saved settings → {CONFIG_PATH} (active: {label})")

    def validate_for_start(self) -> Optional[str]:
        t = self.active_target_settings()
        label = t.get("label") or t.get("_target_id") or "target"
        if not t.get("deploy_host"):
            return f"{label}: host / IP is required."
        key = Path(str(t.get("deploy_key") or "")).expanduser()
        if not key.is_file():
            return f"{label}: SSH key not found:\n{key}"
        if not _frozen():
            py = Path(str(t.get("python_bin") or "")).expanduser()
            if not py.is_file():
                return f"Python not found:\n{py}\nCreate the project venv first."
        relay_script = _relay_script()
        if not relay_script.is_file() and not _frozen():
            return f"Missing relay script:\n{relay_script}"
        if not (t.get("relay_token") or "").strip():
            return (
                f"{label}: shared token is required "
                f"(must match YOUTUBE_TRANSCRIPT_RELAY_TOKEN on the hub)."
            )
        return None

    # ── process control ───────────────────────────────────────────────────

    def start_both(self) -> None:
        err = self.validate_for_start()
        if err:
            QMessageBox.warning(self, "Cannot start", err)
            self.append_log(f"ERROR: {err}")
            return
        self.save_settings()
        t = self.active_target_settings()
        self.append_log(
            f"Starting for {t.get('label')} → {t.get('deploy_user')}@{t.get('deploy_host')}"
        )
        self.start_relay()
        QTimer.singleShot(500, self.start_tunnel)

    def stop_both(self) -> None:
        self.append_log("Stopping tunnel and relay…")
        self.tunnel.stop()
        self.relay.stop()
        self.refresh_status()
        self.append_log("Stopped.")

    def start_relay(self) -> None:
        if self.relay.running:
            self.append_log("Relay already running.")
            return
        t = self.active_target_settings()
        port = int(t.get("relay_port") or 8791)
        token = str(t.get("relay_token") or "")
        if _frozen():
            cmd = [
                sys.executable,
                "--relay",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--token",
                token,
            ]
        else:
            py = str(Path(str(t["python_bin"])).expanduser())
            script = str(_relay_script())
            cmd = [
                py,
                script,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--token",
                token,
            ]
        env = os.environ.copy()
        env["YOUTUBE_TRANSCRIPT_RELAY_TOKEN"] = token
        env.pop("YOUTUBE_TRANSCRIPT_RELAY_URL", None)
        self.append_log(f"Starting relay on port {port}…")
        try:
            # Limit pipe buffer growth: use a modest buffer; pump drains often
            self.relay.proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except OSError as e:
            self.append_log(f"Failed to start relay: {e}")
            QMessageBox.critical(self, "Relay error", str(e))
            return
        self.relay.pump_generation += 1
        self._pump_output(self.relay, self.relay.pump_generation)
        self.refresh_status()

    def start_tunnel(self) -> None:
        if self.tunnel.running:
            self.append_log("Tunnel already running.")
            return
        t = self.active_target_settings()
        key = str(Path(str(t["deploy_key"])).expanduser())
        port = int(t.get("relay_port") or 8791)
        host = str(t.get("deploy_host") or "")
        user = str(t.get("deploy_user") or "ec2-user")
        label = t.get("label") or "hub"
        cmd = [
            "ssh",
            "-i",
            key,
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-N",
            "-R",
            f"127.0.0.1:{port}:127.0.0.1:{port}",
            f"{user}@{host}",
        ]
        self.append_log(f"Starting SSH tunnel → {label} {user}@{host} (R {port})…")
        try:
            self.tunnel.proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except OSError as e:
            self.append_log(f"Failed to start tunnel: {e}")
            QMessageBox.critical(self, "Tunnel error", str(e))
            return
        self.tunnel.pump_generation += 1
        self._pump_output(self.tunnel, self.tunnel.pump_generation)
        self.refresh_status()

    def _pump_output(self, slot: ProcessSlot, generation: int) -> None:
        """Drain child stdout; generation token cancels pumps after stop/restart."""
        if not slot.proc or not slot.proc.stdout:
            return

        def read_chunk() -> None:
            # Stale timer from a previous process instance
            if generation != slot.pump_generation:
                return
            if not slot.proc or not slot.proc.stdout:
                return
            lines_this_tick = 0
            try:
                import select

                while lines_this_tick < 50:
                    r, _, _ = select.select([slot.proc.stdout], [], [], 0)
                    if not r:
                        break
                    line = slot.proc.stdout.readline()
                    if not line:
                        break
                    lines_this_tick += 1
                    self.append_log(f"{slot.name}: {line.rstrip()}")
            except Exception:
                pass
            if generation == slot.pump_generation and slot.running:
                QTimer.singleShot(400, read_chunk)

        QTimer.singleShot(200, read_chunk)

    def refresh_status(self) -> None:
        for slot in (self.relay, self.tunnel):
            if slot.proc is not None and slot.proc.poll() is not None:
                code = slot.proc.returncode
                self.append_log(f"{slot.name} exited (code {code})")
                slot.proc = None

        self._update_target_label()
        r_ok = self.relay.running
        t_ok = self.tunnel.running
        self.status_relay.setText("Relay: running" if r_ok else "Relay: stopped")
        self.status_tunnel.setText("Tunnel: running" if t_ok else "Tunnel: stopped")
        tid = self.current_target_id()
        label = (
            self._target_tabs.get(tid).collect().get("label")
            if tid in self._target_tabs
            else tid
        )
        if r_ok and t_ok:
            overall = f"Status: online ({label} can use home transcripts)"
            color = "#22c55e"
        elif r_ok or t_ok:
            overall = "Status: partial — start both for full relay"
            color = "#eab308"
        else:
            overall = "Status: offline"
            color = "#64748b"
        self.status_overall.setText(overall)
        # Avoid allocating a new QIcon/QPixmap every second (memory/CPU leak under Qt)
        if color != self._last_tray_color:
            self.tray.setIcon(icon_for(color))
            self._last_tray_color = color
        self.tray.setToolTip(overall)
        self.btn_start.setEnabled(not (r_ok and t_ok))
        self.btn_stop.setEnabled(r_ok or t_ok)

    def closeEvent(self, event) -> None:  # noqa: N802
        event.ignore()
        self.hide()
        self.tray.showMessage(
            "Transcript relay",
            "Still running in the tray. Use Quit from the tray menu to exit.",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

    def quit_app(self) -> None:
        self.stop_both()
        self.tray.hide()
        QApplication.instance().quit()


def main() -> int:
    if "--relay" in sys.argv:
        import runpy

        sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--relay"]
        runpy.run_path(str(_relay_script()), run_name="__main__")
        return 0

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("AI Conversation Transcript Relay")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None,
            "No system tray",
            "No system tray is available. The window will still work for Start/Stop.",
        )

    win = RelayControllerWindow()
    if win.cfg.get("start_minimized") and QSystemTrayIcon.isSystemTrayAvailable():
        win.hide()
    else:
        win.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
