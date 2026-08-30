# Fan Control KDE

A system tray applet for KDE Plasma that sets **CPU/case fan** and **NVIDIA GPU
fan** speed. Tray icon only — no windows, no dialogs. The icon is a fan that
spins at a rate proportional to the *measured* RPM, and stops only when the
fans have actually stopped.

![icons](docs/icons.png)

_The nine icon styles, each drawn at runtime._

## What it does

- Sets motherboard fan headers (via the kernel `hwmon` interface) and the
  NVIDIA GPU fan (via `nvidia-settings`).
- Shows live RPM and temperature for both, refreshed every 4 s.
- Optionally restores your chosen speeds on every boot.
- Nine hand-drawn fan icons, painted at runtime so they follow your panel's
  colour in light and dark themes.

## Supported hardware

Everything is discovered at startup by probing sysfs — nothing is hardcoded for
a particular board or card. A controller that cannot be driven is still listed,
with the reason, instead of being hidden.

| | Control | Notes |
|---|---|---|
| **Motherboard fan headers** | yes | any chip exposing `pwmN` under `/sys/class/hwmon` — `nct6775` family, `it87`, `f71882fg` and friends |
| **AMD RX 400/500** (Polaris) | yes | classic `amdgpu` hwmon `pwm1` |
| **AMD RX 5000/6000** (RDNA/RDNA2) | yes | same interface |
| **AMD RX 7000** (RDNA3) | usually | some boards' firmware refuses manual PWM; the write fails and the app says so instead of pretending |
| **NVIDIA** (proprietary driver) | yes | through `nvidia-settings`; needs an X or XWayland session |
| **Intel Arc** (`i915`) | read only | the driver exposes `fan1_input` but no PWM |
| **Intel Arc** (`xe`) | read only | PWM control is not in mainline yet |
| **Integrated GPUs** | n/a | no fan of their own; skipped automatically |

## Requirements

| | |
|---|---|
| Desktop | KDE Plasma (X11 or Wayland) — needs a StatusNotifierItem tray |
| Python | 3.9+ |
| Qt bindings | **PySide6** |
| Privileges | **polkit** (`pkexec`) |
| Init | **systemd**, only for the "keep after reboot" option |
| Optional | `lspci` for readable GPU names, `nvidia-settings` for NVIDIA |

If `sensors` shows no fans, the Super I/O driver is probably not loaded — try
`sudo modprobe nct6775` (or run `sudo sensors-detect`).

### Fedora
```
sudo dnf install python3-pyside6 polkit lm_sensors pciutils
```
### Arch
```
sudo pacman -S pyside6 polkit lm_sensors pciutils
```

## Install

Download a package from [Releases](../../releases), or:

```bash
git clone https://github.com/gabrielmf1998/fan-control-kde
cd fan-control-kde
sudo make install
```

Then start `fan-tray`, or log out and back in — the desktop entry autostarts it.

## Hardware quirks worth knowing

These are not bugs in this program; they are how the hardware behaves.

**The NVIDIA API only accepts 30–100 %.** `GPUTargetFanSpeed` refuses anything
lower — and `nvidia-settings` still exits 0 when it refuses, so a naive tool
reports success while the fan never moves. The helper clamps to the driver's
own advertised range and then **reads the speed back** to report what really
happened. Many cards still stop their fans entirely at the low end via their
own zero-RPM mode, so 0 % is often a real outcome.

**AMD RX 7000 may refuse manual control.** The kernel exposes `pwm1_enable`
on every `amdgpu` card, but on some RDNA3 boards the firmware rejects the
write. The app reports the errno it got rather than claiming success. Those
cards still accept a fan curve through `gpu_od/fan_ctrl/fan_curve`, which this
version does not drive yet.

**Motherboard fans may not stop at 0 %.** Most 4-pin fans have a mechanical
minimum and keep turning at ~500 rpm even at 0 % duty. If your board exposes
DC mode (`pwmN_mode = 0`) the fan can be stopped by cutting voltage, but many
boards are PWM-only and reject the switch.

**NVIDIA exposes no `hwmon`.** There is no `pwm` file in `/sys` for the GPU;
`nvidia-settings`/NVML is the only route, which is why an X or XWayland session
is required even on Wayland.

## How it is put together

```
fan-tray            tray applet (PySide6), runs as you
fan-tray-helper     runs as root through polkit; only touches fan controls
```

The helper is bound to a single polkit action. `data/49-fan-control-kde.rules`
lets members of `wheel` change fan speed without a password — delete it if you
would rather be asked (you then get one prompt per session).

A tray menu is exported over **DBusMenu** and drawn by the panel, not by Qt.
That protocol carries labels, checkmarks, separators and submenus and nothing
else, which is why speed is a list of levels rather than a slider: an embedded
widget has no representation in it and renders as an empty box.

## Uninstall

```bash
sudo make uninstall
```

## Licence

MIT
