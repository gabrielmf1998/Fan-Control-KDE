#!/bin/sh
# Fan Control KDE — online installer.
#
#   curl -fsSL https://raw.githubusercontent.com/gabrielmf1998/Fan-Control-KDE/main/install-online.sh | sh
#
# Works out which package this distribution wants, takes it from the latest
# release, checks it against the SHA256SUMS published beside it, and installs
# it. Anything it does not recognise gets the AppImage.
set -eu

REPO="gabrielmf1998/Fan-Control-KDE"
GITLAB="gabriel17166%2Ffan-control-kde"
API="https://api.github.com/repos/$REPO/releases/latest"
GITLAB_API="https://gitlab.com/api/v4/projects/$GITLAB/releases"

info() { printf '\033[1m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m==>\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || err "curl is required"

fam=""
[ -r /etc/os-release ] && . /etc/os-release
for t in "${ID:-}" ${ID_LIKE:-}; do
    case "$t" in
        fedora|rhel|centos|rocky|almalinux|nobara) fam=rpm; break ;;
        debian|ubuntu|linuxmint|pop)               fam=deb; break ;;
        arch|manjaro|endeavouros|cachyos)          fam=arch; break ;;
    esac
done

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

# ── PySide6 first ───────────────────────────────────────────
# The tray is a Qt program. Without PySide6 the package installs and then does
# nothing at all, which is a worse outcome than saying so now.
install_pyside() {
    if python3 -c "import PySide6.QtWidgets" 2>/dev/null; then
        info "PySide6 is already here"
        return
    fi
    info "installing PySide6"
    case "$fam" in
        rpm)  $SUDO dnf install -y python3-pyside6 ;;
        deb)  $SUDO apt-get update -qq || true
              $SUDO apt-get install -y python3-pyside6.qtwidgets \
                                       python3-pyside6.qtnetwork ;;
        arch) $SUDO pacman -S --needed --noconfirm pyside6 ;;
        *)    warn "unknown distribution — install PySide6 yourself" ;;
    esac
}

# ── the release ─────────────────────────────────────────────
# GitHub first, GitLab as the fallback: the project is mirrored, and one of the
# two being unreachable should not stop an install.
assets_github() {
    curl -fsSL "$API" 2>/dev/null | tr ',' '\n' \
        | grep '"browser_download_url"' | cut -d'"' -f4
}

assets_gitlab() {
    curl -fsSL "$GITLAB_API" 2>/dev/null | tr ',' '\n' \
        | grep -o 'https://[^"]*' | grep -v '/api/v4/'
}

ASSETS="$(assets_github || true)"
[ -n "$ASSETS" ] || ASSETS="$(assets_gitlab || true)"
[ -n "$ASSETS" ] || err "could not reach GitHub or GitLab to find a release"

fetch() {
    url="$(printf '%s\n' "$ASSETS" | grep -- "$1\$" | head -1)"
    [ -n "$url" ] || err "no asset ending in '$1' in the latest release"
    out="$tmp/${url##*/}"
    info "downloading ${url##*/}"
    curl -fL --progress-bar "$url" -o "$out" || err "download failed: $url"
    printf '%s' "$out"
}

verify() {
    file="$1"
    sums="$(printf '%s\n' "$ASSETS" | grep -- 'SHA256SUMS$' | head -1)"
    if [ -z "$sums" ]; then
        warn "this release publishes no SHA256SUMS; skipping the check"
        return
    fi
    curl -fsSL "$sums" -o "$tmp/SHA256SUMS" || {
        warn "could not fetch SHA256SUMS; skipping the check"; return; }
    want="$(awk -v n="$(basename "$file")" \
        '{ sub(/^\.\//, "", $2); sub(/^\*/, "", $2); if ($2 == n) print $1 }' \
        "$tmp/SHA256SUMS")"
    [ -n "$want" ] || err "SHA256SUMS does not mention $(basename "$file")"
    got="$(sha256sum "$file" | cut -d' ' -f1)"
    [ "$want" = "$got" ] || err "checksum mismatch — nothing was installed"
    info "checksum OK"
}

install_pyside

case "$fam" in
    rpm)
        pkg="$(fetch .noarch.rpm)"; verify "$pkg"
        info "installing with dnf"
        $SUDO dnf install -y "$pkg" ;;
    deb)
        pkg="$(fetch _all.deb)"; verify "$pkg"
        info "installing with apt"
        $SUDO apt-get install -y "$pkg" \
            || { $SUDO dpkg -i "$pkg"; $SUDO apt-get -f install -y; } ;;
    arch)
        pkg="$(fetch .pkg.tar.zst)"; verify "$pkg"
        info "installing with pacman"
        $SUDO pacman -U --noconfirm "$pkg" ;;
    *)
        info "unknown distribution — installing the AppImage into ~/.local/bin"
        pkg="$(fetch .AppImage)"; verify "$pkg"
        mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
        install -m 0755 "$pkg" "$HOME/.local/bin/fan-control"
        cat > "$HOME/.local/share/applications/fan-control-kde.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Fan Control
Comment=Fan speed, fan curves and temperatures in the system tray
Exec=$HOME/.local/bin/fan-control
Icon=sensors
Terminal=false
Categories=System;Monitor;Settings;
DESKTOP
        warn "the AppImage cannot ship the privileged helper — pkexec only runs"
        warn "a real file on disk that a polkit policy names — so it can neither"
        warn "read nor change anything on its own. Install the package for your"
        warn "distribution, or run install.sh from the repository." ;;
esac

info "done — run it with:  fan-control"
info "first launch: pick Settings to choose an icon, and Curves to draw one"
