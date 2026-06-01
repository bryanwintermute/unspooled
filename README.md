# unspooled

> A Linux CLI for the Rongta RP332 thermal receipt printer.
> The protocol was undocumented, the config tool was Windows-only,
> and the vendor mobile SDKs ship the relevant methods as
> `mov x0, #0; ret` stubs. So we routed `PrinterTool.exe`'s output
> through Wine and a custom logging CUPS backend, captured every byte
> it emits, and re-implemented all of it in **seven Python scripts,
> stdlib only, zero third-party dependencies**.

`unspooled` is two things in one repo:

1. **A generic stdlib ESC/POS renderer** (`receipt_print.py`) — works
   on any ESC/POS-compatible 80mm or 58mm thermal receipt printer
   (Rongta, Epson, Star, Bixolon, Xprinter, …). Use as a CLI or
   import as a library:
   ```python
   from receipt_print import Receipt
   r = Receipt(title="Costco", style="checkbox", print_width=42)
   r.add_items(["milk", "eggs", "bread"])
   open("/dev/usb/lp0", "wb").write(r.to_bytes())
   ```
2. **A Rongta RP332 NV-config CLI** (`nv_config.py`, `ethernet_config.py`,
   `papersave_config.py`, `blackmark_config.py`, `other1_config.py`,
   all dispatched through `rongta_config.py`) — flips the persistent
   factory defaults (auto-cutter, buzzer, drawer kick, paper width,
   DHCP, static IP, MAC, 43 code pages, black-mark sensor, paper-save
   trimming, …) without needing the proprietary Windows tool.

The renderer is **brand-agnostic** by design and is the bit you want
if you're building anything that prints to a thermal receipt
printer. The Rongta CLIs are **brand-specific** by necessity — the
NV-config wire protocol is proprietary to Rongta. Use whichever half
applies.

## Why "unspooled"?

The vendor tool talks to the printer through the Windows print
spooler. We routed that spool through a logging CUPS backend on
Linux (the printer presented to Wine as a CUPS printer) and
captured every byte. The project is the printer literally being
"unspooled" out of the vendor pipeline — and the protocol itself
being unspooled into something documented.

## Hardware

- **Renderer (`receipt_print.py`):** Any ESC/POS-compatible thermal
  receipt printer (80mm or 58mm head). No vendor lock-in.
- **NV-config CLIs (`rongta_config.py` et al.):** Rongta RP332,
  USB id `0fe6:811e` (the printer presents as an "ICS Advent
  Parallel Adapter" — Rongta licenses the USB-to-parallel chip).
  **Likely** also works on other Rongta SKUs that share the
  `PrinterTool.exe` config tool (RP325, RP326, RP328, etc.) but
  **untested** — PRs welcome.

> ### ❤️ Help wanted
>
> The RP332 has no WiFi or Bluetooth hardware, so PrinterTool.exe's
> WiFi tab and Bluetooth-setting tab were never reverse-engineered.
> If you have a Rongta SKU with WiFi or BT and are willing to repeat
> the technique on it, [open a "Help wanted" issue](https://github.com/bryanwintermute/unspooled/issues/new?template=wifi-bt-help-wanted.yml).
> Same goes for the UDP-discovery protocol behind the "Search
> Printer" tab. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Requirements

- Python 3.9+ — **stdlib only, no third-party packages.** That's
  the whole runtime dependency footprint.
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

## ⚠️ Safety — read this before writing anything

Most commands in this CLI write to the printer's **NV-RAM**. The
writes are **persistent across power cycles** — there is no
"undo" beyond writing the previous value back. Wrong values can
leave the printer in a state where the only recovery path is
this CLI itself (which is also the project's de-facto factory-reset).

Three concrete failure modes worth knowing before you flip
anything:

1. **`rongta_config.py other1 usb-mode virtual-serial`** —
   makes the printer re-enumerate as `/dev/ttyACM*` instead of
   `/dev/usb/lp0`. The udev rule in this repo won't fire for
   `ttyACM` devices, so `/dev/rongta-receipt` will not exist.
   You'll need a different recovery path. Don't run this casually.
2. **`rongta_config.py ethernet mac <bad-mac>`** — if you change
   the MAC and forget the original, you can't read it back over
   USB (the firmware echoes confirmations, but only of the value
   you sent). Always note the existing MAC from the
   power-on-self-test report before changing it.
3. **`rongta_config.py ethernet static --ip <bad-ip>`** — wrong
   static IP / gateway / subnet can isolate the printer on its
   own Ethernet but it's harmless if you're driving over USB.

**Always use `--dry-run` first.** Every command supports it.
Print the bytes, eyeball them, then drop the flag.

```bash
./rongta_config.py base --cutter on --buzzer on --dry-run
# 1f 73 02 00 00 01 00 00 00 00 00 1f 72 00 1f 74 00
```

If you do botch a setting, re-run with the desired values. The
CLI is its own factory-reset.

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
| `base` | `nv_config.py` | Cutter, buzzer, drawer kick, font, density, char/line, code page (43 named entries, sourced from the printer's own self-test report; 5 reserved slots accessible via `--code-page-raw`), baud rate, parity, auto-reprint, buzzer-after-print. |
| `ethernet` | `ethernet_config.py` | DHCP, static IP, submask, gateway, MAC address, link mode. |
| `papersave` | `papersave_config.py` | Whitespace trimming (uses standard Epson `GS ( E`). |
| `blackmark` | `blackmark_config.py` | Black-mark sensor: enable/disable, length, width, print/cut offset. |
| `other1` | `other1_config.py` | Paper width (80mm/58mm), buzzer volume, alarm, USB enumeration mode, Chinese character mode, cutter-count query. |
| `print` | `receipt_print.py` | Render a list (with `--title`, `--style`, `--print-width`) as standard Epson ESC/POS. Brand-agnostic. |

## Use as a library (`receipt_print.py`)

`receipt_print.py` is intentionally importable from downstream
projects (e.g. [`tickertape`](https://github.com/bryanwintermute/tickertape))
without dragging in any of the Rongta-specific modules. It's
stdlib-only, brand-agnostic, and the entire byte-emitting surface
is standard Epson ESC/POS (init, code-page CP437, align, font size,
bold, full-cut).

```python
from receipt_print import Receipt

# 80mm head, Font A (the default — 42 columns).
r = Receipt(title="Costco", style="checkbox")
r.add_items(["milk", "eggs", "bread"])
with open("/dev/usb/lp0", "wb") as f:
    f.write(r.to_bytes())

# 58mm head — pass print_width=32.
r58 = Receipt(title="Reminders", style="bullet", print_width=32)
r58.add_items(["pick up package", "water plants"])
```

Constructor signature:

```python
Receipt(
    title: str | None = None,        # optional bold/centered/upper-cased title
    timestamp: bool = True,          # adds a YYYY-MM-DD HH:MM line under the title
    items: list[str] = [],           # or use .add_item() / .add_items()
    style: str = "checkbox",         # 'checkbox' / 'numbered' / 'bullet' / 'plain'
    cut: bool = True,                # GS V 0 full-cut at the end
    print_width: int = 42,           # 42=80mm Font A, 32=58mm Font A, 56=80mm Font B
)
```

The `Receipt.to_bytes()` method is deterministic given the same
inputs (timestamp aside) and the byte format is locked by the test
suite in `tests/test_receipt_print_library.py`.

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

Full technique in
[`docs/wine-cups-backend-recovers-nv-bytes.md`](docs/wine-cups-backend-recovers-nv-bytes.md).
Short version:

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

A concrete example — the Base tab's "Set" command with four
isolated states (all-off, only-cutter, only-drawer, only-buzzer)
produces these four 17-byte files. Aligning them column-wise:

```text
                                  ┌─cutter
                                  │  ┌─buzzer
                                  │  │  ┌─drawer
all-off       :  1f 73 02 |  01  01  01  | 00 00 00 00 00 | 1f 72 00 | 1f 74 00
cutter-only   :  1f 73 02 |  00  01  01  | 00 00 00 00 00 | 1f 72 00 | 1f 74 00
drawer-only   :  1f 73 02 |  01  01  00  | 00 00 00 00 00 | 1f 72 00 | 1f 74 00
buzzer-only   :  1f 73 02 |  01  00  01  | 00 00 00 00 00 | 1f 72 00 | 1f 74 00
                          └────────────┘
                          three settings,
                          inverted booleans
                          (0 = on, 1 = off)
```

Position 3 only changes when Cutter is toggled, position 4 only
when Buzzer, position 5 only when Drawer. The encoding is
inverted (0 = on, 1 = off) because the factory firmware is shipped
with everything off and "0" means "default no-add-ons". Four
clicks → complete bit-mapping in 30 seconds of diffing.

For big enum dropdowns (like code pages), there's an even
cheaper trick: **static-analyse the PE binary**. MFC dropdown
labels are stored as contiguous string literals in the binary's
`.rdata` section. MSVC emits them **bottom-up** (reverse source
order), so:

```bash
strings -el -t d PrinterTool.exe | grep -E '^(CP|WCP|ISO|Katakana)' | sort -rn
```

…gives you the dropdown labels in their *visual* order.
**Important:** dropdown order is NOT the same as wire-byte order.
The RP332's first 6 code-page entries (CP437, Katakana,
CP850/860/863/865) happen to be wire bytes 0-5 because the
most-common pages are listed first AND happen to have the lowest
enum values — but past that, the dropdown order diverges.

**The truly cheap source of truth turned out to be the printer's
own self-test report**: the RP332's power-on diagnostic prints
its full 48-entry code-page table verbatim. We just hadn't read
all the way to the bottom of the receipt. Always read every
diagnostic output the device exposes before reaching for static
analysis. Full debrief in
[`docs/wine-cups-backend-recovers-nv-bytes.md`](docs/wine-cups-backend-recovers-nv-bytes.md).

## More reading

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

## Contributing

PRs welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the
quick path to adding a new Rongta SKU (or extending the protocol
catalogue with bytes we haven't captured).
