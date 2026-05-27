#!/usr/bin/env python3
"""Configure Paper Save settings on the Rongta RP332 receipt printer.

Reverse-engineered from PrinterTool.exe v2.63.0's PaperSave tab via Wine
+ logging-CUPS-backend technique. Unlike the Base/Ethernet tabs, the
PaperSave tab uses **standard ESC/POS user-setting-mode commands**, not
Rongta-vendor commands:

    GS ( E <pL><pH> <fn>  <data...>           # 1d 28 45 ...

The PaperSave tab's "Set" emits two consecutive `GS ( E` commands:

  1. `1d 28 45 10 00 05 <e> 00 00 <f> 00 00 <g> 00 00 <h> 00 00 <i> 00 00`
     `GS ( E pL=0x10 pH=0x00 fn=5` = "set user-setting values"
     Five 3-byte sub-records, addressed by single-byte code:
        e  (0x65) = Delete Empty Space At The Top   0=disable, 1=enable
        f  (0x66) = Delete Empty Space In The middle 0=disable, 1=enable
        g  (0x67) = Cut Rate of Line Interval        0=None,1=25%,2=50%,3=75%
        h  (0x68) = Cut Rate of Change Line          (same encoding)
        i  (0x69) = Cut Rate of bar-code's Height    (same encoding)

  2. `1d 28 45 04 00 02 4f 55 54`
     `GS ( E pL=4 pH=0 fn=2` = "OUT" sentinel — exit user-setting mode
     and commit. ASCII "OUT" is literally 0x4F 0x55 0x54.

Both Delete-Empty-Space settings appear to control auto-trim of
whitespace before/within content. The three Cut Rates are aggressive
trimming options for receipts containing line spacing / line changes /
barcodes — the Custom preview on the right side of the tab shows what
the output would look like with the active settings.

Default state (factory): all settings off / 0.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_DEVICE = "/dev/rongta-receipt"

CUT_RATES = {"none": 0, "25%": 1, "50%": 2, "75%": 3}


def _bool(name: str, value: str) -> int:
    if value == "enable" or value == "on":
        return 1
    if value == "disable" or value == "off":
        return 0
    raise ValueError(f"{name}: expected 'enable' or 'disable', got {value!r}")


def build_papersave(
    *,
    delete_top: str = "disable",
    delete_middle: str = "disable",
    cut_rate_line_interval: str = "none",
    cut_rate_change_line: str = "none",
    cut_rate_barcode_height: str = "none",
) -> bytes:
    e = _bool("delete_top", delete_top)
    f = _bool("delete_middle", delete_middle)
    g = CUT_RATES[cut_rate_line_interval]
    h = CUT_RATES[cut_rate_change_line]
    i = CUT_RATES[cut_rate_barcode_height]

    cmd1 = bytes([
        0x1D, 0x28, 0x45,    # GS ( E
        0x10, 0x00,          # pL pH = 16 bytes follow
        0x05,                # fn = 5 (set user-setting values)
        0x65, e, 0x00,       # 'e'
        0x66, f, 0x00,       # 'f'
        0x67, g, 0x00,       # 'g'
        0x68, h, 0x00,       # 'h'
        0x69, i, 0x00,       # 'i'
    ])
    cmd2 = bytes([
        0x1D, 0x28, 0x45,    # GS ( E
        0x04, 0x00,          # pL pH = 4 bytes follow
        0x02,                # fn = 2 (exit user-setting mode, commit)
        0x4F, 0x55, 0x54,    # ASCII "OUT"
    ])
    return cmd1 + cmd2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument(
        "--delete-top",
        choices=["enable", "disable"],
        default="disable",
        help="Delete empty space at the top of pages (e=0x65).",
    )
    p.add_argument(
        "--delete-middle",
        choices=["enable", "disable"],
        default="disable",
        help="Delete empty space within content (f=0x66).",
    )
    p.add_argument(
        "--cut-line-interval",
        choices=list(CUT_RATES),
        default="none",
        help="Cut rate for line-interval spacing (g=0x67).",
    )
    p.add_argument(
        "--cut-change-line",
        choices=list(CUT_RATES),
        default="none",
        help="Cut rate for line-change spacing (h=0x68).",
    )
    p.add_argument(
        "--cut-barcode-height",
        choices=list(CUT_RATES),
        default="none",
        help="Cut rate for barcode height (i=0x69).",
    )
    p.add_argument(
        "--device",
        default=DEFAULT_DEVICE,
        help=f"Printer device (default: {DEFAULT_DEVICE}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print bytes that would be written, don't actually write.",
    )

    args = p.parse_args(argv)

    data = build_papersave(
        delete_top=args.delete_top,
        delete_middle=args.delete_middle,
        cut_rate_line_interval=args.cut_line_interval,
        cut_rate_change_line=args.cut_change_line,
        cut_rate_barcode_height=args.cut_barcode_height,
    )

    if args.dry_run:
        print(data.hex(" "))
        return 0

    dev = Path(args.device)
    try:
        with dev.open("wb", buffering=0) as f:
            f.write(data)
    except PermissionError:
        print(
            f"error: cannot write to {dev} (not in 'plugdev' group?).",
            file=sys.stderr,
        )
        return 2
    except FileNotFoundError:
        print(
            f"error: {dev} not present. Is the printer plugged in?",
            file=sys.stderr,
        )
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
