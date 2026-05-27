#!/usr/bin/env python3
"""Configure the Other1 tab on the Rongta RP332 receipt printer.

This tab is a grab-bag of miscellaneous settings — paper width, sensor
behaviour, beeper volume, USB mode, Chinese character mode, alarm
beep/light — each with its own dedicated Set button. Three command
families show up:

  1. Rongta-vendor `1f 1b 1f <op> ...` (same family as Base + BlackMark):
       0xfe  Chinese Character mode   (0=Enable, 1=Disable; inverted bool)
       0x19  Sound-and-light alarm    (sub-fn 0x02 = beep, 0x03 = light;
                                       value 0x01 = Open, 0x00 = Close)
                                      (sub-fn 0x00 = cutter-stats query)
       0xa4  80 Print Mode (paper width)   — see notes below

  2. New Rongta-vendor family `1f 7b <op> <arg>`:
       'p' (0x70) Run Out of Paper sensor  (0=Disable, 1=Enable)
       'u' (0x75) USB mode                 (0=Printer USB, 1=Virtual Serial)

  3. Standard Epson ESC/POS `GS ( E` fn=1:
       Volume Set (the GS ( E user-mode "set value" command).
       Wire: `1d 28 45 04 00 01 <v> 00`
       v: 0x01 = Voiceless, 0x02 = Softly, 0x03 = Moderate (default),
          0x04 = Loud.

80 Print Mode (paper width) is a 11-byte vendor command:
  `1f 1b 1f a4 01 02 03 11 12 13 <v>`
  v = 0x55 ('U') for 80mm, 0x33 ('3') for 58mm.
The literal 0x11 0x12 0x13 prefix looks like a structured magic header.
The trailing ASCII byte feels like a one-letter mnemonic.

WARNING: changing USB mode to 'Virtual Serial' will make the printer
re-enumerate as /dev/ttyACM* instead of /dev/usb/lp0; you'll lose the
udev rule's /dev/rongta-receipt symlink. Don't do this casually.

The Other1 tab also has a "Number of cutters and mileage" Query button
that emits `1f 1b 1f 19 00 02`. It's a READ command — the response
comes back on the printer's BULK-IN endpoint. We expose it here but
the response capture is left as an exercise (would need usbmon, since
CUPS backend doesn't relay BULK-IN reads back to the user).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_DEVICE = "/dev/rongta-receipt"

VOLUMES = {"voiceless": 0x01, "softly": 0x02, "moderate": 0x03, "loud": 0x04}
PRINT_WIDTHS = {"80mm": 0x55, "58mm": 0x33}


def build_chinese(enable: bool) -> bytes:
    return bytes([0x1F, 0x1B, 0x1F, 0xFE, 0x00 if enable else 0x01])


def build_alarm_beep(open_: bool) -> bytes:
    return bytes([0x1F, 0x1B, 0x1F, 0x19, 0x02, 0x01 if open_ else 0x00])


def build_alarm_light(open_: bool) -> bytes:
    return bytes([0x1F, 0x1B, 0x1F, 0x19, 0x03, 0x01 if open_ else 0x00])


def build_cutter_query() -> bytes:
    """Query cutter cycle count + mileage. Response comes back via BULK-IN."""
    return bytes([0x1F, 0x1B, 0x1F, 0x19, 0x00, 0x02])


def build_run_out_of_paper(enable: bool) -> bytes:
    return bytes([0x1F, 0x7B, 0x70, 0x01 if enable else 0x00])


def build_usb_mode(virtual_serial: bool) -> bytes:
    """USB enumeration mode.

    WARNING: setting virtual_serial=True will make the printer disappear
    from /dev/usb/lp0 and reappear as /dev/ttyACM*. The udev rule that
    pins /dev/rongta-receipt will NOT fire for ttyACM devices.
    """
    return bytes([0x1F, 0x7B, 0x75, 0x01 if virtual_serial else 0x00])


def build_print_width(width: str) -> bytes:
    """Set paper width to '80mm' or '58mm'."""
    v = PRINT_WIDTHS[width]
    return bytes([0x1F, 0x1B, 0x1F, 0xA4, 0x01, 0x02, 0x03, 0x11, 0x12, 0x13, v])


def build_volume(level: str) -> bytes:
    """Set buzzer volume via Epson GS ( E fn=1."""
    v = VOLUMES[level]
    return bytes([0x1D, 0x28, 0x45, 0x04, 0x00, 0x01, v, 0x00])


def write_bytes(dev: Path, data: bytes) -> None:
    with dev.open("wb", buffering=0) as f:
        f.write(data)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_ch = sub.add_parser("chinese", help="Enable / disable Chinese character mode.")
    sp_ch.add_argument("state", choices=["enable", "disable"])

    sp_ab = sub.add_parser("alarm-beep", help="Sound-and-light alarm beep open/close.")
    sp_ab.add_argument("state", choices=["open", "close"])

    sp_al = sub.add_parser("alarm-light", help="Sound-and-light alarm light open/close.")
    sp_al.add_argument("state", choices=["open", "close"])

    sub.add_parser(
        "cutter-query",
        help="Send cutter-stats query (response is read-only; needs usbmon to capture).",
    )

    sp_ro = sub.add_parser(
        "run-out-of-paper",
        help="Enable / disable run-out-of-paper sensor behaviour.",
    )
    sp_ro.add_argument("state", choices=["enable", "disable"])

    sp_usb = sub.add_parser(
        "usb-mode",
        help="USB enumeration mode (printer-class or virtual-serial).",
    )
    sp_usb.add_argument(
        "mode",
        choices=["printer", "virtual-serial"],
        help="'printer' = /dev/usb/lp0; 'virtual-serial' = /dev/ttyACM*.",
    )

    sp_pw = sub.add_parser(
        "print-width",
        help="Set paper width (80mm or 58mm).",
    )
    sp_pw.add_argument("width", choices=list(PRINT_WIDTHS))

    sp_vol = sub.add_parser(
        "volume",
        help="Set buzzer volume (Epson GS ( E fn=1).",
    )
    sp_vol.add_argument("level", choices=list(VOLUMES))

    sp_raw = sub.add_parser("raw", help="Write arbitrary hex bytes.")
    sp_raw.add_argument("hex_bytes")

    for sp in p._actions[-1].choices.values():
        sp.add_argument("--device", default=DEFAULT_DEVICE)
        sp.add_argument(
            "--dry-run",
            action="store_true",
            help="Print bytes that would be written, don't actually write.",
        )

    args = p.parse_args(argv)

    if args.cmd == "chinese":
        data = build_chinese(args.state == "enable")
    elif args.cmd == "alarm-beep":
        data = build_alarm_beep(args.state == "open")
    elif args.cmd == "alarm-light":
        data = build_alarm_light(args.state == "open")
    elif args.cmd == "cutter-query":
        data = build_cutter_query()
    elif args.cmd == "run-out-of-paper":
        data = build_run_out_of_paper(args.state == "enable")
    elif args.cmd == "usb-mode":
        data = build_usb_mode(args.mode == "virtual-serial")
    elif args.cmd == "print-width":
        data = build_print_width(args.width)
    elif args.cmd == "volume":
        data = build_volume(args.level)
    elif args.cmd == "raw":
        data = bytes.fromhex(args.hex_bytes.replace(" ", "").replace(":", ""))
    else:
        p.error("unknown subcommand")

    if args.dry_run:
        print(data.hex(" "))
        return 0

    dev = Path(args.device)
    try:
        write_bytes(dev, data)
    except PermissionError:
        print(f"error: cannot write to {dev} (not in 'plugdev' group?).", file=sys.stderr)
        return 2
    except FileNotFoundError:
        print(f"error: {dev} not present. Is the printer plugged in?", file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
