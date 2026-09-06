%global bin fan-control

Name:           fan-control-kde
Version:        2.3.0
Release:        1%{?dist}
Summary:        Tray applet for fan speed, fan curves and temperatures

License:        MIT
URL:            https://github.com/gabrielmf1998/Fan-Control-KDE
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3

Requires:       python3
Requires:       python3-pyside6
Requires:       polkit
Requires:       systemd
# lm_sensors ships the tooling that loads the Super I/O driver in the first
# place; nvidia-settings is only needed on an NVIDIA machine, so neither is a
# hard dependency.
Recommends:     lm_sensors
Recommends:     pciutils
Suggests:       nvidia-settings

%description
Fan Control KDE puts every fan the machine will admit to having in the system
tray: motherboard headers one by one through the kernel's own hwmon interface,
AMD cards through amdgpu and its overdrive fan curve, and NVIDIA cards through
nvidia-settings.

Set a speed by hand, hand a fan back to its firmware, or draw a fan curve on a
graph and have a small system service run it - with hysteresis, separate ramp
rates up and down, a spin-up kick for fans that will not start from stopped, and
a zero-rpm cut-off. Where the hardware has a curve of its own - the Smart Fan IV
anchor points on an nct6775-family Super I/O, or the overdrive fan curve on an
RDNA3 or RDNA4 Radeon - the same curve can be written into the firmware so it
runs with nothing loaded at all.

Calibration sweeps a fan and writes down the duty it actually starts turning at,
which is the one thing a curve cannot be guessed without.

One icon can speak for the whole machine, or be pinned to a single fan, and
there can be as many as you have fans worth watching - each with an appearance
of its own, so the CPU icon and the GPU icon are not the same picture twice.
Headers the board never populated can be hidden outright.

53 icon shapes, 30 of them fan rotors - a three-blade classic, sickle, scythe
and maple blades, a squirrel cage, a bladeless ring, a counter-rotating pair -
and 44 animations, including motion blur that smears the trailing edge across a
real arc the way a fast fan actually looks. A colour and an animation per state,
a number badge on the icon, and a rotor that turns at a rate taken from the
measured rpm.

Privileged work goes through two polkit actions on two helpers: one for fans,
which the shipped rules file lets wheel through without a prompt, and a separate
one for installing an update, which always asks.

%prep
%autosetup -n %{name}-%{version}

%build
%{__python3} -m py_compile fancontrol/*.py helper/fan-control-helper \
    helper/fan-control-installer
rm -rf fancontrol/__pycache__

%install
install -d %{buildroot}%{_datadir}/%{name}/fancontrol
install -m 0644 fancontrol/*.py %{buildroot}%{_datadir}/%{name}/fancontrol/
install -Dm 0755 packaging/%{bin} %{buildroot}%{_bindir}/%{bin}
install -Dm 0755 packaging/fan-tray %{buildroot}%{_bindir}/fan-tray
install -Dm 0755 helper/fan-control-helper \
    %{buildroot}%{_libexecdir}/fan-control-helper
install -Dm 0755 helper/fan-control-installer \
    %{buildroot}%{_libexecdir}/fan-control-installer
install -Dm 0644 polkit/io.github.gabrielmf1998.fancontrol.policy \
    %{buildroot}%{_datadir}/polkit-1/actions/io.github.gabrielmf1998.fancontrol.policy
install -Dm 0644 polkit/49-fan-control-kde.rules \
    %{buildroot}%{_sysconfdir}/polkit-1/rules.d/49-fan-control-kde.rules
install -Dm 0644 packaging/%{name}.desktop \
    %{buildroot}%{_datadir}/applications/%{name}.desktop
install -Dm 0644 systemd/fan-control-kde-restore.service \
    %{buildroot}%{_prefix}/lib/systemd/system/fan-control-kde-restore.service
install -Dm 0644 systemd/fan-control-kde-curve.service \
    %{buildroot}%{_prefix}/lib/systemd/system/fan-control-kde-curve.service
install -Dm 0644 systemd/fan-control-kde.service \
    %{buildroot}%{_prefix}/lib/systemd/user/fan-control-kde.service
for s in 48 64 128 256 512; do
    install -Dm 0644 assets/%{name}-${s}.png \
        %{buildroot}%{_datadir}/icons/hicolor/${s}x${s}/apps/%{name}.png
done
install -Dm 0644 assets/%{name}.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/%{name}.svg
install -d %{buildroot}%{_sysconfdir}/fan-control-kde
install -Dm 0644 LICENSE %{buildroot}%{_datadir}/licenses/%{name}/LICENSE
install -Dm 0644 README.md %{buildroot}%{_datadir}/doc/%{name}/README.md

%post
%systemd_post fan-control-kde-restore.service fan-control-kde-curve.service
# 1.x called the boot service something else. If it was enabled, carry that
# choice over rather than silently dropping it, and clear the dangling link the
# removed unit file leaves behind.
if [ -L %{_sysconfdir}/systemd/system/graphical.target.wants/fan-tray-restore.service ]; then
    rm -f %{_sysconfdir}/systemd/system/graphical.target.wants/fan-tray-restore.service
    systemctl enable fan-control-kde-restore.service >/dev/null 2>&1 || :
fi
# an entry from the pre-packaging manual install, if it is still around
rm -f %{_datadir}/applications/fan-tray.desktop
touch --no-create %{_datadir}/icons/hicolor &>/dev/null || :

%posttrans
gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :

%preun
%systemd_preun fan-control-kde-restore.service fan-control-kde-curve.service

%postun
%systemd_postun fan-control-kde-restore.service fan-control-kde-curve.service

%files
%license LICENSE
%doc README.md
%{_bindir}/%{bin}
%{_bindir}/fan-tray
%{_libexecdir}/fan-control-helper
%{_libexecdir}/fan-control-installer
%{_datadir}/%{name}/
%{_datadir}/applications/%{name}.desktop
%{_datadir}/polkit-1/actions/io.github.gabrielmf1998.fancontrol.policy
%{_datadir}/icons/hicolor/*/apps/%{name}.*
%{_prefix}/lib/systemd/system/fan-control-kde-restore.service
%{_prefix}/lib/systemd/system/fan-control-kde-curve.service
%{_prefix}/lib/systemd/user/fan-control-kde.service
%config(noreplace) %{_sysconfdir}/polkit-1/rules.d/49-fan-control-kde.rules
%dir %{_sysconfdir}/fan-control-kde

%changelog
* Sun Sep 06 2026 Gabriel Marques Ferrarezi <110578985+gabrielmf1998@users.noreply.github.com> - 2.3.0-1
- Each tray icon can have an appearance of its own: its own shape, colours,
  animations, badge, size and rotation range. A CPU icon and a GPU icon no
  longer have to be the same picture in two places
- Appearance and States are edited for whichever icon is picked at the top of
  the settings window; an icon either follows the shared look or has a
  complete one of its own, with nothing in between to guess at
- An icon's own Appearance menu edits that icon when it has a look of its own,
  so picking a shape from it no longer changes every other icon too
- Frame rate stays shared: one timer drives every icon and cannot redraw two of
  them at two different rates without one tearing

* Sun Sep 06 2026 Gabriel Marques Ferrarezi <110578985+gabrielmf1998@users.noreply.github.com> - 2.2.0-1
- Fans can be hidden. A board wires more headers than it populates and the
  empty ones are still real pwm channels the kernel reports at 100%, so they
  filled the menu and the tooltip with rows about nothing. One button hides
  every header reporting no rpm; the Fans tab brings any of them back
- An icon can be pinned to a single fan instead of speaking for the whole
  machine, so it stops averaging the CPU header and the graphics card into one
  number that describes neither
- More than one icon: tick "Own tray icon" on as many fans as you like and get
  one each, with its own state, its own rotor speed and its own menu

* Sat Sep 05 2026 Gabriel Marques Ferrarezi <110578985+gabrielmf1998@users.noreply.github.com> - 2.1.1-1
- The animation no longer stutters. Three separate causes: the frame timer was
  restarted on every poll, which threw away the pending frame once every 2.5
  seconds; motion was counted in ticks rather than in seconds, so a late frame
  slowed the animation instead of catching it up; and the timer was a coarse
  one, which Qt lets the kernel coalesce with other timers
- The icon is one pixmap per frame now, not four. The panel decodes every frame
  on the other side of D-Bus, and being handed four images for a cell that
  draws one of them made it quietly coalesce frames
- Rotation is held below the rate at which the blades strobe. An 18-blade jet
  turbine repeats every 20 degrees, so at full rpm and 30 fps it was advancing
  three quarters of a blade per frame - past the halfway point where the eye
  stops seeing rotation and starts seeing a wagon wheel running backwards.
  There is a switch for it in Appearance for anyone who wants the literal rpm

* Sat Sep 05 2026 Gabriel Marques Ferrarezi <110578985+gabrielmf1998@users.noreply.github.com> - 2.1.0-1
- 22 more icon shapes, all of them fans: paddle, 7/9/11-blade axial, sickle,
  scythe, maple, helix, star, turbofan, shrouded, ducted, squirrel cage, water
  wheel, a 4-pin case fan, a wire cage, a desk fan, an exhaust fan, a
  cross-flow drum, a bladeless ring, a counter-rotating pair and a heatpipe
  cooler - 53 in total, 30 of them rotors
- 15 more animations, including motion blur and a long blur trail that smear
  the trailing edge across a real arc, an oscillating-fan swing, wind up and
  wind down, brake and go, judder, flicker, elastic and tilt - 44 in total

* Sat Sep 05 2026 Gabriel Marques Ferrarezi <110578985+gabrielmf1998@users.noreply.github.com> - 2.0.0-1
- Fan curves, drawn on a graph and run by a system service: hysteresis, split
  ramp rates, a spin-up kick and a zero-rpm cut-off
- The same curve can be written into the firmware on nct6775-family Super I/O
  chips and on RDNA3/RDNA4 Radeons, where it runs with nothing loaded at all
- Calibration: sweeps a fan and reports the duty it really starts turning at
- Every motherboard header is its own fan now, instead of one ganged device
- A settings window: 31 icon shapes, 29 animations, a colour and an animation
  per state, icon size, frame rate, rotation range, a number badge
- Check for updates against both forges, and install one from the window
- Start with the system, from the menu or the settings window
- Temperature sources are listed and pickable, and the ones a board leaves
  unpopulated no longer make the icon go red

* Wed Sep 03 2026 gabrielmf1998 <110578985+gabrielmf1998@users.noreply.github.com> - 1.2.0-1
- 15 icon styles, up from 9
- 11 colour modes including rainbow, prism, and heat/velocity from live sensors
- 7 motion modes and a selectable frame rate from 12 to 45 fps
- Check for updates against both GitHub and GitLab from the menu

* Fri Aug 29 2026 gabrielmf1998 <110578985+gabrielmf1998@users.noreply.github.com> - 1.1.1-1
- Ships its own icon: the referenced sensors-fan does not exist in Breeze
- Removes the stale fan-tray.desktop left by a pre-packaging install

* Fri Aug 29 2026 gabrielmf1998 <110578985+gabrielmf1998@users.noreply.github.com> - 1.1.0-1
- Hardware is now discovered at runtime instead of hardcoded
- AMD GPUs supported through the amdgpu hwmon pwm interface
- Intel GPUs detected and listed as monitor-only
- Any Super I/O chip with pwm channels works, not just nct6xxx

* Thu Aug 28 2026 gabrielmf1998 <110578985+gabrielmf1998@users.noreply.github.com> - 1.0.2-1
- Switching the GPU to Auto no longer reports "nvidia-settings failed" on success
- A speed change no longer reports a mid-ramp reading; only a real clamp is announced

* Fri Aug 28 2026 gabrielmf1998 <110578985+gabrielmf1998@users.noreply.github.com> - 1.0.1-1
- Helper state path now matches the packaged /etc/fan-control-kde directory

* Fri Aug 28 2026 gabrielmf1998 <110578985+gabrielmf1998@users.noreply.github.com> - 1.0.0-1
- First release
