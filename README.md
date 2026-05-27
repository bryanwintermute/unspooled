# unspooled

**Stdlib-only Python CLI to configure Rongta RP332 thermal receipt
printers — replacing the Windows-only vendor tool with seven Python
scripts and zero third-party dependencies.**

The Rongta RP332 (and likely related Rongta SKUs) ships with a
proprietary Windows-only configuration utility (`PrinterTool.exe`)
that flips NV-RAM defaults like auto-cutter, buzzer, paper width,
DHCP, and Chinese-character mode. None of those settings are
exposed via standard ESC/POS escapes; the bytes are vendor-private
and absent from Rongta's mobile SDKs (the documented methods are
stub implementations that return `nil`).

`unspooled` reverse-engineered every command the vendor tool emits
and re-implements them in seven small Python scripts you can run
from any Linux host with the printer attached.

## Why "unspooled"?

The vendor tool talks to the printer through the Windows print
spooler. We routed that spool through a logging CUPS backend on
Linux (the printer presented to Wine as a CUPS printer) and
captured every byte. The project is the printer literally being
"unspooled" out of the vendor pipeline — and the protocol itself
being unspooled into something documented.

## Hardware

- **Printer:** Rongta RP332, 80mm thermal, auto-cut, USB+Serial+Ethernet.
- **USB id:** `0fe6:811e` (the printer presents as an ICS Advent
  Parallel Adapter — Rongta licenses the USB-to-parallel chip from
  ICS Advent).
- **Likely also works on:** other Rongta SKUs that share the
  `PrinterTool.exe` config tool (RP325, RP326, RP328 are reported
  to share the protocol family but **untested**; PRs welcome).

## Requirements

- Python 3.9+ (stdlib only, no third-party packages)
- A Linux host with the printer attached via USB
- Membership in the `plugdev` group (so you can write to the
  printer without `sudo`)
- The udev rule in this repo (`99-rongta-receipt.rules`) installed
  to `/etc/udev/rules.d/`

## Setup

```bash
git clone git@github.com:bryanwintermute/unspooled.git
cd unspooled

# Install the udev rule (one-time, requires sudo)
sudo install -o root -g root -m 0644 99-rongta-receipt.rules \
  /etc/udev/rules.d/99-rongta-receipt.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --action=change /sys/class/usbmisc/lp0
sudo udevadm settle

# Verify the symlink exists
ls -la /dev/rongta-receipt  # should point to usb/lp0
```

Add yourself to `plugdev` if you're not already (log out + back in
after):

```bash
sudo usermod -aG plugdev "$USER"
```

## Quick reference

The unified entry point is `rongta_config.py`. It dispatches to
six per-tab modules (each of which is also runnable standalone if
you prefer narrower help):

```bash
# Out-of-the-box: enable DHCP so the printer is reachable on the LAN.
./rongta_config.py ethernet dhcp on

# Out-of-the-box: enable the NV-gated auto-cutter (off from factory).
./rongta_config.py base --cutter on

# Aggressive paper-saving for shopping-list-style receipts.
./rongta_config.py papersave --delete-top enable --cut-line-interval 75%

# Switch paper width to 58mm.
./rongta_config.py other1 print-width 58mm

# Print a list.
echo -e 'milk\neggs\nbread' | ./rongta_config.py print --title 'Costco'

# Full help for any area:
./rongta_config.py <area> --help
```

### Areas

| Area | Module | Coverage |
|---|---|---|
| `base` | `nv_config.py` | Cutter, buzzer, drawer kick, font, density, char/line, **43 code pages**, baud rate, parity, auto-reprint, buzzer-after-print. |
| `ethernet` | `ethernet_config.py` | DHCP, static IP, submask, gateway, MAC address, link mode. |
| `papersave` | `papersave_config.py` | Whitespace trimming (uses standard Epson `GS ( E`). |
| `blackmark` | `blackmark_config.py` | Black-mark sensor: enable/disable, length, width, print/cut offset. |
| `other1` | `other1_config.py` | Paper width (80mm/58mm), buzzer volume, alarm, USB enumeration mode, Chinese character mode, cutter-count query. |
| `print` | `receipt_print.py` | Render a list (with `--title`, `--style`, etc.) as ESC/POS. |

## Command-family catalogue

Roughly half of what the vendor tool emits is **standard Epson
ESC/POS** — documented in the public Epson TM-T88 / TM-T20 spec.
The other half is Rongta-vendor extensions with no public docs.

| Prefix | Family | Coverage |
|---|---|---|
| `1f 73 XX <args>` | Rongta vendor | Base tab base-config (+ sub-fns `1f 72`, `1f 74`) |
| `1f 69`, `1f 25`, `1f 4e`, `1f 6d`, `1f 70`, `1f 62 44` | Rongta vendor | Ethernet (IP/submask/gateway/MAC/duplex/DHCP) |
| `1f 1b 1f XX <args>` | Rongta vendor extended | BlackMark + Other1 |
| `1f 7b X <arg>` | Rongta vendor mode toggles | Paper sensor (`'p'`), USB mode (`'u'`) |
| `1d 28 45 ...` | **Standard Epson `GS ( E`** | PaperSave + Volume |
| `1d 28 46 ...` | **Standard Epson `GS ( F`** | BlackMark print/cut-after offsets |
| `1d 56 00` | **Standard Epson `GS V 0`** | Full-cut (runtime) |
| `12 54` | **Standard Epson DC2 'T'** | Self-test trigger |
| `1b 1b 45 ... 0c 5a` | Rongta vendor "structured" | Reset button — emits a "Setting Fail!" on this firmware. Documented but non-functional. |

## How we got the bytes

The reverse-engineering technique is fully documented in
[`docs/wine-cups-backend-recovers-nv-bytes.md`](docs/wine-cups-backend-recovers-nv-bytes.md).
TL;DR:

1. **usbip-export the printer** from the Pi it lives on to an
   x86_64 Linux host (so Wine can run on x86 while the printer
   stays on the Pi).
2. **Run `PrinterTool.exe` under Wine** (Xvfb + x11vnc lets you
   click through it from a phone VNC client).
3. **Install a custom CUPS backend** at
   `/usr/lib/cups/backend/rongta` (mode `0700` so it runs as root)
   that `tee`s every print-spool job to `/tmp/rongta-writes/<ns>.bin`.
4. **Click through the GUI**: each click = one labelled `.bin`
   file. Diff them to find the bytes that change.
5. **Static-analyse the PE binary** for big enums: dropdown labels
   in MFC tools are stored as contiguous string literals in
   `.rdata` (in **reverse source order** by MSVC), so
   `strings -el -t d PrinterTool.exe | sort -rn` gives you the
   dropdown labels in their wire-byte index order. (We mapped all
   43 code pages this way after a single spot-click confirmed the
   pattern.)

See [`docs/`](docs/) for the full lesson set:

- [`wine-cups-backend-recovers-nv-bytes.md`](docs/wine-cups-backend-recovers-nv-bytes.md)
  — the core technique with 7 distinct RE patterns.
- [`vendor-mobile-sdks-may-stub-nv-config.md`](docs/vendor-mobile-sdks-may-stub-nv-config.md)
  — the prequel: how we disassembled Rongta's iOS/Android SDKs and
  proved the NV-config methods were stubs.
- [`escpos-thermal-printers-need-no-cups-driver.md`](docs/escpos-thermal-printers-need-no-cups-driver.md)
  — the foundational lesson: ESC/POS printers don't need CUPS for
  the basic print path.
- [`rongta-rp332-vendor-tool-replacement-recap.md`](docs/rongta-rp332-vendor-tool-replacement-recap.md)
  — project-recap: what was built, what's still TODO.
- [`udev-settle-after-trigger-or-rebind.md`](docs/udev-settle-after-trigger-or-rebind.md)
  — the trigger/settle discipline used in the setup recipe.

## Status / TODO

All major NV-setting tabs in `PrinterTool.exe` v2.63.0 are
reverse-engineered. Remaining items (all nice-to-haves):

- **Bluetooth setting tab** — RP332 has no BT hardware; tab might
  emit no-op commands or preview a different family for other
  Rongta SKUs.
- **UDP discovery** (the tool's "Search Printer" tab) — would be
  nice as a Python equivalent.
- **Capture cutter-stats response** — the cutter-count query is
  exposed as `rongta_config.py other1 cutter-query`, but the
  response comes back on BULK-IN, which the CUPS backend doesn't
  relay. Capture with `usbmon` to decode and parse.
- **Find a working factory-reset command** — the GUI's Reset
  button emits a 13-byte structured packet that the firmware
  rejects ("Setting Fail!"). Trailing `0c 5a` smells like a
  checksum; figuring it out + sending a real reset would be neat.

See [`docs/rongta-rp332-vendor-tool-replacement-recap.md`](docs/rongta-rp332-vendor-tool-replacement-recap.md)
for the full wishlist.

## License

Apache-2.0. See [`LICENSE`](LICENSE).

## Safety

Many of the commands in this CLI write to NV-RAM and are
**persistent across power cycles**. Wrong values can leave the
printer in an unrecoverable state via USB (e.g., the `usb-mode
virtual-serial` command makes the printer re-enumerate as
`/dev/ttyACM*` instead of `/dev/usb/lp0`, breaking the udev rule
in this repo). Use `--dry-run` to see exactly what bytes will be
written. Read the docstring of each module before flipping
anything you don't already understand.

The CLI is its own factory-reset: re-running with known-good
defaults restores the printer's state.
