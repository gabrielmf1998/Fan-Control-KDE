#!/usr/bin/env bash
# Builds every package into dist/:  .rpm (Fedora, openSUSE), .deb (Debian,
# Ubuntu), the fan-control-kde-pyside6 .deb for the ones that package no
# PySide6, .pkg.tar.zst (Arch) and an .AppImage (the system's python3, and its
# PySide6 when it has one - otherwise the copy inside).
set -euo pipefail

NAME=fan-control-kde
BIN=fan-control
VERSION=2.4.0
RELEASE=1
MAINT="Gabriel Marques Ferrarezi <110578985+gabrielmf1998@users.noreply.github.com>"
URL="https://github.com/gabrielmf1998/Fan-Control-KDE"
SUMMARY="Tray applet for fan speed, fan curves and temperatures"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$ROOT/dist"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
say() { printf '\033[1m==>\033[0m %s\n' "$*"; }

rm -rf "$DIST"; mkdir -p "$DIST"

stage_tree() {
    local d="$1"
    install -d "$d/usr/share/$NAME/fancontrol"
    install -m 0644 "$ROOT"/fancontrol/*.py         "$d/usr/share/$NAME/fancontrol/"
    install -Dm 0755 "$ROOT/packaging/$BIN"         "$d/usr/bin/$BIN"
    install -Dm 0755 "$ROOT/packaging/fan-tray"     "$d/usr/bin/fan-tray"
    install -Dm 0755 "$ROOT/helper/fan-control-helper" \
        "$d/usr/libexec/fan-control-helper"
    install -Dm 0755 "$ROOT/helper/fan-control-installer" \
        "$d/usr/libexec/fan-control-installer"
    install -Dm 0644 "$ROOT/polkit/io.github.gabrielmf1998.fancontrol.policy" \
        "$d/usr/share/polkit-1/actions/io.github.gabrielmf1998.fancontrol.policy"
    install -Dm 0644 "$ROOT/polkit/49-fan-control-kde.rules" \
        "$d/etc/polkit-1/rules.d/49-fan-control-kde.rules"
    install -Dm 0644 "$ROOT/packaging/$NAME.desktop" \
        "$d/usr/share/applications/$NAME.desktop"
    install -Dm 0644 "$ROOT/systemd/fan-control-kde-daemon.service" \
        "$d/usr/lib/systemd/system/fan-control-kde-daemon.service"
    install -Dm 0644 "$ROOT/systemd/fan-control-kde.service" \
        "$d/usr/lib/systemd/user/fan-control-kde.service"
    for s in 48 64 128 256 512; do
        install -Dm 0644 "$ROOT/assets/$NAME-${s}.png" \
            "$d/usr/share/icons/hicolor/${s}x${s}/apps/$NAME.png"
    done
    install -Dm 0644 "$ROOT/assets/$NAME.svg" \
        "$d/usr/share/icons/hicolor/scalable/apps/$NAME.svg"
    install -d "$d/etc/fan-control-kde"
    install -Dm 0644 "$ROOT/LICENSE"   "$d/usr/share/licenses/$NAME/LICENSE"
    install -Dm 0644 "$ROOT/README.md" "$d/usr/share/doc/$NAME/README.md"
}

# ── source tarball (for the RPM) ────────────────────────────
say "source tarball"
SRCDIR="$WORK/$NAME-$VERSION"; mkdir -p "$SRCDIR"
cp -r "$ROOT"/{fancontrol,helper,polkit,systemd,assets,packaging,docs,Makefile,LICENSE,README.md,install.sh,install-online.sh} "$SRCDIR/"
rm -rf "$SRCDIR/fancontrol/__pycache__" "$SRCDIR/packaging/build-packages.sh" \
       "$SRCDIR/packaging/bundle-pyside6.py"
tar -C "$WORK" -czf "$WORK/$NAME-$VERSION.tar.gz" "$NAME-$VERSION"

# ── a PySide6 for distributions without one ─────────────────
# Ubuntu 24.04 and its derivatives (Kubuntu, KDE neon), and Debian 12, package
# none. The official wheel, pinned and hash-checked, trimmed to what the tray
# uses; it goes into its own .deb and into the AppImage. See
# packaging/bundle-pyside6.py.
say "bundled PySide6"
PYSIDE="$WORK/pyside6"
python3 "$ROOT/packaging/bundle-pyside6.py" "$PYSIDE"
PYSIDE_VERSION="$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' "$ROOT/packaging/bundle-pyside6.py")"

# ── RPM ─────────────────────────────────────────────────────
if command -v rpmbuild >/dev/null; then
    say "RPM"
    TOP="$WORK/rpm"; mkdir -p "$TOP"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
    cp "$WORK/$NAME-$VERSION.tar.gz" "$TOP/SOURCES/"
    cp "$ROOT/packaging/fedora/$NAME.spec" "$TOP/SPECS/"
    rpmbuild --define "_topdir $TOP" -bb "$TOP/SPECS/$NAME.spec" >"$WORK/rpm.log" 2>&1 \
        || { tail -40 "$WORK/rpm.log"; exit 1; }
    find "$TOP/RPMS" -name '*.rpm' -exec cp {} "$DIST/" \;
else
    say "rpmbuild unavailable — skipping RPM"
fi

# ── DEB ─────────────────────────────────────────────────────
if command -v dpkg-deb >/dev/null; then
    say "DEB"
    DEB="$WORK/deb"; stage_tree "$DEB"
    mkdir -p "$DEB/DEBIAN"
    cat > "$DEB/DEBIAN/control" <<CONTROL
Package: $NAME
Version: $VERSION-$RELEASE
Architecture: all
Maintainer: $MAINT
Section: utils
Priority: optional
Homepage: $URL
Depends: python3, python3-pyside6.qtwidgets | $NAME-pyside6, python3-pyside6.qtnetwork | $NAME-pyside6, policykit-1 | polkitd, systemd
Recommends: lm-sensors, pciutils
Description: $SUMMARY
 Fan Control KDE puts every fan the machine will admit to having in the system
 tray: motherboard headers one by one through the kernel's own hwmon interface,
 AMD cards through amdgpu and its overdrive fan curve, and NVIDIA cards through
 NVML, with no X display or Coolbits needed.
 .
 Set a speed by hand, hand a fan back to its firmware, or draw a fan curve on a
 graph. A small system service keeps every speed where it was set - putting it
 back if the firmware moves it - restores them all after a reboot, and runs the
 curves, with hysteresis, separate ramp rates up and down, a spin-up kick for
 fans that will not start from stopped, and a zero-rpm cut-off. Where the
 hardware has a curve of its own, the same curve can be written into the
 firmware so it runs with nothing loaded at all.
 .
 Calibration sweeps a fan and writes down the duty it actually starts at, which
 is the one thing a curve cannot be guessed without.
 .
 One icon can speak for the whole machine, or be pinned to a single fan, and
 there can be as many as you have fans worth watching - each with an appearance
 of its own, so the CPU icon and the GPU icon are not the same picture twice.
 Headers the board never populated can be hidden outright.
 .
 53 icon shapes - 30 of them fan rotors, from a three-blade classic through
 sickle, scythe and maple blades to a squirrel cage, a bladeless ring and a
 counter-rotating pair - and 44 animations, including motion blur that smears
 the trailing edge across a real arc the way a fast fan actually looks.
 .
 A colour and an animation per state, a number badge, and a rotor that turns at
 a rate taken from the measured rpm.
CONTROL
    cat > "$DEB/DEBIAN/conffiles" <<'CONFFILES'
/etc/polkit-1/rules.d/49-fan-control-kde.rules
CONFFILES
    cat > "$DEB/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
systemctl daemon-reload >/dev/null 2>&1 || true
# The one service that keeps the speeds and runs the curves. This also folds
# 2.3's two units into it, keeping what was switched on there, and restarts it
# so an upgrade runs the new code.
/usr/libexec/fan-control-helper migrate || true
if [ -x /usr/bin/update-desktop-database ]; then
    update-desktop-database -q /usr/share/applications || true
fi
if [ -x /usr/bin/gtk-update-icon-cache ]; then
    gtk-update-icon-cache -q /usr/share/icons/hicolor || true
fi
exit 0
POSTINST
    cat > "$DEB/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
if [ "$1" = remove ]; then
    systemctl disable --now fan-control-kde-daemon.service >/dev/null 2>&1 || true
fi
exit 0
PRERM
    chmod 0755 "$DEB/DEBIAN/postinst" "$DEB/DEBIAN/prerm"
    dpkg-deb --root-owner-group --build "$DEB" \
        "$DIST/${NAME}_${VERSION}-${RELEASE}_all.deb" >/dev/null

    say "DEB (bundled PySide6 $PYSIDE_VERSION)"
    RT="$WORK/deb-pyside6"
    install -d "$RT/usr/lib/$NAME/pyside6" "$RT/usr/share/doc/$NAME-pyside6" "$RT/DEBIAN"
    cp -r "$PYSIDE/PySide6" "$PYSIDE/shiboken6" "$RT/usr/lib/$NAME/pyside6/"
    install -m 0644 "$PYSIDE/copyright" "$RT/usr/share/doc/$NAME-pyside6/copyright"
    cat > "$RT/DEBIAN/control" <<CONTROL
Package: $NAME-pyside6
Version: $PYSIDE_VERSION-1
Architecture: amd64
Maintainer: $MAINT
Installed-Size: $(du -sk "$RT/usr" | cut -f1)
Section: python
Priority: optional
Homepage: $URL
Depends: python3 (>= 3.9), libc6 (>= 2.34), libstdc++6, libgcc-s1, libglib2.0-0t64 | libglib2.0-0, libdbus-1-3, libgl1, libegl1, libfontconfig1, libfreetype6, libbrotli1, zlib1g, libzstd1, libgssapi-krb5-2, libxkbcommon0, libxkbcommon-x11-0, libx11-6, libx11-xcb1, libxcb1, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render0, libxcb-render-util0, libxcb-shape0, libxcb-shm0, libxcb-sync1, libxcb-util1, libxcb-xfixes0, libxcb-xkb1, libwayland-client0, libwayland-cursor0
Recommends: libssl3t64 | libssl3
Description: PySide6 $PYSIDE_VERSION for Fan Control KDE, where the distribution has none
 Ubuntu 24.04 and what is built on it (Kubuntu, KDE neon, Linux Mint 22,
 Pop!_OS 24.04), and Debian 12, do not package PySide6. This is the official
 Qt for Python $PYSIDE_VERSION wheel, unmodified, trimmed to what Fan Control
 KDE uses: QtCore, QtGui, QtWidgets, QtNetwork and QtDBus, with the xcb and
 Wayland platform plugins.
 .
 It lives in /usr/lib/$NAME/pyside6, off Python's path. Only $NAME picks it
 up, and only when the distribution offers no PySide6 of its own.
CONTROL
    dpkg-deb -Zxz --root-owner-group --build "$RT" \
        "$DIST/${NAME}-pyside6_${PYSIDE_VERSION}-1_amd64.deb" >/dev/null
else
    say "dpkg-deb unavailable — skipping DEB"
fi

# ── Arch ────────────────────────────────────────────────────
say "Arch package"
PKG="$WORK/pkg"; stage_tree "$PKG"
# polkit's own package makes this 750; anything else and pacman warns that the
# permissions differ on every install.
chmod 0750 "$PKG/etc/polkit-1/rules.d"
SIZE=$(du -sb "$PKG" | cut -f1)
cat > "$PKG/.PKGINFO" <<PKGINFO
pkgname = $NAME
pkgbase = $NAME
pkgver = $VERSION-$RELEASE
pkgdesc = $SUMMARY
url = $URL
builddate = $(date +%s)
packager = $MAINT
size = $SIZE
arch = any
license = MIT
depend = python
depend = pyside6
depend = polkit
depend = systemd
optdepend = lm_sensors: detect the motherboard's Super I/O chip
optdepend = pciutils: readable graphics card names
backup = etc/polkit-1/rules.d/49-fan-control-kde.rules
PKGINFO
# pacman runs these; without them an upgrade would leave 2.3's units behind
# and nothing would start the one service that keeps the speeds.
cp "$ROOT/packaging/arch/$NAME.install" "$PKG/.INSTALL"
( cd "$PKG"
  TAROPTS=(--no-xattrs --no-fflags --uid 0 --gid 0 --uname root --gname root)
  LANG=C bsdtar "${TAROPTS[@]}" -czf .MTREE --format=mtree \
      --options='!all,use-set,type,uid,gid,mode,time,size,md5,sha256,link' \
      .PKGINFO .INSTALL etc usr
  LANG=C bsdtar "${TAROPTS[@]}" -cf - .PKGINFO .INSTALL .MTREE etc usr |
      zstd -q -c -T0 -18 > "$DIST/$NAME-$VERSION-$RELEASE-any.pkg.tar.zst" )

# ── AppImage (the system's python3; its PySide6, or the one inside) ──
say "AppImage"
if AT="$(command -v appimagetool 2>/dev/null)"; then :; else
    AT="$WORK/appimagetool"
    curl -fsSL -o "$AT" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage \
        && chmod +x "$AT" || AT=""
fi
if [ -n "$AT" ]; then
    APPDIR="$WORK/AppDir"
    install -d "$APPDIR/usr/share/$NAME/fancontrol"
    install -m 0644 "$ROOT"/fancontrol/*.py "$APPDIR/usr/share/$NAME/fancontrol/"
    install -Dm 0755 "$ROOT/helper/fan-control-helper" \
        "$APPDIR/usr/libexec/fan-control-helper"
    install -d "$APPDIR/usr/lib/$NAME/pyside6"
    cp -r "$PYSIDE/PySide6" "$PYSIDE/shiboken6" "$PYSIDE/copyright" \
        "$APPDIR/usr/lib/$NAME/pyside6/"
    install -Dm 0644 "$ROOT/assets/$NAME-256.png" "$APPDIR/$NAME.png"
    install -Dm 0644 "$ROOT/assets/$NAME-256.png" \
        "$APPDIR/usr/share/icons/hicolor/256x256/apps/$NAME.png"
    install -Dm 0644 "$ROOT/packaging/$NAME.desktop" "$APPDIR/$NAME.desktop"
    cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
# Fan Control KDE AppImage: the system's python3, and its PySide6 when it has
# one - otherwise the copy inside this image (Qt for Python, trimmed).
HERE="$(dirname "$(readlink -f "$0")")"
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    echo "Fan Control KDE needs python3, 3.9 or newer, on the system." >&2
    exit 1
fi
# The privileged helper cannot live inside the image: pkexec will only run a
# real file on disk that a polkit policy names by path. Point at the packaged
# one, and say so plainly when it is not there.
if [ ! -x /usr/libexec/fan-control-helper ]; then
    echo "Fan Control KDE: /usr/libexec/fan-control-helper is missing, so the" >&2
    echo "fans can be watched but not changed: every fan control on Linux needs" >&2
    echo "root. Install the .rpm/.deb/pkg, or run install.sh from the" >&2
    echo "repository, and the AppImage will use it." >&2
fi
export PYTHONPATH="$HERE/usr/share/fan-control-kde${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m fancontrol "$@"
APPRUN
    chmod +x "$APPDIR/AppRun"
    ARCH=x86_64 "$AT" --appimage-extract-and-run "$APPDIR" \
        "$DIST/Fan-Control-KDE-x86_64.AppImage" >"$WORK/appimage.log" 2>&1 \
        && say "AppImage built" \
        || { say "AppImage build failed:"; tail -15 "$WORK/appimage.log"; }
else
    say "appimagetool unavailable — skipping AppImage"
fi

# ── checksums ───────────────────────────────────────────────
( cd "$DIST" && sha256sum ./*.rpm ./*_all.deb ./*_amd64.deb ./*.pkg.tar.zst \
    ./*.AppImage > SHA256SUMS 2>/dev/null || true )
say "done. Artifacts in dist/:"
ls -1sh "$DIST"
