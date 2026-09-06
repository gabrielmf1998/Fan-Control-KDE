PREFIX      ?= /usr
DESTDIR     ?=
BINDIR      := $(DESTDIR)$(PREFIX)/bin
LIBEXECDIR  := $(DESTDIR)$(PREFIX)/libexec
SHAREDIR    := $(DESTDIR)$(PREFIX)/share
APPDIR      := $(SHAREDIR)/applications
POLICYDIR   := $(SHAREDIR)/polkit-1/actions
RULESDIR    := $(DESTDIR)/etc/polkit-1/rules.d
UNITDIR     := $(DESTDIR)$(PREFIX)/lib/systemd/system
USERUNITDIR := $(DESTDIR)$(PREFIX)/lib/systemd/user
STATEDIR    := $(DESTDIR)/etc/fan-control-kde
ICONDIR     := $(SHAREDIR)/icons/hicolor
PKGDIR      := $(SHAREDIR)/fan-control-kde

ACTION := io.github.gabrielmf1998.fancontrol
SIZES  := 48 64 128 256 512

.PHONY: all install uninstall check icons packages

all:
	@echo "Nothing to build -- it is Python. Run 'sudo make install'."

check:
	python3 -m py_compile fancontrol/*.py helper/fan-control-helper \
	    helper/fan-control-installer
	@rm -rf fancontrol/__pycache__
	@echo "syntax OK"

icons:
	python3 assets/gen_icons.py

packages:
	packaging/build-packages.sh

install:
	install -d $(PKGDIR)/fancontrol
	install -m644 fancontrol/*.py           $(PKGDIR)/fancontrol/
	install -Dm755 packaging/fan-control    $(BINDIR)/fan-control
	install -Dm755 packaging/fan-tray       $(BINDIR)/fan-tray
	install -Dm755 helper/fan-control-helper    $(LIBEXECDIR)/fan-control-helper
	install -Dm755 helper/fan-control-installer $(LIBEXECDIR)/fan-control-installer
	install -Dm644 polkit/$(ACTION).policy   $(POLICYDIR)/$(ACTION).policy
	install -Dm644 polkit/49-fan-control-kde.rules \
	    $(RULESDIR)/49-fan-control-kde.rules
	install -Dm644 packaging/fan-control-kde.desktop \
	    $(APPDIR)/fan-control-kde.desktop
	install -Dm644 systemd/fan-control-kde-restore.service \
	    $(UNITDIR)/fan-control-kde-restore.service
	install -Dm644 systemd/fan-control-kde-curve.service \
	    $(UNITDIR)/fan-control-kde-curve.service
	install -Dm644 systemd/fan-control-kde.service \
	    $(USERUNITDIR)/fan-control-kde.service
	for s in $(SIZES); do \
	    install -Dm644 assets/fan-control-kde-$$s.png \
	        $(ICONDIR)/$${s}x$${s}/apps/fan-control-kde.png; \
	done
	install -Dm644 assets/fan-control-kde.svg \
	    $(ICONDIR)/scalable/apps/fan-control-kde.svg
	install -dm755 $(STATEDIR)

uninstall:
	rm -f  $(BINDIR)/fan-control $(BINDIR)/fan-tray
	rm -f  $(LIBEXECDIR)/fan-control-helper $(LIBEXECDIR)/fan-control-installer
	rm -f  $(POLICYDIR)/$(ACTION).policy
	rm -f  $(RULESDIR)/49-fan-control-kde.rules
	rm -f  $(UNITDIR)/fan-control-kde-restore.service
	rm -f  $(UNITDIR)/fan-control-kde-curve.service
	rm -f  $(USERUNITDIR)/fan-control-kde.service
	rm -f  $(APPDIR)/fan-control-kde.desktop
	rm -f  $(ICONDIR)/scalable/apps/fan-control-kde.svg
	for s in $(SIZES); do \
	    rm -f $(ICONDIR)/$${s}x$${s}/apps/fan-control-kde.png; \
	done
	rm -rf $(PKGDIR)
	@echo "left alone: $(STATEDIR) -- it holds your speeds and curves"
