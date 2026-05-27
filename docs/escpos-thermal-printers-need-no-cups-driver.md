# ESC/POS thermal printers don't need CUPS — write raw bytes to `/dev/usb/lpN`

**Date learned:** 2026-05-23
**Context:** Wiring up a Rongta RP332 80mm thermal receipt printer
on the `octoprint` Pi for a to-do / shopping-list printer. The Pi
inherited a half-installed broken CUPS queue `80Series2` from a prior
attempt — missing the `rastertort58_80` filter binary, so every CUPS
job died at the rasterise stage. The instinct was to fix CUPS. The
right move was to skip CUPS entirely.

## The shortcut

Linux's `usblp` kernel module unconditionally binds anything that
identifies as a USB printer-class device, and exposes it as a raw
character device at `/dev/usb/lp0` (lp1, lp2, …). For ESC/POS
printers — which is essentially every cheap thermal receipt printer,
plus most Epson, Star, Citizen, Bixolon, Rongta, Xprinter, etc.
units — **writing the right bytes to that file is all you need to
print.**

```bash
# This actually prints "HELLO\n" and cuts the paper:
printf '\x1b@\x1bt\x00HELLO\n\n\n\n\n\n\x1dV\x00' > /dev/usb/lp0
#       \------ init + CP437 -----/        \--- 5 LF + full cut ---/
```

That's it. No CUPS, no PPD, no vendor driver, no Python deps. The
"driver" is the printer's own firmware interpreting ESC/POS
command bytes mixed with payload text.

## Why this is non-obvious

The naming and the existing tooling all point you at CUPS:

- The vendor ships **a Windows / macOS driver bundle** + a CUPS
  filter for Linux. They never advertise "or just write bytes to
  the device file".
- CUPS is the canonical Linux printing layer, so every guide leads
  with "install the driver, add a queue, configure the page size".
- The Rongta RP332's CUPS queue is supposed to work via
  `rastertort58_80` — a vendor-supplied rasterise filter that takes
  PDF/PS input and emits ESC/POS. When that filter is missing or
  the wrong arch, CUPS dies with messages like:
  `"/usr/lib/cups/filter/rastertort58_80" not available: No such
  file or directory`. You then go down the rabbit hole of trying
  to install the vendor's `.deb`, which doesn't have an `arm64`
  build, which doesn't have an `armv7l` build, which doesn't have
  bullseye paths, etc.

The trap is that you're trying to turn a PDF into receipt-shaped
output, when **receipt-shaped output is what you already have**:
short lines of text with optional bold/double-size/centre-align
control bytes. The whole CUPS rasterise pipeline exists to translate
between layouts and devices that don't speak each other's language.
For a receipt printer fed plain text, it's pure overhead.

## When to actually reach for CUPS

CUPS earns its keep when:

- You need to print arbitrary PDF / PostScript / page-layout output
  (an invoice with embedded graphics, a multi-column report).
- The printer doesn't have a usable command language (some
  bitmap-only label printers).
- You want all OS apps to see "a printer" in the system print
  dialog — i.e. you actually want desktop-print-stack semantics.

A to-do list, a shopping list, an order ticket, a transaction
receipt, a barcode label — none of these need any of that.

## What you actually need

Three pieces, in order:

### 1. Confirm the kernel bound it to `/dev/usb/lpN`

```bash
$ lsusb | grep -i rongta   # or epson, star, etc.
Bus 001 Device 005: ID 0fe6:811e ICS Advent
$ ls -l /dev/usb/lp*
crw-rw---- 1 root lp 180, 0 May 23 18:48 /dev/usb/lp0
```

If you don't see `/dev/usb/lpN`, the kernel didn't bind. Either
the printer's USB class isn't `07` (printer), or `usblp` is
blacklisted (sometimes done by CUPS distributions — see
`/etc/modprobe.d/`), or the device is locked by a CUPS backend.
Unloading and reloading `usblp` (`sudo modprobe -r usblp &&
sudo modprobe usblp`) usually resolves the CUPS-holding-the-port
case.

### 2. udev rule for stable name + group ACL

So you don't need sudo for every print, and the device name is
stable across replug:

```udev
SUBSYSTEM=="usbmisc", KERNEL=="lp[0-9]*", \
  ATTRS{idVendor}=="0fe6", ATTRS{idProduct}=="811e", \
  MODE="0660", GROUP="plugdev", SYMLINK+="rongta-receipt"
```

Drop in `/etc/udev/rules.d/`, reload, replug. See
`udev-settle-after-trigger-or-rebind.md` for the diagnostic
ritual (the async race that makes the rule *look* not to apply).

### 3. A renderer that emits ESC/POS bytes

Bare minimum:

```python
ESC, GS = b"\x1b", b"\x1d"
def receipt(lines: list[str]) -> bytes:
    out  = ESC + b"@"                # initialise
    out += ESC + b"t\x00"            # code page 437 (default; latin-only)
    for ln in lines:
        out += ln.encode("cp437", errors="replace") + b"\n"
    out += b"\n" * 5                 # advance past cutter
    out += GS  + b"V\x00"            # full cut
    return out
```

For more useful control:

| Bytes | Meaning |
|---|---|
| `ESC @` | initialise |
| `ESC t 0` | code page 437 (Western Latin) |
| `ESC a 0` / `1` / `2` | align left / centre / right |
| `ESC E 1` / `0` | bold on / off |
| `ESC ! 0x30` | double-width + double-height |
| `ESC ! 0x00` | reset character formatting |
| `GS V 0` / `1` | full / partial cut |
| `LF` (`0x0a`) | line feed |

For a complete renderer with arg-parsing and library shape, see
`receipt_print.py`.

## The hardware-feature footgun: NV flags

The basic print path is driver-free, but **some hardware features
are gated by flags stored in the printer's NV memory** that ESC/POS
commands alone don't control. Sending `GS V 0` to a printer with
"Cutter: No" in its NV settings produces zero error and zero cut —
the byte stream is interpreted, the cut command is ignored, the
paper feeds and stops.

Diagnostic: the **printer's own self-test** (hold FEED + power-on
on most models) prints the NV settings. Look for lines like:

```text
Save paper: No
BMMode:     No
Cutter:     No
Beeper:     No
```

If `Cutter: No`, no ESC/POS command will get the cutter to engage
— this is empirically confirmed against the Rongta RP332 with
**every** ESC/POS cut command including `GS V 0` (full), `GS V 1`
(partial), `GS V 65 n` (feed+cut), the legacy `ESC i` (`1B 69`),
and `ESC m` (`1B 6D`). The legacy bytes are the exact ones the
vendor's own Android and iOS SDKs send (confirmed by disassembling
`libRTPrinterSDK.a` arm64), so it's not a wrong-byte problem —
the NV-flag-suppresses-the-actuator behaviour is at firmware
level.

The setting is flipped via the vendor's Windows config utility
(Rongta calls it the "Thermal Receipt Printer Tool"), which writes
the flag to NV via a **proprietary** command sequence. Crucially,
that sequence is **not in any of the vendor's mobile SDKs** — the
iOS SDK declares `-[ESCCmd GetCommonSetCmd:]` in its header but
its implementation is an 8-byte stub that returns nil
(disassembly: `mov x0, #0; ret`). See
`vendor-mobile-sdks-may-stub-nv-config.md` for the broader
pattern.

One-time setup: run the Windows tool against the printer once
(via USB or Ethernet), enable Cutter / Beeper, save. The NV
setting persists across power cycles, and the Pi-side renderer
keeps working unchanged afterwards. If you can't easily reach a
Windows box, the only Linux-side derivation route is Wine +
`usbmon` to capture the tool's writes — viable but a separate
multi-step project.

Other settings in this category vary by model: code page default,
print density, paper-end behaviour, buzzer enable, language pack.
None of them are practical to set from Linux without
reverse-engineering the vendor's wire protocol; the one-time
Windows-tool dance is the pragmatic path.

## When to NOT skip CUPS

- **Multi-user desktops** where ordinary GUI apps print to the
  receipt printer from their print dialogs — you want CUPS as the
  system print layer.
- **Mixed printer fleet** where the same code prints to both
  receipt printers and regular page printers — CUPS abstracts.
- **Authenticated / accounted printing** with per-user quotas —
  again, CUPS layer.

For headless single-purpose use ("a Pi prints to a receipt printer
for a personal project") the direct-bytes path is more reliable,
faster to bring up, and easier to maintain.

## See also

- `` — canonical companion implementation
  (CLI + library + udev rule + deploy script + README).
- `udev-settle-after-trigger-or-rebind.md` — the sibling lesson on
  the udev-async footgun that bit during the udev-rule install
  step of this same project.
- The Epson ESC/POS reference is the authoritative command list,
  since most clone firmwares implement a subset:
  https://reference.epson-biz.com/modules/ref_escpos/
