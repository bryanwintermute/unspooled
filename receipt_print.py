#!/usr/bin/env python3
"""Stdlib-only ESC/POS renderer for 80mm and 58mm thermal receipt printers.

Designed to be:
- usable as a CLI: `python3 receipt_print.py --title 'Costco' < items.txt`
- importable as a library: `from receipt_print import Receipt`

The emitted byte stream is standard Epson ESC/POS (init, code-page-CP437,
align, font size, bold, full-cut) and should work on any ESC/POS-compatible
thermal receipt printer — Rongta RP332, Epson TM-T88, Star TSP100, Bixolon
SRP-330, Xprinter XP-58 family, and so on. The CLI defaults to writing to
`/dev/usb/lp0` (the kernel's generic `usblp` character device); pass
`--device` for any other path, or pipe the bytes anywhere via `--dry-run`.

For Rongta RP332 specifically, install the udev rule shipped alongside this
module (`99-rongta-receipt.rules`) and use `--device /dev/rongta-receipt`.
For other printers, your distro / udev rule conventions apply.

Width / column constants:
- 80mm head + Font A (12x24)  → 42 columns
- 80mm head + Font B (9x17)   → 56 columns
- 58mm head + Font A          → 32 columns
- 58mm head + Font B          → 42 columns
The renderer defaults to 42-col / 80mm Font A. Pass `print_width=` to
`Receipt()` for 58mm or other widths.

References for the command set used here:
  https://escpos.readthedocs.io/en/latest/  (community spec)
  Epson TM-T88 programming reference
"""

from __future__ import annotations

import argparse
import sys
import textwrap
import time
from dataclasses import dataclass, field
from typing import Iterable

# Generic kernel-bound usblp char device. The Rongta-specific symlink
# `/dev/rongta-receipt` (from the bundled udev rule) is equivalent on
# Bryan's rig but isn't required — change `--device` for any other path.
DEFAULT_DEVICE = "/dev/usb/lp0"

# Default print width: 80mm head, Font A (12x24 dots). Override per-Receipt
# via the print_width= keyword for 58mm heads (=32), Font B (=56), etc.
DEFAULT_PRINT_WIDTH = 42

ESC = b"\x1b"
GS = b"\x1d"
LF = b"\x0a"

INIT = ESC + b"@"
CODEPAGE_CP437 = ESC + b"t" + b"\x00"
ALIGN_LEFT = ESC + b"a" + b"\x00"
ALIGN_CENTER = ESC + b"a" + b"\x01"
ALIGN_RIGHT = ESC + b"a" + b"\x02"
FONT_DOUBLE = ESC + b"!" + b"\x30"
FONT_NORMAL = ESC + b"!" + b"\x00"
BOLD_ON = ESC + b"E" + b"\x01"
BOLD_OFF = ESC + b"E" + b"\x00"
CUT_FULL = GS + b"V" + b"\x00"
CUT_PARTIAL = GS + b"V" + b"\x01"


STYLES = {
    # rendered_prefix, continuation_indent
    "checkbox": ("[ ] ", "    "),
    "numbered": (None, "    "),  # numbering is computed dynamically
    "bullet":   ("- ",   "  "),
    "plain":    ("",     ""),
}


def _encode(s: str) -> bytes:
    """Encode to CP437 with safe fallback for unsupported chars."""
    return s.encode("cp437", errors="replace")


@dataclass
class Receipt:
    """A renderable receipt. Build with .add_*() then .to_bytes().

    print_width is the column count for textwrap + horizontal-rule
    rendering. Defaults to 42 (80mm head, Font A). Use 32 for 58mm,
    56 for 80mm Font B, etc. The renderer does NOT switch the printer's
    font for you; if you want Font B output you need to set the NV
    default-font (see ../unspooled rongta_config base --font b) AND
    pass print_width=56.
    """

    title: str | None = None
    timestamp: bool = True
    items: list[str] = field(default_factory=list)
    style: str = "checkbox"
    cut: bool = True
    print_width: int = DEFAULT_PRINT_WIDTH

    def add_item(self, text: str) -> None:
        self.items.append(text)

    def add_items(self, items: Iterable[str]) -> None:
        for it in items:
            text = it.strip()
            if text:
                self.items.append(text)

    def _render_item(self, idx: int, text: str) -> bytes:
        if self.style == "numbered":
            prefix = f"{idx + 1}. "
            cont_indent = " " * len(prefix)
        else:
            prefix, cont_indent = STYLES[self.style]

        wrapped = textwrap.fill(
            text,
            width=self.print_width,
            initial_indent=prefix,
            subsequent_indent=cont_indent,
            break_long_words=True,
            break_on_hyphens=False,
        )
        return _encode(wrapped + "\n")

    def to_bytes(self) -> bytes:
        out = bytearray()
        out += INIT + CODEPAGE_CP437

        if self.title:
            out += ALIGN_CENTER + FONT_DOUBLE + BOLD_ON
            out += _encode(self.title.upper()) + b"\n"
            out += BOLD_OFF + FONT_NORMAL + ALIGN_LEFT

        if self.timestamp:
            ts = time.strftime("%Y-%m-%d  %H:%M")
            out += ALIGN_CENTER + _encode(ts) + b"\n" + ALIGN_LEFT

        if self.title or self.timestamp:
            out += _encode("-" * self.print_width) + b"\n"

        for i, item in enumerate(self.items):
            out += self._render_item(i, item)

        if self.items:
            out += _encode("-" * self.print_width) + b"\n"

        # Advance paper above the tear/cutter bar (~12mm) then cut.
        out += LF * 5
        if self.cut:
            out += CUT_FULL

        return bytes(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Render a list to a thermal receipt printer as Epson ESC/POS. "
            "Works on any ESC/POS-compatible printer; defaults assume 80mm "
            "head + Font A. Pass --print-width 32 for 58mm."
        ),
    )
    p.add_argument(
        "file",
        nargs="?",
        default="-",
        help="File with one item per line (default: stdin).",
    )
    p.add_argument("--title", help="Optional title printed at the top.")
    p.add_argument(
        "--style",
        choices=sorted(STYLES),
        default="checkbox",
        help="List item style (default: checkbox).",
    )
    p.add_argument(
        "--device",
        default=DEFAULT_DEVICE,
        help=f"Printer device (default: {DEFAULT_DEVICE}).",
    )
    p.add_argument(
        "--print-width",
        type=int,
        default=DEFAULT_PRINT_WIDTH,
        help=(
            f"Column count for text wrap + horizontal rules "
            f"(default: {DEFAULT_PRINT_WIDTH} = 80mm Font A; "
            "use 32 for 58mm)."
        ),
    )
    p.add_argument("--no-timestamp", action="store_true", help="Suppress timestamp line.")
    p.add_argument("--no-cut", action="store_true", help="Skip the auto-cut at the end.")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Write rendered bytes to stdout instead of the printer.",
    )
    args = p.parse_args(argv)

    if args.file == "-":
        lines = sys.stdin.readlines()
    else:
        with open(args.file, encoding="utf-8") as f:
            lines = f.readlines()

    receipt = Receipt(
        title=args.title,
        timestamp=not args.no_timestamp,
        style=args.style,
        cut=not args.no_cut,
        print_width=args.print_width,
    )
    receipt.add_items(lines)

    payload = receipt.to_bytes()

    if args.dry_run:
        sys.stdout.buffer.write(payload)
        return 0

    try:
        with open(args.device, "wb") as f:
            f.write(payload)
    except PermissionError:
        print(
            f"error: cannot write to {args.device} (not in 'plugdev' group?).",
            file=sys.stderr,
        )
        return 2
    except FileNotFoundError:
        print(
            f"error: {args.device} not present. Is the printer plugged in?",
            file=sys.stderr,
        )
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
