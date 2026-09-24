# Fan Control KDE

Every fan the machine will admit to having, in the system tray. Set a speed by
hand, hand a fan back to its firmware, or draw a fan curve on a graph. A small
system service keeps every speed where you put it, puts it all back after a
reboot, and runs the curves.

![Icon styles](docs/icon-styles.png)

The icon is painted every frame rather than loaded from a file, which is what
lets it spin at a rate taken from the **measured rpm**, take a colour from the
hottest sensor, and follow the panel's own foreground in light and dark themes.

---

## Install

One line, on Fedora, openSUSE, Debian, Ubuntu, Arch and their derivatives -
Kubuntu, KDE neon, Nobara, Manjaro, EndeavourOS and CachyOS included:

```sh
curl -fsSL https://raw.githubusercontent.com/gabrielmf1998/Fan-Control-KDE/main/install-online.sh | sh
```

or from the mirror:

```sh
curl -fsSL https://gitlab.com/gabriel17166/fan-control-kde/-/raw/main/install-online.sh | sh
```

It works out which package your distribution wants, takes it from the latest
release, checks it against the `SHA256SUMS` published beside it, and installs it.
Where the distribution packages no PySide6 - Ubuntu 24.04 and everything built
on it, and Debian 12 - it brings its own, as a second package.

<details>
<summary>Or take a package from the release page</summary>

| Distribution | File |
| --- | --- |
| Fedora, RHEL, Nobara, openSUSE | `fan-control-kde-2.4.0-1.fc*.noarch.rpm` |
| Debian, Ubuntu, Kubuntu, KDE neon, Mint | `fan-control-kde_2.4.0-1_all.deb` |
| ...plus, where there is no PySide6 (Ubuntu 24.04 and its family, Debian 12) | `fan-control-kde-pyside6_6.10.3-1_amd64.deb` |
| Arch, Manjaro, EndeavourOS, CachyOS | `fan-control-kde-2.4.0-1-any.pkg.tar.zst` |
| Anything else | `Fan-Control-KDE-x86_64.AppImage` |

Install the two `.deb` files together: `sudo apt install ./fan-control-kde_*.deb`.

The AppImage needs `python3` on the system, and uses the system's PySide6 when
there is one or the copy inside when there is not. It **cannot ship the
privileged helper** — `pkexec` will only run a real file on disk that a polkit
policy names by path — so on its own it can watch the fans but not change them,
because every fan control on Linux needs root.

</details>

<details>
<summary>Or from a clone</summary>

```sh
git clone https://github.com/gabrielmf1998/Fan-Control-KDE
cd fan-control-kde
./install.sh
```

`./install.sh uninstall` takes it back out. Your settings and curves stay.

</details>

Once it is running: **Settings → Updates → Check for updates** finds a newer
release on either forge, shows what changed, and installs it on a click.

---

## What it can drive

Fan control is not one interface, it is four, and which one a machine has
decides what is possible on it. This is what each one actually gives you.

### Motherboard headers — the CPU fan and the case fans

Through the kernel's own `hwmon` PWM interface, so **any chip with a driver
works**: the whole nct6775 family (nct6106 through nct6799), it87, f71882fg,
w83627, `dell_smm` on Dell laptops, `thinkpad_acpi`, `applesmc`, the ASUS WMI
and EC sensor drivers.

Every header is its own fan here, listed and controlled one at a time — not one
ganged "CPU / case" device. Header 1 is guessed to be the CPU fan and the rest
chassis headers, and you can rename any of them to whatever is actually plugged
in.

> **AMD or Intel makes no difference to this.** The CPU fan header is on the
> motherboard, driven by the board's Super I/O chip; the CPU is not involved in
> its own fan at all. A Ryzen machine and a Core machine are the same problem.
> What differs is the *temperature* you point a curve at: `k10temp` (Tctl/Tccd)
> on AMD, `coretemp` (Package id 0) on Intel. Both are listed.

If nothing turns up, the Super I/O driver is not loaded. `sudo sensors-detect`
finds it; a few boards also need `acpi_enforce_resources=lax` on the kernel
command line, because ACPI claims the chip and the driver politely stands down.

### AMD Radeon

| Cards | How | What you get |
| --- | --- | --- |
| RX 400, RX 500 (Polaris), Vega, RX 5000 (RDNA1), RX 6000 (RDNA2) | `amdgpu` hwmon `pwm1` | Flat manual duty, auto, full range |
| RX 7000 (RDNA3), RX 9000 (RDNA4) | overdrive fan curve, `gpu_od/fan_ctrl/` | A **firmware fan curve**, zero-rpm, acoustic limits |

RDNA3 and RDNA4 are the important row. Those cards' firmware very often
**refuses flat manual PWM** — the write lands, the driver returns success, and
the fan does not move. What they do have is a real fan curve in the firmware, and
this writes to it. Draw the curve, press *Write it into the firmware*, and the
card runs it with nothing loaded at all.

That interface needs OverDrive turned on, which is a kernel parameter:

```
amdgpu.ppfeaturemask=0xffffffff
```

Zero-rpm control (`fan_zero_rpm_enable`, `fan_zero_rpm_stop_temperature`) is
RDNA3-and-newer on Linux 6.13 or later.

### NVIDIA

GeForce, Quadro and RTX cards, through **NVML** — the driver's own library, the
one `nvidia-smi` is built on. It needs no X display and no `Coolbits`: it works
on a Wayland session, and from the background service before anyone has logged
in, which is where a speed has to be put back after a reboot. Every speed is
read back afterwards, so what you are told is what the driver actually kept.

That takes driver 520 or newer. On an older one the helper falls back to
`nvidia-settings`, which needs `Coolbits` in the X configuration
(`sudo nvidia-xconfig --cool-bits=28`) and an X or XWayland display.

Most GeForce cards clamp their minimum to about 30%; the range the driver
reports is read out of it, and the menu will not offer anything below it. NVIDIA
exposes no firmware fan curve to Linux, so a curve on an NVIDIA card is run by
the background service.

### Intel

Discrete Arc cards report fan speed through the `i915`/`xe` hwmon
(`fan1_input`), and that is all mainline has: the PWM control patches for `xe`
are not merged. Those cards are listed as monitor-only, with that as the stated
reason rather than being hidden. If a kernel with the control patches is running,
the PWM channel appears and the generic hwmon backend drives it with no changes
here.

Intel integrated graphics have no fan; the fan cooling an Intel CPU is on a
motherboard header, covered above.

---

## Fan curves

![The curve editor](docs/curve-editor.png)

Drag the points. Click the empty graph to add one, right-click a point to remove
it, hold <kbd>Shift</kbd> while dragging to change only the duty.

The dashed green line is the sensor this curve follows, *right now*. The filled
dot is what the curve asks for at that temperature; the hollow ring is what the
fan is actually doing. Watching those two while a game loads tells you more about
whether a curve is right than any amount of arithmetic.

Nine starting points — Silent, Quiet, Balanced, Performance, Aggressive, Linear,
Stepped, Zero RPM, Full blast — and every one of them is just a curve, so you can
grab a preset and then move it.

**How it responds**, all of it per fan:

| | |
| --- | --- |
| **Hysteresis** | How far the temperature has to fall before the fan eases off. This is what stops a fan hunting up and down at a steady load. |
| **Ramp up / ramp down** | Percentage points per second, separately in each direction. Slow on the way down is what makes a curve sound calm. |
| **Never below / never above** | A floor and a ceiling, drawn on the graph where they will bite. |
| **Stop the fan below** | Zero-rpm: below this temperature the fan stops entirely. |
| **Kick to start at** | A stopped fan will not take a low duty from standing. This gives it a shove for a moment first. |

### Calibration — what the fan actually does

Guessing the bottom of a curve is the one thing you cannot do from a datasheet,
because it is not the fan's specification, it is *this* fan on *this* header.

*Calibrate* sweeps it from 0% to 100% in steps, waits for it to settle at each
one, and writes down the rpm. Out of that comes the number that matters: **the
duty this fan actually starts turning at**. A curve that dips below it does not
run the fan quietly — it stops it.

Take the measurement, pick a style, and it builds a curve that respects it.

### Where a curve runs

**In a system service.** Press *Apply and run* and the curve is saved, switched
on, and run by `fan-control-kde-daemon.service` from then on — now, and after
every reboot, whether or not anyone is logged in — until you press *Stop this
curve* or set that fan's speed by hand. Stopping it puts the fan back on the
speed you last set by hand, or hands it to the firmware if you never set one.

The service hands every fan a curve was driving back to the firmware when it
stops — a curve daemon that dies must not leave a fan at 20% while the CPU
cooks. Above 95 °C every curve is overridden and the fan goes to 100%; a fan
curve is a comfort setting and that part is not negotiable. If a curve's
temperature source stops answering, that fan goes to 70% rather than to silence.

**Or in the firmware**, where the hardware has one:

* nct6775-family Super I/O chips have Smart Fan IV — five anchor points and a
  temperature source. The curve is resampled to those five, the top one pinned
  at full speed, and written in.
* RDNA3 and RDNA4 Radeons have the overdrive fan curve described above.

A firmware curve runs with nothing loaded: before login, while the machine is
booting, and in any other operating system on it. *Undo that* hands the fan back.

---

## The rest of it

![Icon shapes](docs/icon-styles.png)

**53 icon shapes, 30 of them fan rotors.** Three-blade classic, tri-blade,
pinwheel, propeller, paddle, axial in 7, 9 and 11 blades, sickle and scythe and
maple blades, a helix, a star, a turbine, a turbofan, a jet turbine, a shrouded
rotor, a ducted fan, a blower, a squirrel cage, a water wheel, an impeller, a
spiral, a vortex, a ceiling fan, a windmill, leaf blades.

Then **17 housings**, where the frame stays still and only the rotor turns: a
case fan, a case fan with its 4-pin tail, hex and round frames, a wire cage, a
desk fan on its stand, a wall exhaust fan, a cross-flow drum, a bladeless ring, a
counter-rotating pair, twin fans, a radiator, a tower cooler, a heatpipe cooler,
an AIO pump, a CPU and a graphics card.

And **six meters** that show a reading instead of turning: a heatsink, a dial, a
ring, bars, a thermometer and a plain number.

![The same shapes at panel size](docs/icon-styles-22px.png)

Every one of them is drawn to survive 22 px, because that is the only size that
actually matters.

![Animations](docs/animations.png)

**44 animations.** The ones worth naming are the ones that only make sense on a
fan: **Motion blur** and **Long blur trail** smear the trailing edge across a
real arc — a few degrees of smear vanishes behind the blade in front of it, so
these use a wide one, and on a dense rotor they fill into the near-solid disc a
fast fan actually looks like. **Swing** turns the blades while the whole head
sweeps, like an oscillating fan. **Rev** surges and settles the way a fan ramps
under load; **Wind up** and **Wind down** run the whole range; **Brake and go**
stops it dead for a beat. **Gusts** buffets it, **Stutter** and **Strobed spin**
freeze it the way a camera does, **Judder** shakes it with no period the eye can
lock on to, **Airflow** sweeps arcs off the blade tips, and **Glow with the
heat** brightens with the hottest sensor.

### One icon, or one per fan

A machine with six headers and a graphics card was one icon trying to be all of
them at once, and a menu with a row about every header the board never
populated.

**Hide the ones that are not there.** *Settings → Fans* has a tick beside every
fan and a button that unhides nothing and hides every header reporting no rpm at
all. Hidden fans leave the menu, the tooltip, the icon's state and the curve
list — but not the Fans tab, which is where you get them back. Be a little
careful with the button: a fan with no sense wire spins perfectly well and still
reads zero.

**Pin an icon to one fan.** *Own tray icon* on any fan gives it an icon of its
own that shows only it — its speed, its rpm, its temperature, its own rotor
rate. The whole-machine icon is just another entry in the same list, so you can
have it as well, or drop it. Any icon's own menu has **This icon follows ▸** to
repoint it without opening settings, and every fan's submenu has **Hide this
fan** for the ones you only find out are junk after you look at them.

Tick two fans and you get two icons: a CPU one and a GPU one, instead of one
icon averaging a 100% case fan and a 53% graphics card into a number that
describes neither.

### Each icon can look different

Two icons that are the same picture in two places are two icons you have to
read the tooltip of. So the appearance is per icon: **Appearance for** at the
top of the settings window picks which one the Appearance and States tabs are
editing, and **This icon has a look of its own** decides whether it follows the
shared look or keeps its own.

Its own shape, its own colour mode and per-state colours, its own animations,
its own badge, size, stroke weight, margin and rotation range. Make the CPU
icon a three-blade classic in heat colours and the GPU icon a graphics-card
outline in green, and you can tell at a glance which is which without hovering
anything.

**Naming an icon there is the instruction to edit it.** Change anything and it
gets a look of its own on the spot — the tickbox ticks itself so you can see it
happen — and Apply never touches the shared look while an icon is named. Untick
the box to hand that icon straight back to the shared look.

An icon either follows the shared look or has a complete one of its own — there
is no third state, because a per-control "inherited" tickbox is a lot of
interface for very little, and it turns "why is this one blue" into a question
with two answers.

A pinned icon's own **Appearance** menu in the tray edits that icon for the same
reason. The whole-machine icon's menu edits the shared look, because that icon
*is* the machine.

The one thing that stays shared is the **frame rate**: one timer drives every
icon, and it cannot redraw two of them at two different rates without one of
them tearing.

![States](docs/states.png)

**Nine states**, each with its own colour and its own animation, resolved top to
bottom so a machine that is too hot says so even while its fans sit at 40%:
no controller, critically hot, running hot, stopped, idle, low, medium, high,
full. Eight colour presets, or set every one by hand.

Everything else that was asked for and is now there: icon **size** (22 to 96 px),
fill of the tray cell, stroke weight, inner margin, **frame rate** (5–60 fps),
animation speed, the rotation range in degrees per second and whether rotation
follows measured rpm, requested duty or nothing; a **number badge** on the icon
showing duty, rpm, temperature or how many fans are turning, in four shapes and
any corner; a **corner pip** for who is driving the fans; **start with the
system**; per-fan **renaming**; notifications for heat, for a fan that stalls,
and for what a curve is doing; and the temperature sensors listed with the
unpopulated ones marked.

> Super I/O chips wire more thermistor inputs than any board populates, and the
> empty ones do not read as absent — they read as 15 °C, or 102 °C, or 0. Those
> are marked, and are never what turns the icon red. They stay selectable for a
> curve, because on some boards one of them really is the VRM.

---

## What it keeps, and for how long

Everything you set is kept, and nothing needs a *Save* button:

* **A speed set by hand** — from the menu, the slider or the *Max* button — is
  applied at once, written to `/etc/fan-control-kde/state.json`, and kept by
  the background service. It looks at every fan it is keeping every two
  seconds, and puts it back if anything moved it: the firmware, a driver,
  another tool. The journal says each time
  (`journalctl -u fan-control-kde-daemon`), and the Fans tab shows how often.
* **After a reboot** the service puts every speed back as it starts, before
  anyone logs in. *Settings → Behaviour → Put the speeds I set back after a
  reboot* switches that off; the speeds set since are still kept until the next
  one.
* **A curve** runs until it is stopped, across reboots.
* **Appearance, icons and names** are yours alone, in
  `~/.config/fan-control-kde/config.json`, and saved by *Apply* or *OK*.

The last thing asked of a fan wins: setting a speed by hand stops that fan's
curve, and applying a curve takes over from the speed set by hand.

---

## How it works, and what it asks for

Reading is unprivileged and constant. Everything that writes goes through a
helper under `pkexec`, and there are **two** polkit actions, on purpose:

`io.github.gabrielmf1998.fancontrol` — fans, curves, the service. The shipped
`49-fan-control-kde.rules` lets administrators — `wheel`, or `sudo` on Debian
and Ubuntu — through without a prompt, from a local session, because the tray
changes fan speeds constantly and a fan speed is worth nothing to an attacker
who already has your session. Delete that file to be asked once in a while
instead.

`io.github.gabrielmf1998.fancontrol.install` — installing an update. A separate
action on a separate binary, deliberately **not** in the rules file, and set to
ask every single time. Adding it there would turn *change a fan speed without a
password* into *install anything without a password*. The installer refuses any
package the system's own tools do not say is called `fan-control-kde`, and the
download is checked against the release's `SHA256SUMS` before it gets that far.

| Path | What is in it |
| --- | --- |
| `~/.config/fan-control-kde/config.json` | Appearance and behaviour |
| `/etc/fan-control-kde/curves.json` | The curves, and which of them run |
| `/etc/fan-control-kde/state.json` | The speeds set by hand, and whether they come back after a reboot |
| `/run/fan-control-kde/status.json` | What the service is doing right now |

The helper is a plain command-line program and is worth knowing about:

```sh
/usr/libexec/fan-control-helper status      # everything, as JSON
/usr/libexec/fan-control-helper sensors     # every temperature it can see
sudo /usr/libexec/fan-control-helper set hwmon:nct6799:pwm2 60
sudo /usr/libexec/fan-control-helper calibrate hwmon:nct6799:pwm2
sudo /usr/libexec/fan-control-helper hwcurve hwmon:nct6799:pwm1
journalctl -u fan-control-kde-daemon          # what the service has done
```

---

## When it does not work

**No fan controller found.** The Super I/O driver is not loaded — run
`sudo sensors-detect`, and if the chip is detected but the driver still refuses
it, add `acpi_enforce_resources=lax` to the kernel command line.

**A speed is accepted and nothing moves.** The write is read back, so this is
reported rather than assumed. On an RDNA3 or RDNA4 Radeon it means the firmware
wants its fan curve instead — draw one and write it in. On NVIDIA with a driver
older than 520 it means `Coolbits` is not set.

**A speed does not stay where it was set.** Something else is moving it — the
firmware, a BIOS fan profile, another fan tool — and the service is putting it
back. `journalctl -u fan-control-kde-daemon` says what it found each time. If
the tray menu says *Background service is stopped*, start it from there; nothing
keeps a speed or runs a curve while it is off.

**A fan reads 0 rpm at every duty.** Either nothing is plugged into that header,
or the fan has no sense wire. It can still be driven; it just cannot be measured,
so calibration has nothing to report and the icon takes its rotation from the
duty instead.

**The icon is not moving.** *Keep animating while the fans are stopped* is off
and the fans are stopped, which is the icon telling you the truth.

**A many-bladed shape looks like it is barely turning, or turning backwards.**
That is aliasing, and it is the reason *Hold rotation below the speed at which
the blades strobe* exists in Appearance and is on by default. A shape looks
identical every time it turns by one blade, so past about a third of that per
frame the eye stops seeing rotation: first it strobes, then — past half a blade
per frame — it runs backwards, the same wagon-wheel effect as in every western
ever filmed. An 18-blade jet turbine repeats every 20°, so at 444 °/s and 30 fps
it advances three quarters of a blade per frame. The cap is per shape: a
three-blade fan is never touched at all. Turn it off if you would rather have
the literal rpm and the strobing that comes with it.

---

## Building the packages

```sh
make check          # syntax
make test           # the service against a fake sysfs, and the settings window
make icons          # regenerate the icon and the documentation sheets
make packages       # dist/: .rpm, .deb (+ PySide6 .deb), .pkg.tar.zst, .AppImage, SHA256SUMS
```

---

MIT. Not affiliated with AMD, NVIDIA, Intel or KDE.

Mirrored at [gitlab.com/gabriel17166/fan-control-kde](https://gitlab.com/gabriel17166/fan-control-kde).
