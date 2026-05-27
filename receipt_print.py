#!/usr/bin/env python3
"""Receipt-printer renderer + CLI for the Rongta RP332.

Stdlib-only ESC/POS renderer designed to be:
- usable as a CLI on the printer host: `receipt-print --title 'Costco' < items.txt`
- importable from a future HTTP service: `from receipt_print import Receipt`

The Rongta RP332 (USB id 0fe6:811e) is bound to /dev/usb/lp0 by the
generic usblp kernel driver and pinned to /dev/rongta-receipt by the
udev rule in ./99-rongta-receipt.rules. The printer accepts raw
ESC/POS byte streams; no CUPS, no vendor "driver", no Python deps.

References for the command set used here:
  https://escpos.readthedocs.io/en/latest/  (community spec)
  Epson TM-T88 programming reference (RP332 is ESC/POS-compatible)
"""

from __future__ import annotations

import argparse
import sys
import textwrap
import time
from dataclasses import dataclass, field
from typing import Iterable

DEFAULT_DEVICE = "/dev/rongta-receipt"

# Printable width at the standard (Font A, 12x24) font on an 80mm head.
# Font A is 42 cols. Font B (9x17) is 56 cols. We stick to Font A.
PRINT_COLS = 42

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
    """A renderable receipt. Build with .add_*() then .to_bytes()."""

    title: str | None = None
    timestamp: bool = True
    items: list[str] = field(default_factory=list)
    style: str = "checkbox"
    cut: bool = True

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
            width=PRINT_COLS,
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
            out += _encode("-" * PRINT_COLS) + b"\n"

        for i, item in enumerate(self.items):
            out += self._render_item(i, item)

        if self.items:
            out += _encode("-" * PRINT_COLS) + b"\n"

        # Advance paper above the tear/cutter bar (~12mm) then cut.
        out += LF * 5
        if self.cut:
            out += CUT_FULL

        return bytes(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Render a list to the Rongta RP332 thermal printer.",
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
