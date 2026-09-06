#!/bin/sh
# Fan Control KDE — install from this checkout, without building a package.
#
#   ./install.sh            install
#   ./install.sh uninstall  take it back out
#
# Use the package for your distribution if there is one; this is for running
# from a clone. It is the same file layout either way, so the two do not fight.
set -eu

cd "$(dirname "$0")"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

info() { printf '\033[1m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m==>\033[0m %s\n' "$*" >&2; }

if [ "${1:-install}" = "uninstall" ]; then
    info "stopping the services"
    $SUDO systemctl disable --now fan-control-kde-curve.service 2>/dev/null || true
    $SUDO systemctl disable --now fan-control-kde-restore.service 2>/dev/null || true
    $SUDO make uninstall
    rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/fan-control-kde.desktop"
    info "done. Your settings are still in ${XDG_CONFIG_HOME:-$HOME/.config}/fan-control-kde"
    exit 0
fi

python3 -c "import PySide6.QtWidgets" 2>/dev/null || {
    warn "PySide6 is not installed. The tray is a Qt program and will not start:"
    warn "  Fedora:        sudo dnf install python3-pyside6"
    warn "  Debian/Ubuntu: sudo apt install python3-pyside6.qtwidgets"
    warn "  Arch:          sudo pacman -S pyside6"
}

make check
info "installing into /usr (this is the part that needs the password)"
$SUDO make install
$SUDO systemctl daemon-reload

# 1.x installed itself under a different name; leaving both in place would run
# two trays at once and give the old one the fans.
if [ -e /usr/libexec/fan-tray-helper ] || \
   [ -e /usr/lib/systemd/system/fan-tray-restore.service ]; then
    info "clearing out the 1.x install"
    $SUDO systemctl disable --now fan-tray-restore.service 2>/dev/null || true
    $SUDO rm -f /usr/libexec/fan-tray-helper \
                /usr/lib/systemd/system/fan-tray-restore.service \
                /usr/share/applications/fan-tray.desktop
    $SUDO systemctl daemon-reload
fi

info "done. Start it with:  fan-control"
info "to have it start at login, use Settings, or the menu's Start with the system"
