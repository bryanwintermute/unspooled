# Rongta RP332 vendor-tool replacement — project recap

This is the "how to pick this back up" recap for the Rongta RP332
RE project (May 2026). Pair-read with
[`wine-cups-backend-recovers-nv-bytes.md`](./wine-cups-backend-recovers-nv-bytes.md),
which has the deeper technical patterns; this file just maps where
the artifacts live, what's still hot on <dev-host>, and what's left.

## What was built

Started: Saturday evening 2026-05-23 as "I want a to-do-list
printer on the Pi". Ended: Monday morning 2026-05-27 with a
seven-script Python CLI that fully replaces the proprietary
Windows-only Rongta config tool.

All artifacts live in [``](../../):

| File | Role |
|---|---|
| `rongta_config.py` | Unified entry point — dispatches to all areas. Recommended for daily use. |
| `nv_config.py` | Base tab: cutter, buzzer, drawer, font, code page (43 entries), baud, parity, auto-reprint, buzzer-after-print. |
| `ethernet_config.py` | Ethernet tab: DHCP, static IP, submask, gateway, MAC, duplex. |
| `papersave_config.py` | PaperSave tab: whitespace trimming (uses standard Epson `GS ( E`). |
| `blackmark_config.py` | BlackMark tab: mark-sensor config (mixed vendor + Epson `GS ( F`). |
| `other1_config.py` | Other1 tab: paper width, volume, alarm, USB mode, Chinese mode, cutter query. |
| `receipt_print.py` | Original list-to-paper renderer (predates the RE work). |

## Command families catalogued

```
1f 73 XX <args>                 Rongta vendor — Base config (+ sub-fns 0x72 0x74)
1f 69, 1f 25, 1f 4e, 1f 6d,     Rongta vendor — Ethernet family
1f 70, 1f 62 44
1f 1b 1f XX <args>              Rongta vendor extended — BlackMark + Other1
1f 7b X <arg>                   Rongta vendor mode toggles (ASCII-coded:
                                 'p'=paper sensor, 'u'=USB mode)
1d 28 45 ...                    STANDARD Epson GS ( E user-mode
                                 (PaperSave + Other1 Volume)
1d 28 46 ...                    STANDARD Epson GS ( F black-mark fns
                                 (BlackMark print/cut-after offsets)
1d 56 00                        STANDARD Epson GS V 0 (full-cut, runtime)
12 54                           STANDARD Epson DC2 'T' (self-test trigger)
1b 1b 45 ... 0c 5a              Rongta vendor "structured" packet
                                 (the Reset button — broken on this firmware)
```

Roughly half of what the vendor tool emits is **standard Epson
ESC/POS** — documented in the public Epson TM-T88 / TM-T20 spec.
The other half is Rongta-vendor extensions with no public docs.
Both halves yielded cleanly to the
[Wine + logging-CUPS-backend recovery technique](./wine-cups-backend-recovers-nv-bytes.md).

## State of the rig (the canonical layout to reproduce)

The reverse-engineering rig has two hosts. The values below are
placeholders; substitute your own.

| Role | Placeholder | Notes |
|---|---|---|
| Where the printer is plugged in | `<printer-host>` at `192.0.2.20` | Often a Pi (ARMv7+) that already has the printer attached via USB. Linux. |
| Where Wine runs | `<dev-host>` at `192.0.2.10` | x86_64 Linux. Wine isn't fun on ARM, so this is a separate host. |

(These IPs are TEST-NET-1, IANA-reserved for documentation. Replace
with your real LAN values.)

On `<dev-host>`, leave the following running between sessions:

- **Xvfb :99** + **x11vnc on 0.0.0.0:5900** — VNC client connects
  to `<dev-host>:5900` (no password by default; set one with
  `x11vnc -storepasswd`).
- **Wine prefix** at `~/wineprefix-rongta` (32-bit, `WINEARCH=win32`).
- **PrinterTool.exe v2.63.0** in `~/wineprefix-rongta/drive_c/Rongta/`.
  Restart with `cd ~/wineprefix-rongta/drive_c/Rongta && DISPLAY=:99 wine ./RongtaPrinterTool.exe &`.
- **Custom CUPS backend** at `/usr/lib/cups/backend/rongta` (mode
  0700 — required so it runs as root, can write to `/dev/usb/lp0`).
  Logs every spool to `/tmp/rongta-writes/<nanosecond>.bin`.
- **`rongta-raw` CUPS queue** with device URI `rongta:/dev/rongta-receipt`.
- **udev rule** `/etc/udev/rules.d/99-rongta-receipt.rules` (same as
  the canonical copy in [`99-rongta-receipt.rules`](../99-rongta-receipt.rules)).
- **usbipd on `<printer-host>`** with the printer bound (the busid
  is whatever `usbip list -l` shows on the printer-host side, e.g.
  `1-1.3`).
- **usbip attach on `<dev-host>`** — printer enumerates on a virtual
  USB bus as `/dev/usb/lp0` (and is symlinked to
  `/dev/rongta-receipt`).
- **`/tmp/rongta-wine/`** — original vendor tool zip + unpacked
  binaries.
- **Capture archives:** `/tmp/rongta-writes-archive/` for past
  captures, `/tmp/rongta-writes/` for live ones.
- **PE-tools venv** at `/tmp/petool-venv/` with `pefile` + `capstone`
  bootstrapped via PEP-668 workaround (venv `--without-pip` +
  `get-pip.py`).

### Re-attach recipe (if usbip drops)

usbip attachments do NOT survive printer power-cycles. When the
printer reboots:

```bash
# on <printer-host>
sudo usbip bind -b <busid>            # e.g. 1-1.3

# on <dev-host>
sudo usbip attach -r <printer-host>   # IP or hostname
                  -b <busid>
```

If `/dev/rongta-receipt` is left behind as a stale **regular file**
(see footgun in
[`wine-cups-backend-recovers-nv-bytes.md`](./wine-cups-backend-recovers-nv-bytes.md)):

```bash
sudo rm /dev/rongta-receipt
sudo udevadm trigger --action=change /sys/class/usbmisc/lp0
sudo udevadm settle
ls -la /dev/rongta-receipt  # should be lrwxrwxrwx → usb/lp0
```

## Wishlist (nice-to-haves)

In rough effort order — none of these are blocking. The CLI shipped
today covers every setting that practically matters.

1. **Bluetooth setting tab** — RP332 has no BT hardware, but the
   tab might emit no-op commands or preview a different family
   for other Rongta SKUs. Curious-only.
2. **Search Printer tab** — UDP-broadcast discovery protocol.
   Useful if you ever want a Rongta-tool-compatible discovery
   client in Python.
3. **Capture the cutter-stats response.** The
   `1f 1b 1f 19 00 02` query command is exposed as
   `rongta_config.py other1 cutter-query`, but the response only
   comes back on the printer's BULK-IN endpoint. The CUPS backend
   doesn't relay BULK-IN reads. To actually parse the response,
   capture with usbmon during a query, decode the format, expose
   a `cutter-info` subcommand that prints `N cuts, M.MM meters`.
4. **Empirically verify Voiceless volume.** Currently inferred as
   `0x01` (gap-filling the 02/03/04 pattern observed for
   Softly/Moderate/Loud). One click confirms.
5. **Set vs Set2 semantic difference** (Ethernet tab). Both
   produce the same end state per firmware-echo prints. Maybe
   Set persists-on-reboot and Set2 applies-immediately, or vice
   versa. Hard to test without power-cycling the printer between
   writes.
6. **Find a working factory-reset command.** The GUI's Reset
   emits `1b 1b 45 02 01 02 06 00 00 00 00 0c 5a` and firmware
   responds with "Setting Fail!" — no state change. Trailing
   `0c 5a` smells like a checksum trailer. Figure out the
   algorithm, try variants. (Meanwhile, `nv_config.py` writing
   factory defaults is a de-facto reset.)
7. **Decode the mystery middle "Set"** on BlackMark tab — emits
   `1f 1b 1f 83 04 05 06 01`. Trying other trailing bytes (00, 02,
   FF) might reveal its semantics.
8. **Pi-side end-to-end smoke test.** Bytes are verified to match
   Wine captures via `--dry-run`, but the per-CLI scripts haven't
   been run directly on <printer-host> (always via usbip from <dev-host>).
   They should work identically since the device path is the same,
   but a 5-minute sanity check is owed.
9. **`print-receipt` wrapper on <dev-host>** — pipe shopping lists
   from the laptop → ssh → <printer-host> → `/dev/rongta-receipt`.
   Deferred from the earliest sessions.
10. **HTTP / web-share portal** — "send to printer from phone".
    Also deferred from the earliest sessions. The original
    `receipt_print.py` was designed to be importable for this.

## Cleanup checklist (when you're done with the rig)

```bash
# <dev-host>
for pid in $(pgrep -f 'x11vnc|RongtaPrinterTool|wineserver|Xvfb :99'); do
  kill "$pid"
done
sudo usbip detach -p 0
# Optional: remove the wineprefix (~50MB) if not keeping for future tabs.
# rm -rf ~/wineprefix-rongta

# <printer-host>
sudo usbip unbind -b 1-1.3
# usbipd can keep running. Or:
# sudo systemctl stop usbipd  (if you ever wrap it in a unit)

# Optional: archive the captures somewhere durable before /tmp clears.
# tar czf ~/rongta-re-captures.tar.gz /tmp/rongta-writes-*
```

The `rongta-raw` CUPS queue + the custom `/usr/lib/cups/backend/rongta`
+ the udev rule on <dev-host> are all harmless when the printer
isn't attached. Leave them in place if you might revisit.

## Project numbers

- **7 Python CLIs**, all stdlib-only (~1500 LOC total).
- **~16 KB README** with byte-map tables for every command family.
- **9 commits** on `main` for this slice
  (`ad92ad7` → `2000c10`).
- **7 distinct RE patterns** captured in
  [`wine-cups-backend-recovers-nv-bytes.md`](./wine-cups-backend-recovers-nv-bytes.md).
- **Zero third-party dependencies** in shipped code. Vendor binaries
  (`PrinterTool.exe`, `ToolUseDll.dll`) used only during RE; not
  committed to the repo.

## See also

- [`wine-cups-backend-recovers-nv-bytes.md`](./wine-cups-backend-recovers-nv-bytes.md) —
  the technical lesson with all 7 RE patterns + footguns.
- [`vendor-mobile-sdks-may-stub-nv-config.md`](./vendor-mobile-sdks-may-stub-nv-config.md) —
  what we did BEFORE Wine: disassembled Rongta's iOS/Android SDKs,
  proved the NV-config methods were stubs, concluded the Windows
  tool was the only viable path.
- [`escpos-thermal-printers-need-no-cups-driver.md`](./escpos-thermal-printers-need-no-cups-driver.md) —
  the parent lesson: ESC/POS printers don't need CUPS for the
  basic print path. (CUPS only re-entered the picture here as a
  RE harness, not as a print path.)
- [`udev-settle-after-trigger-or-rebind.md`](./udev-settle-after-trigger-or-rebind.md) —
  the trigger/settle discipline used in the re-attach recipe.
- [``](../../) — the
  actual deliverable.
