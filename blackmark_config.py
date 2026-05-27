#!/usr/bin/env python3
"""Configure Black Mark sensing on the Rongta RP332 receipt printer.

The Black Mark sensor detects pre-printed registration marks on the
back of receipt paper (commonly used in ticket/label printing) and
synchronises cuts/feeds to those marks. The BlackMark tab in
PrinterTool.exe controls this; we've reverse-engineered all its
buttons via Wine + logging-CUPS-backend.

The tab mixes TWO command families:

  * Rongta-vendor `1f 1b 1f <op> 04 05 06 [args]` for:
      0x80 = Enable/Disable (arg byte: 'D' = enable, 'f' = disable)
      0x81 = Black Mark Length (arg: 2-byte big-endian, 1/8mm units)
      0x82 = Black Mark Width  (arg: 2-byte big-endian, 1/8mm units)
      0x83 = (unknown — middle "Set" button emits this; trailing byte 0x01)

  * Standard Epson ESC/POS `GS ( F` for:
      fn=1 = Print After Black Mark (arg: 2-byte big-endian, 1/8mm)
      fn=2 = Cut After Black Mark   (arg: 2-byte big-endian, 1/8mm)

The RP332 prints at 203 DPI = 8 dots/mm, so the 1/8mm encoding lines
up perfectly with the dot pitch.

The "Next Black Mark" and "Next Cut" buttons are NOT NV writes:
  * Next Black Mark = literal "HELLO WORLD!\\n\\x0c" — a test print
    ending in form-feed (advance to next mark). Useful as a sensor
    runtime check.
  * Next Cut = `1d 56 00` = standard GS V 0 full-cut. Same as our
    receipt_print.py uses.

So this CLI exposes the NV-write subcommands and skips the runtime ones.

WARNING: writing wrong Length/Width can leave the printer unable to
align prints to marks. Default factory values (Length=300mm,
Width=10mm) effectively disable mark-sensing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_DEVICE = "/dev/rongta-receipt"

# 1/8 mm per unit (RP332 prints at 203 DPI = 8 dots/mm).
DOTS_PER_MM = 8


def _be_u16(mm: int) -> bytes:
    """Encode a mm value as big-endian 16-bit in 1/8mm units."""
    units = mm * DOTS_PER_MM
    if not 0 <= units <= 0xFFFF:
        raise ValueError(f"mm value out of range: {mm} → {units} units")
    return bytes([(units >> 8) & 0xFF, units & 0xFF])


def build_enable(enable: bool) -> bytes:
    """Enable / disable black-mark mode."""
    return bytes([0x1F, 0x1B, 0x1F, 0x80, 0x04, 0x05, 0x06, 0x44 if enable else 0x66])


def build_set_length(mm: int) -> bytes:
    """Set expected black-mark length in mm (default factory: 300)."""
    return bytes([0x1F, 0x1B, 0x1F, 0x81, 0x04, 0x05, 0x06]) + _be_u16(mm)


def build_set_width(mm: int) -> bytes:
    """Set expected black-mark width in mm (default factory: 10)."""
    return bytes([0x1F, 0x1B, 0x1F, 0x82, 0x04, 0x05, 0x06]) + _be_u16(mm)


def build_set_print_after(mm: int) -> bytes:
    """Set 'print-after-black-mark' offset in mm via Epson GS ( F fn=1.

    Wire format: 1d 28 46 04 00 01 00 <hi> <lo>  (big-endian 1/8mm).
    """
    return bytes([0x1D, 0x28, 0x46, 0x04, 0x00, 0x01, 0x00]) + _be_u16(mm)


def build_set_cut_after(mm: int) -> bytes:
    """Set 'cut-after-black-mark' offset in mm via Epson GS ( F fn=2.

    Wire format: 1d 28 46 04 00 02 00 <hi> <lo>  (big-endian 1/8mm).
    """
    return bytes([0x1D, 0x28, 0x46, 0x04, 0x00, 0x02, 0x00]) + _be_u16(mm)

def build_mystery_set() -> bytes:
    """The middle 'Set' button on the BlackMark tab (purpose unknown).

    Emits `1f 1b 1f 83 04 05 06 01`. Possibly a 'commit black-mark
    settings to NV' or 'enable advanced mode'. Untested for behaviour.
    """
    return bytes([0x1F, 0x1B, 0x1F, 0x83, 0x04, 0x05, 0x06, 0x01])


def write_bytes(dev: Path, data: bytes) -> None:
    with dev.open("wb", buffering=0) as f:
        f.write(data)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_en = sub.add_parser("enable", help="Enable black-mark sensing.")
    sp_di = sub.add_parser("disable", help="Disable black-mark sensing.")

    sp_len = sub.add_parser("length", help="Set Black Mark Length in mm (default factory 300).")
    sp_len.add_argument("mm", type=int)

    sp_w = sub.add_parser("width", help="Set Black Mark Width in mm (default factory 10).")
    sp_w.add_argument("mm", type=int)

    sp_pa = sub.add_parser(
        "print-after",
        help="Set print-after-black-mark offset in mm (Epson GS ( F fn=1).",
    )
    sp_pa.add_argument("mm", type=int)

    sp_ca = sub.add_parser(
        "cut-after",
        help="Set cut-after-black-mark offset in mm (Epson GS ( F fn=2).",
    )
    sp_ca.add_argument("mm", type=int)

    sp_x = sub.add_parser(
        "mystery-set",
        help="The middle 'Set' button (unknown purpose; emits 1f 1b 1f 83 04 05 06 01).",
    )

    sp_raw = sub.add_parser("raw", help="Write arbitrary hex bytes.")
    sp_raw.add_argument("hex_bytes")

    for sp in (sp_en, sp_di, sp_len, sp_w, sp_pa, sp_ca, sp_x, sp_raw):
        sp.add_argument("--device", default=DEFAULT_DEVICE)
        sp.add_argument(
            "--dry-run",
            action="store_true",
            help="Print bytes that would be written, don't actually write.",
        )

    args = p.parse_args(argv)

    if args.cmd == "enable":
        data = build_enable(True)
    elif args.cmd == "disable":
        data = build_enable(False)
    elif args.cmd == "length":
        data = build_set_length(args.mm)
    elif args.cmd == "width":
        data = build_set_width(args.mm)
    elif args.cmd == "print-after":
        data = build_set_print_after(args.mm)
    elif args.cmd == "cut-after":
        data = build_set_cut_after(args.mm)
    elif args.cmd == "mystery-set":
        data = build_mystery_set()
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
