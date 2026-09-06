#!/usr/bin/env bash
# Builds every package into dist/:  .rpm (Fedora), .deb (Debian/Ubuntu),
# .pkg.tar.zst (Arch) and an .AppImage (thin: uses the system python3+PySide6).
set -euo pipefail

NAME=fan-control-kde
BIN=fan-control
VERSION=2.3.0
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
    for unit in fan-control-kde-restore.service fan-control-kde-curve.service; do
        install -Dm 0644 "$ROOT/systemd/$unit" "$d/usr/lib/systemd/system/$unit"
    done
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
rm -rf "$SRCDIR/fancontrol/__pycache__" "$SRCDIR/packaging/build-packages.sh"
tar -C "$WORK" -czf "$WORK/$NAME-$VERSION.tar.gz" "$NAME-$VERSION"

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
Depends: python3, python3-pyside6.qtwidgets, python3-pyside6.qtnetwork, policykit-1 | polkitd, systemd
Recommends: lm-sensors, pciutils
Suggests: nvidia-settings
Description: $SUMMARY
 Fan Control KDE puts every fan the machine will admit to having in the system
 tray: motherboard headers one by one through the kernel's own hwmon interface,
 AMD cards through amdgpu and its overdrive fan curve, and NVIDIA cards through
 nvidia-settings.
 .
 Set a speed by hand, hand a fan back to its firmware, or draw a fan curve on a
 graph and have a small system service run it - with hysteresis, separate ramp
 rates up and down, a spin-up kick for fans that will not start from stopped,
 and a zero-rpm cut-off. Where the hardware has a curve of its own, the same
 curve can be written into the firmware so it runs with nothing loaded at all.
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
# 1.x shipped this unit under a different name; carry the user's choice over.
if [ -L /etc/systemd/system/graphical.target.wants/fan-tray-restore.service ]; then
    rm -f /etc/systemd/system/graphical.target.wants/fan-tray-restore.service
    systemctl enable fan-control-kde-restore.service >/dev/null 2>&1 || true
fi
systemctl daemon-reload >/dev/null 2>&1 || true
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
    systemctl disable --now fan-control-kde-curve.service >/dev/null 2>&1 || true
    systemctl disable --now fan-control-kde-restore.service >/dev/null 2>&1 || true
fi
exit 0
PRERM
    chmod 0755 "$DEB/DEBIAN/postinst" "$DEB/DEBIAN/prerm"
    dpkg-deb --root-owner-group --build "$DEB" \
        "$DIST/${NAME}_${VERSION}-${RELEASE}_all.deb" >/dev/null
else
    say "dpkg-deb unavailable — skipping DEB"
fi

# ── Arch ────────────────────────────────────────────────────
say "Arch package"
PKG="$WORK/pkg"; stage_tree "$PKG"
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
optdepend = nvidia-settings: fan control on NVIDIA cards
backup = etc/polkit-1/rules.d/49-fan-control-kde.rules
PKGINFO
( cd "$PKG"
  TAROPTS=(--no-xattrs --no-fflags --uid 0 --gid 0 --uname root --gname root)
  LANG=C bsdtar "${TAROPTS[@]}" -czf .MTREE --format=mtree \
      --options='!all,use-set,type,uid,gid,mode,time,size,md5,sha256,link' \
      .PKGINFO etc usr
  LANG=C bsdtar "${TAROPTS[@]}" -cf - .PKGINFO .MTREE etc usr |
      zstd -q -c -T0 -18 > "$DIST/$NAME-$VERSION-$RELEASE-any.pkg.tar.zst" )

# ── AppImage (thin: system python3 + PySide6) ───────────────
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
    install -Dm 0644 "$ROOT/assets/$NAME-256.png" "$APPDIR/$NAME.png"
    install -Dm 0644 "$ROOT/assets/$NAME-256.png" \
        "$APPDIR/usr/share/icons/hicolor/256x256/apps/$NAME.png"
    install -Dm 0644 "$ROOT/packaging/$NAME.desktop" "$APPDIR/$NAME.desktop"
    cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
# Fan Control KDE AppImage: a thin wrapper around the system python3 + PySide6.
HERE="$(dirname "$(readlink -f "$0")")"
if ! python3 -c "import PySide6.QtWidgets" 2>/dev/null; then
    echo "Fan Control KDE needs PySide6 installed on the system:" >&2
    echo "  Fedora:        sudo dnf install python3-pyside6" >&2
    echo "  Debian/Ubuntu: sudo apt install python3-pyside6.qtwidgets" >&2
    echo "  Arch:          sudo pacman -S pyside6" >&2
    exit 1
fi
# The privileged helper cannot live inside the image: pkexec will only run a
# real file on disk that a polkit policy names by path. Point at the packaged
# one, and say so plainly when it is not there.
if [ ! -x /usr/libexec/fan-control-helper ]; then
    echo "Fan Control KDE: /usr/libexec/fan-control-helper is missing." >&2
    echo "Without it nothing can be read or changed, because every fan control" >&2
    echo "on Linux needs root. Install the .rpm/.deb/pkg, or run install.sh" >&2
    echo "from the repository, and the AppImage will find it." >&2
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
( cd "$DIST" && sha256sum ./*.rpm ./*.deb ./*.pkg.tar.zst ./*.AppImage \
    > SHA256SUMS 2>/dev/null || true )
say "done. Artifacts in dist/:"
ls -1sh "$DIST"
