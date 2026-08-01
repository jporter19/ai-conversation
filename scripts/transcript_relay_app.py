#!/usr/bin/env python3
"""
Desktop controller for the YouTube transcript home relay.

- System tray icon
- Window to start/stop relay + SSH tunnel
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
from pathlib import Path
from typing import Any, Dict, Optional

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

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path.home() / ".config" / "ai-conversation"
CONFIG_PATH = CONFIG_DIR / "relay_app.json"
DEFAULTS: Dict[str, Any] = {
    "deploy_host": "",  # set in UI (e.g. Elastic IP or hostname)
    "deploy_user": "ec2-user",
    "deploy_key": str(Path.home() / ".ssh" / "id_rsa"),
    "relay_port": 8791,
    "relay_token": "",
    "python_bin": str(ROOT / ".venv" / "bin" / "python"),
    "autostart": False,
    "start_minimized": False,
}


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: data[k] for k in DEFAULTS if k in data})
        except (json.JSONDecodeError, OSError):
            pass
    # Prefer token from env if config empty
    if not cfg.get("relay_token"):
        env_tok = (os.environ.get("YOUTUBE_TRANSCRIPT_RELAY_TOKEN") or "").strip()
        if env_tok:
            cfg["relay_token"] = env_tok
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


class ProcessSlot:
    """Tracks one subprocess and its log handle."""

    def __init__(self, name: str):
        self.name = name
        self.proc: Optional[subprocess.Popen] = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, timeout: float = 5.0) -> None:
        if not self.proc:
            return
        if self.proc.poll() is None:
            try:
                self.proc.send_signal(signal.SIGTERM)
            except OSError:
                pass
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    self.proc.kill()
                except OSError:
                    pass
                try:
                    self.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        self.proc = None


class RelayControllerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AI Conversation — Transcript Relay")
        self.setMinimumSize(520, 480)
        self.setWindowIcon(make_icon())

        self.cfg = load_config()
        self.relay = ProcessSlot("relay")
        self.tunnel = ProcessSlot("tunnel")

        # ── form ──────────────────────────────────────────────────────────
        form = QFormLayout()
        self.host_edit = QLineEdit(self.cfg["deploy_host"])
        self.user_edit = QLineEdit(self.cfg["deploy_user"])
        self.key_edit = QLineEdit(self.cfg["deploy_key"])
        self.port_edit = QLineEdit(str(self.cfg["relay_port"]))
        self.token_edit = QLineEdit(self.cfg["relay_token"])
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.python_edit = QLineEdit(self.cfg["python_bin"])
        self.autostart_cb = QCheckBox("Start relay + tunnel when app opens")
        self.autostart_cb.setChecked(bool(self.cfg.get("autostart")))
        self.minimized_cb = QCheckBox("Start minimized to tray")
        self.minimized_cb.setChecked(bool(self.cfg.get("start_minimized")))

        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit)
        key_browse = QPushButton("Browse…")
        key_browse.clicked.connect(self._browse_key)
        key_row.addWidget(key_browse)
        key_wrap = QWidget()
        key_wrap.setLayout(key_row)

        form.addRow("EC2 host / IP", self.host_edit)
        form.addRow("SSH user", self.user_edit)
        form.addRow("SSH key (.pem)", key_wrap)
        form.addRow("Relay port", self.port_edit)
        form.addRow("Shared token", self.token_edit)
        form.addRow("Python (venv)", self.python_edit)
        form.addRow("", self.autostart_cb)
        form.addRow("", self.minimized_cb)

        settings_box = QGroupBox("Settings")
        settings_box.setLayout(form)

        # ── status + buttons ──────────────────────────────────────────────
        self.status_relay = QLabel("Relay: stopped")
        self.status_tunnel = QLabel("Tunnel: stopped")
        self.status_overall = QLabel("Status: idle")
        for lab in (self.status_relay, self.status_tunnel, self.status_overall):
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("Start both")
        self.btn_stop = QPushButton("Stop both")
        self.btn_save = QPushButton("Save settings")
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
        layout.addWidget(settings_box)
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

        self.append_log("Ready. Save settings, then Start both.")
        self.append_log(f"Config file: {CONFIG_PATH}")

        if self.cfg.get("autostart"):
            QTimer.singleShot(400, self.start_both)

    # ── helpers ───────────────────────────────────────────────────────────

    def append_log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {msg}")

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

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select EC2 SSH private key",
            str(Path.home() / ".ssh"),
            "PEM / key files (*.pem *);;All files (*)",
        )
        if path:
            self.key_edit.setText(path)

    def collect_settings(self) -> Dict[str, Any]:
        try:
            port = int(self.port_edit.text().strip() or "8791")
        except ValueError:
            port = 8791
        return {
            "deploy_host": self.host_edit.text().strip(),
            "deploy_user": self.user_edit.text().strip() or "ec2-user",
            "deploy_key": self.key_edit.text().strip(),
            "relay_port": port,
            "relay_token": self.token_edit.text().strip(),
            "python_bin": self.python_edit.text().strip()
            or str(ROOT / ".venv" / "bin" / "python"),
            "autostart": self.autostart_cb.isChecked(),
            "start_minimized": self.minimized_cb.isChecked(),
        }

    def save_settings(self) -> None:
        self.cfg = self.collect_settings()
        save_config(self.cfg)
        self.append_log(f"Saved settings → {CONFIG_PATH}")

    def validate_for_start(self) -> Optional[str]:
        cfg = self.collect_settings()
        if not cfg["deploy_host"]:
            return "EC2 host is required."
        key = Path(cfg["deploy_key"]).expanduser()
        if not key.is_file():
            return f"SSH key not found:\n{key}"
        py = Path(cfg["python_bin"]).expanduser()
        if not py.is_file():
            return f"Python not found:\n{py}\nCreate the project venv first."
        relay_script = ROOT / "scripts" / "transcript_relay.py"
        if not relay_script.is_file():
            return f"Missing relay script:\n{relay_script}"
        if not cfg["relay_token"]:
            return "Shared token is required (must match EC2 YOUTUBE_TRANSCRIPT_RELAY_TOKEN)."
        return None

    # ── process control ───────────────────────────────────────────────────

    def start_both(self) -> None:
        err = self.validate_for_start()
        if err:
            QMessageBox.warning(self, "Cannot start", err)
            self.append_log(f"ERROR: {err}")
            return
        self.save_settings()
        self.start_relay()
        # slight delay so relay binds before tunnel is useful
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
        cfg = self.collect_settings()
        py = str(Path(cfg["python_bin"]).expanduser())
        script = str(ROOT / "scripts" / "transcript_relay.py")
        cmd = [
            py,
            script,
            "--host",
            "127.0.0.1",
            "--port",
            str(cfg["relay_port"]),
            "--token",
            cfg["relay_token"],
        ]
        env = os.environ.copy()
        env["YOUTUBE_TRANSCRIPT_RELAY_TOKEN"] = cfg["relay_token"]
        # Prevent relay from trying to call itself if env leaked
        env.pop("YOUTUBE_TRANSCRIPT_RELAY_URL", None)
        self.append_log(f"Starting relay on port {cfg['relay_port']}…")
        try:
            self.relay.proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        except OSError as e:
            self.append_log(f"Failed to start relay: {e}")
            QMessageBox.critical(self, "Relay error", str(e))
            return
        self._pump_output(self.relay)
        self.refresh_status()

    def start_tunnel(self) -> None:
        if self.tunnel.running:
            self.append_log("Tunnel already running.")
            return
        cfg = self.collect_settings()
        key = str(Path(cfg["deploy_key"]).expanduser())
        port = int(cfg["relay_port"])
        host = cfg["deploy_host"]
        user = cfg["deploy_user"]
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
        self.append_log(f"Starting SSH tunnel → {user}@{host} (R {port})…")
        try:
            self.tunnel.proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        except OSError as e:
            self.append_log(f"Failed to start tunnel: {e}")
            QMessageBox.critical(self, "Tunnel error", str(e))
            return
        self._pump_output(self.tunnel)
        self.refresh_status()

    def _pump_output(self, slot: ProcessSlot) -> None:
        """Non-blocking-ish log reader via short timer bursts."""
        if not slot.proc or not slot.proc.stdout:
            return

        def read_chunk() -> None:
            if not slot.proc or not slot.proc.stdout:
                return
            # Read available lines without blocking forever
            try:
                import select

                while True:
                    r, _, _ = select.select([slot.proc.stdout], [], [], 0)
                    if not r:
                        break
                    line = slot.proc.stdout.readline()
                    if not line:
                        break
                    self.append_log(f"{slot.name}: {line.rstrip()}")
            except Exception:
                pass
            if slot.running:
                QTimer.singleShot(400, read_chunk)

        QTimer.singleShot(200, read_chunk)

    def refresh_status(self) -> None:
        # Detect unexpected exits
        for slot in (self.relay, self.tunnel):
            if slot.proc is not None and slot.proc.poll() is not None:
                code = slot.proc.returncode
                self.append_log(f"{slot.name} exited (code {code})")
                slot.proc = None

        r_ok = self.relay.running
        t_ok = self.tunnel.running
        self.status_relay.setText("Relay: running" if r_ok else "Relay: stopped")
        self.status_tunnel.setText("Tunnel: running" if t_ok else "Tunnel: stopped")
        if r_ok and t_ok:
            overall = "Status: online (AWS can use home transcripts)"
            color = "#22c55e"
        elif r_ok or t_ok:
            overall = "Status: partial — start both for full relay"
            color = "#eab308"
        else:
            overall = "Status: offline"
            color = "#64748b"
        self.status_overall.setText(overall)
        self.tray.setIcon(make_icon(color))
        self.tray.setToolTip(overall)
        self.btn_start.setEnabled(not (r_ok and t_ok))
        self.btn_stop.setEnabled(r_ok or t_ok)

    def closeEvent(self, event) -> None:  # noqa: N802
        # Close to tray instead of quit
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
    # High-DPI
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
