Name:           fan-control-kde
Version:        1.1.0
Release:        1%{?dist}
Summary:        Tray applet to control CPU, case and NVIDIA GPU fan speed on KDE

License:        MIT
URL:            https://github.com/gabrielmf1998/fan-control-kde
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  make
BuildRequires:  python3

Requires:       python3
Requires:       python3-pyside6
Requires:       polkit
Recommends:     pciutils
Requires:       systemd
# lm_sensors ships the hwmon tooling; nvidia-settings is optional and only
# needed for GPU control, so it is deliberately not a hard dependency.
Recommends:     lm_sensors

%description
A system tray applet for KDE Plasma that sets motherboard fan header speeds
through the kernel hwmon interface and the NVIDIA GPU fan through
nvidia-settings. Tray icon only, with a fan that spins in proportion to the
measured RPM. Speeds can optionally be restored on every boot.

Privileged operations go through a single polkit action bound to a helper that
touches nothing but fan controls.

%prep
%autosetup

%build
%make_build check

%install
%make_install PREFIX=%{_prefix}

%post
%systemd_post fan-tray-restore.service

%preun
%systemd_preun fan-tray-restore.service

%postun
%systemd_postun fan-tray-restore.service

%files
%license LICENSE
%doc README.md
%{_bindir}/fan-tray
%{_libexecdir}/fan-tray-helper
%{_datadir}/applications/fan-control-kde.desktop
%{_datadir}/polkit-1/actions/io.github.gabrielmf1998.fancontrol.policy
%{_prefix}/lib/systemd/system/fan-tray-restore.service
%config(noreplace) /etc/polkit-1/rules.d/49-fan-control-kde.rules
%dir /etc/fan-control-kde

%changelog
* %s gabrielmf1998 <110578985+gabrielmf1998@users.noreply.github.com> - 1.1.0-1
- Hardware is now discovered at runtime instead of hardcoded
- AMD GPUs supported through the amdgpu hwmon pwm interface
- Intel GPUs detected and listed as monitor-only
- Any Super I/O chip with pwm channels works, not just nct6xxx
- The menu is built from whatever the machine actually has

* %s gabrielmf1998 <110578985+gabrielmf1998@users.noreply.github.com> - 1.0.2-1
- Switching the GPU to Auto no longer reports "nvidia-settings failed" on success
- A speed change no longer reports a mid-ramp reading; only a real clamp is announced

* Fri Aug 28 2026 gabrielmf1998 <110578985+gabrielmf1998@users.noreply.github.com> - 1.0.1-1
- Helper state path now matches the packaged /etc/fan-control-kde directory

* Fri Aug 28 2026 gabrielmf1998 <110578985+gabrielmf1998@users.noreply.github.com> - 1.0.0-1
- First release
