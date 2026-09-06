"""Talking to the helper, and to systemd.

Reading is unprivileged and happens constantly, so it runs as the user and must
never block the GUI. Writing needs root and goes through one pkexec'd helper.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

HELPER_NAME = "fan-control-helper"
INSTALLER_NAME = "fan-control-installer"


def _find(name: str) -> str:
    """A packaged binary, or the one in this checkout when running from source."""
    here = Path(__file__).resolve().parent
    for cand in (Path("/usr/libexec") / name,
                 Path("/usr/local/libexec") / name,
                 here.parent / "helper" / name):
        if cand.is_file():
            return str(cand)
    return shutil.which(name) or name


def helper_path() -> str:
    return _find(HELPER_NAME)


def installer_path() -> str:
    return _find(INSTALLER_NAME)


def run(args: list[str], timeout: float = 8.0) -> tuple[int, str, str]:
    """Blocking run for one-shot reads. Never raises."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.SubprocessError):
        return 127, "", "could not run " + " ".join(args[:1])


class AsyncRun(QObject):
    """One QProcess wrapped so callers get a single (code, out, err) callback."""

    done = Signal(int, str, str)

    _live: set = set()

    def __init__(self, program: str, args: list[str], parent=None) -> None:
        super().__init__(parent)
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.SeparateChannels)
        self._proc.finished.connect(self._finished)
        self._proc.errorOccurred.connect(self._error)
        self._program = program
        self._args = args
        self._fired = False

    def start(self, timeout_ms: int = 30000) -> None:
        AsyncRun._live.add(self)
        self._proc.start(self._program, self._args)
        if timeout_ms > 0:
            QTimer.singleShot(timeout_ms, self._timeout)

    def write_stdin(self, data: str) -> None:
        self._proc.write(data.encode("utf-8"))
        self._proc.closeWriteChannel()

    def _timeout(self) -> None:
        if not self._fired and self._proc.state() != QProcess.NotRunning:
            self._proc.kill()

    def _error(self, _err) -> None:
        if self._proc.state() == QProcess.NotRunning:
            self._emit(127, "", self._proc.errorString())

    def _finished(self, code: int, _status) -> None:
        out = bytes(self._proc.readAllStandardOutput()).decode(errors="replace")
        err = bytes(self._proc.readAllStandardError()).decode(errors="replace")
        self._emit(code, out.strip(), err.strip())

    def _emit(self, code: int, out: str, err: str) -> None:
        if self._fired:
            return
        self._fired = True
        self.done.emit(code, out, err)
        AsyncRun._live.discard(self)


def run_async(program: str, args: list[str], callback, parent=None,
              timeout_ms: int = 30000) -> AsyncRun:
    job = AsyncRun(program, args, parent)
    job.done.connect(callback)
    job.start(timeout_ms)
    return job


def qt_env() -> QProcessEnvironment:
    """pkexec inherits what it is given, and the polkit agent needs the session
    bits that are already in ours."""
    env = QProcessEnvironment()
    for key, value in os.environ.items():
        env.insert(key, value)
    return env


class Privileged(QObject):
    """Runs the helper under pkexec and reports (ok, message).

    Serialised on purpose: two authentication prompts at once is a mess, and
    two writes to the same fan at once is worse.
    """

    result = Signal(bool, str)
    started = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._busy = False
        self._queue: list[tuple[list[str], str]] = []

    @property
    def busy(self) -> bool:
        return self._busy

    def run(self, args: list[str], stdin: str = "") -> bool:
        if self._busy:
            self._queue.append((args, stdin))
            return True
        self._busy = True
        self.started.emit(" ".join(args))
        job = AsyncRun("pkexec", [helper_path(), *args], self)
        job._proc.setProcessEnvironment(qt_env())
        job.done.connect(self._finished)
        job.start(180000)
        if stdin:
            job.write_stdin(stdin)
        return True

    def _finished(self, code: int, out: str, err: str) -> None:
        self._busy = False
        if code == 0:
            self.result.emit(True, out)
        elif code == 126:
            self.result.emit(False, "")            # the prompt was dismissed
        elif code == 127:
            self.result.emit(False, err or "Authentication failed.")
        else:
            self.result.emit(False, err or out or f"The helper exited with {code}.")
        if self._queue:
            args, stdin = self._queue.pop(0)
            QTimer.singleShot(0, lambda: self.run(args, stdin))


def helper_json(args: list[str], timeout: float = 25.0) -> dict:
    """One unprivileged read from the helper. {} when anything at all goes wrong."""
    code, out, _err = run([helper_path(), *args], timeout=timeout)
    if code != 0 or not out:
        return {}
    try:
        data = json.loads(out)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------
# systemd, read-only
# --------------------------------------------------------------------------
def unit_state(unit: str) -> tuple[str, str]:
    """(ActiveState, UnitFileState); "" for both when systemctl is not there."""
    code, out, _ = run(["systemctl", "show", unit, "-p", "ActiveState",
                        "-p", "UnitFileState", "--value"], timeout=5)
    if code != 0:
        return "", ""
    lines = out.splitlines()
    return (lines[0].strip() if lines else "",
            lines[1].strip() if len(lines) > 1 else "")


# --------------------------------------------------------------------------
# which distribution, for the update path and the install command
# --------------------------------------------------------------------------
def distro_family() -> str:
    """rpm, deb, arch or "" - the same detection the online installer does."""
    ids = []
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith(("ID=", "ID_LIKE=")):
                ids += line.split("=", 1)[1].strip().strip('"').split()
    except OSError:
        return ""
    for token in ids:
        if token in ("fedora", "rhel", "centos", "rocky", "almalinux", "nobara"):
            return "rpm"
        if token in ("debian", "ubuntu", "linuxmint", "pop"):
            return "deb"
        if token in ("arch", "manjaro", "endeavouros", "cachyos"):
            return "arch"
    return ""


PACKAGE_SUFFIX = {"rpm": ".noarch.rpm", "deb": "_all.deb",
                  "arch": ".pkg.tar.zst"}
