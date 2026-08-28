PREFIX      ?= /usr
DESTDIR     ?=
BINDIR      := $(DESTDIR)$(PREFIX)/bin
LIBEXECDIR  := $(DESTDIR)$(PREFIX)/libexec
APPDIR      := $(DESTDIR)$(PREFIX)/share/applications
POLICYDIR   := $(DESTDIR)$(PREFIX)/share/polkit-1/actions
RULESDIR    := $(DESTDIR)/etc/polkit-1/rules.d
UNITDIR     := $(DESTDIR)$(PREFIX)/lib/systemd/system
STATEDIR    := $(DESTDIR)/etc/fan-control-kde

ACTION := io.github.gabrielmf1998.fancontrol

.PHONY: all install uninstall check

all:
	@echo "Nothing to build -- Python. Run 'make install' (as root)."

check:
	python3 -m py_compile src/fan-tray src/fan-tray-helper
	@echo "syntax OK"

install:
	install -Dm755 src/fan-tray            $(BINDIR)/fan-tray
	install -Dm755 src/fan-tray-helper     $(LIBEXECDIR)/fan-tray-helper
	install -Dm644 data/$(ACTION).policy   $(POLICYDIR)/$(ACTION).policy
	install -Dm644 data/49-fan-control-kde.rules $(RULESDIR)/49-fan-control-kde.rules
	install -Dm644 data/fan-tray-restore.service $(UNITDIR)/fan-tray-restore.service
	install -Dm644 data/fan-control-kde.desktop  $(APPDIR)/fan-control-kde.desktop
	install -dm755 $(STATEDIR)

uninstall:
	rm -f  $(BINDIR)/fan-tray
	rm -f  $(LIBEXECDIR)/fan-tray-helper
	rm -f  $(POLICYDIR)/$(ACTION).policy
	rm -f  $(RULESDIR)/49-fan-control-kde.rules
	rm -f  $(UNITDIR)/fan-tray-restore.service
	rm -f  $(APPDIR)/fan-control-kde.desktop
	rm -rf $(STATEDIR)
