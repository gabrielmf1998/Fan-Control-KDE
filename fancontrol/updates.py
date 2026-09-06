"""Finding out whether there is a newer release, and installing it.

Only ever when asked. There is no timer and no background poll unless the user
switches one on; the request happens when someone picks "Check for updates",
and at no other time. It is an unauthenticated GET against a public endpoint,
and nothing about this machine goes with it.

Both forges are asked because the project is mirrored, and whichever answers
with the newer tag wins. Installing is a separate, deliberately noisier step: it
downloads the package for this distribution, checks it against the SHA256SUMS
published beside it, and hands it to the system package manager through its own
polkit action - one that always prompts, even where the fan action does not.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from urllib.parse import quote

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import __version__, system
from .config import APP_NAME, GITHUB_REPO, GITLAB_REPO, GITLAB_URL, PROJECT_URL

GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
# permalink/latest rather than the whole list: the list is every release ever
# made, and picking assets out of it means picking them out of all of them.
GITLAB_API = (f"https://gitlab.com/api/v4/projects/{quote(GITLAB_REPO, safe='')}"
              "/releases/permalink/latest")
RELEASES_PAGE = f"{PROJECT_URL}/releases/latest"
GITLAB_RELEASES_PAGE = f"{GITLAB_URL}/-/releases"

INSTALL_COMMAND = (
    f"curl -fsSL https://raw.githubusercontent.com/{GITHUB_REPO}/main/"
    "install-online.sh | sh"
)
INSTALL_COMMAND_GITLAB = (
    f"curl -fsSL {GITLAB_URL}/-/raw/main/install-online.sh | sh"
)


def parse_version(text: str) -> tuple[int, ...]:
    """"v1.2.3" or "1.2.3-1" -> (1, 2, 3). Anything unparsable sorts lowest."""
    numbers = re.findall(r"\d+", (text or "").split("-")[0])
    return tuple(int(n) for n in numbers[:4]) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


class Release:
    def __init__(self, tag: str, source: str, page: str, notes: str,
                 assets: list[tuple[str, str]]) -> None:
        self.tag = tag.lstrip("vV")
        self.source = source
        self.page = page
        self.notes = notes
        self.assets = assets            # [(name, url)]

    def asset_for(self, suffix: str) -> tuple[str, str] | None:
        for name, url in self.assets:
            if name.endswith(suffix):
                return name, url
        return None

    def checksums(self) -> tuple[str, str] | None:
        return self.asset_for("SHA256SUMS")


class UpdateChecker(QObject):
    """One on-demand look at both forges' release endpoints."""

    checked = Signal(bool, str)      # ok, a line to show

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._pending = 0
        self._found: list[Release] = []
        self._errors: list[str] = []
        self.release: Release | None = None
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def available(self) -> bool:
        return bool(self.release) and is_newer(self.release.tag)

    def check(self, channel: str = "both") -> bool:
        if self._busy:
            return False
        self._busy = True
        self._found = []
        self._errors = []
        targets = []
        if channel in ("both", "github"):
            targets.append((GITHUB_API, "GitHub"))
        if channel in ("both", "gitlab"):
            targets.append((GITLAB_API, "GitLab"))
        self._pending = len(targets)
        for url, kind in targets:
            request = QNetworkRequest(QUrl(url))
            request.setRawHeader(b"User-Agent",
                                 f"{APP_NAME}/{__version__}".encode())
            request.setRawHeader(b"Accept", b"application/json")
            request.setTransferTimeout(15000)
            reply = self._nam.get(request)
            reply.finished.connect(lambda r=reply, k=kind: self._one_done(r, k))
        return True

    # -- parsing -----------------------------------------------------------
    def _one_done(self, reply: QNetworkReply, kind: str) -> None:
        raw = bytes(reply.readAll())
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        error = reply.errorString() if reply.error() != QNetworkReply.NoError else ""
        reply.deleteLater()

        try:
            if error and not raw:
                self._errors.append(f"{kind}: {error}")
            elif status and int(status) >= 400:
                self._errors.append(f"{kind} answered HTTP {status}")
            else:
                data = json.loads(raw.decode("utf-8"))
                release = (self._from_github(data) if kind == "GitHub"
                           else self._from_gitlab(data))
                if release:
                    self._found.append(release)
                else:
                    self._errors.append(f"{kind} has no tagged release")
        except (ValueError, UnicodeDecodeError, TypeError, KeyError):
            self._errors.append(f"{kind} returned something unreadable")
        finally:
            self._pending -= 1
            if self._pending <= 0:
                self._finish()

    @staticmethod
    def _from_github(data) -> Release | None:
        if not isinstance(data, dict):
            return None
        tag = str(data.get("tag_name") or "").strip()
        if not tag:
            return None
        assets = [(a.get("name", ""), a.get("browser_download_url", ""))
                  for a in (data.get("assets") or [])
                  if a.get("browser_download_url")]
        return Release(tag, "GitHub", str(data.get("html_url") or RELEASES_PAGE),
                       str(data.get("body") or ""), assets)

    @staticmethod
    def _from_gitlab(data) -> Release | None:
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            tag = str(entry.get("tag_name") or entry.get("name") or "").strip()
            if not tag:
                continue
            links = ((entry.get("assets") or {}).get("links") or [])
            assets = [(l.get("name", ""), l.get("direct_asset_url") or l.get("url", ""))
                      for l in links if (l.get("direct_asset_url") or l.get("url"))]
            page = ((entry.get("_links") or {}).get("self")
                    or GITLAB_RELEASES_PAGE)
            return Release(tag, "GitLab", str(page),
                           str(entry.get("description") or ""), assets)
        return None

    def _finish(self) -> None:
        self._busy = False
        if not self._found:
            self.checked.emit(False, "; ".join(self._errors) or
                              "Neither GitHub nor GitLab could be reached.")
            return
        self._found.sort(key=lambda r: parse_version(r.tag), reverse=True)
        self.release = self._found[0]
        if self.available:
            self.checked.emit(True, f"Version {self.release.tag} is out "
                                    f"on {self.release.source}.")
        else:
            self.checked.emit(True, f"{__version__} is the latest release.")


# --------------------------------------------------------------------------
# downloading and installing
# --------------------------------------------------------------------------
class Downloader(QObject):
    """Fetches one package and its checksum file, then verifies the pair."""

    progress = Signal(int, int)      # received, total (-1 when unknown)
    finished = Signal(bool, str)     # ok, path or the reason it failed

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._dir = ""
        self._reply: QNetworkReply | None = None

    def cancel(self) -> None:
        if self._reply is not None:
            self._reply.abort()

    def fetch(self, release: Release, family: str) -> bool:
        suffix = system.PACKAGE_SUFFIX.get(family)
        if not suffix:
            self.finished.emit(False, "There is no package for this distribution.")
            return False
        asset = release.asset_for(suffix)
        if not asset:
            self.finished.emit(
                False, f"That release has no {suffix} package attached.")
            return False
        sums = release.checksums()
        self._dir = tempfile.mkdtemp(prefix="fan-control-update-")
        self._release = release
        self._asset = asset
        self._sums = sums
        if sums:
            self._get(sums[1], os.path.join(self._dir, "SHA256SUMS"),
                      self._sums_done)
        else:
            self._start_package()
        return True

    # -- steps -------------------------------------------------------------
    def _get(self, url: str, path: str, done) -> None:
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", f"{APP_NAME}/{__version__}".encode())
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                             QNetworkRequest.NoLessSafeRedirectPolicy)
        request.setTransferTimeout(120000)
        reply = self._nam.get(request)
        self._reply = reply
        reply.downloadProgress.connect(
            lambda got, total: self.progress.emit(int(got), int(total)))
        reply.finished.connect(lambda: done(reply, path))

    def _sums_done(self, reply: QNetworkReply, path: str) -> None:
        data = bytes(reply.readAll())
        failed = reply.error() != QNetworkReply.NoError
        reply.deleteLater()
        self._reply = None
        if not failed and data:
            try:
                with open(path, "wb") as fh:
                    fh.write(data)
            except OSError:
                self._sums = None
        else:
            self._sums = None            # no checksums; say so at the end
        self._start_package()

    def _start_package(self) -> None:
        name, url = self._asset
        self._package = os.path.join(self._dir, os.path.basename(name))
        self._get(url, self._package, self._package_done)

    def _package_done(self, reply: QNetworkReply, path: str) -> None:
        data = bytes(reply.readAll())
        error = (reply.errorString()
                 if reply.error() != QNetworkReply.NoError else "")
        reply.deleteLater()
        self._reply = None
        if error or not data:
            self.finished.emit(False, error or "The download came back empty.")
            return
        try:
            with open(path, "wb") as fh:
                fh.write(data)
        except OSError as exc:
            self.finished.emit(False, str(exc))
            return

        if self._sums:
            ok, why = self._verify(path)
            if not ok:
                self.finished.emit(False, why)
                return
        else:
            self.finished.emit(
                False, "That release publishes no SHA256SUMS, so the download "
                       "cannot be verified. Install it by hand from the "
                       "release page if you trust it.")
            return
        self.finished.emit(True, path)

    def _verify(self, path: str) -> tuple[bool, str]:
        want = ""
        base = os.path.basename(path)
        try:
            for line in open(os.path.join(self._dir, "SHA256SUMS")):
                digest, _, name = line.strip().partition(" ")
                if os.path.basename(name.strip().lstrip("*")) == base:
                    want = digest.strip()
                    break
        except OSError:
            return False, "The checksum file could not be read."
        if not want:
            return False, f"SHA256SUMS does not mention {base}."
        got = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                got.update(chunk)
        if got.hexdigest() != want:
            return False, ("The download does not match its published checksum. "
                           "Nothing was installed.")
        return True, ""


def install_command(family: str) -> list[str]:
    """What the installer helper will run, for showing before it is run."""
    return {
        "rpm": ["dnf", "install", "-y", "<package>"],
        "deb": ["apt-get", "install", "-y", "<package>"],
        "arch": ["pacman", "-U", "--noconfirm", "<package>"],
    }.get(family, [])
