"""Application entry point."""

from __future__ import annotations

import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import icons
from .config import APP_ID, APP_NAME, Config
from .devices import Monitor
from .tray import FanTray


def _already_running(name: str) -> bool:
    probe = QLocalSocket()
    probe.connectToServer(name)
    if probe.waitForConnected(250):
        probe.close()
        return True
    QLocalServer.removeServer(name)
    return False


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(icons.app_icon())
    app.setQuitOnLastWindowClosed(False)

    if _already_running(APP_ID):
        print(f"{APP_NAME} is already running.", file=sys.stderr)
        return 0
    guard = QLocalServer()
    guard.listen(APP_ID)

    cfg = Config()
    monitor = Monitor(cfg)
    tray = FanTray(cfg, monitor)
    tray.show()
    monitor.start()

    # Not having a tray *yet* is normal: a panel registers its
    # StatusNotifierWatcher on the session bus some time after login, and an app
    # started from autostart routinely wins that race.
    if not QSystemTrayIcon.isSystemTrayAvailable():
        tray.wait_for_tray()

    if cfg.get("check_updates_on_start", False):
        QTimer.singleShot(6000, tray.check_updates)

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    wake = QTimer()
    wake.start(400)
    wake.timeout.connect(lambda: None)

    app.aboutToQuit.connect(monitor.shutdown)
    return app.exec()
