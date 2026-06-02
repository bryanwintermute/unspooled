#!/usr/bin/env python3
"""Unified CLI for configuring the Rongta RP332 receipt printer.

A single entry point that dispatches to the per-tab modules:

    rongta_config.py base       …   Base tab settings (cutter, buzzer, font, …)
    rongta_config.py ethernet   …   Ethernet tab (DHCP, IP, MAC, …)
    rongta_config.py papersave  …   PaperSave tab (whitespace trimming)
    rongta_config.py blackmark  …   BlackMark tab (mark-sensor config)
    rongta_config.py other1     …   Other1 tab (volume, alarm, paper width, …)
    rongta_config.py print      …   Print a list (the original receipt_print CLI)

Each `<area>` subcommand simply forwards its trailing arguments to the
corresponding module's main(). For full help on a specific area, run:

    rongta_config.py <area> --help

Example flows the modules cover (reverse-engineered without the
proprietary Windows tool — see README.md and
docs/wine-cups-backend-recovers-nv-bytes.md):

    # Out-of-the-box DHCP fix (most common reason to need this CLI).
    rongta_config.py ethernet dhcp on

    # Enable the auto-cutter (NV-gated; the canonical 'cutter only' state).
    rongta_config.py base --cutter on

    # Aggressive paper-saving for shopping-list-style receipts.
    rongta_config.py papersave --delete-top enable --cut-line-interval 75%

    # Print a shopping list.
    echo -e 'milk\\neggs\\nbread' | rongta_config.py print --title 'Costco'
"""
from __future__ import annotations

import argparse
import importlib
import sys
from typing import Callable

__version__ = "0.3.1"

# Each entry maps area name -> (module name, short help).
AREAS: dict[str, tuple[str, str]] = {
    "base": ("nv_config", "Base tab: cutter, buzzer, font, code page, baud, parity, …"),
    "ethernet": ("ethernet_config", "Ethernet tab: DHCP, static IP, MAC, duplex."),
    "papersave": ("papersave_config", "PaperSave tab: whitespace trimming."),
    "blackmark": ("blackmark_config", "BlackMark tab: mark-sensor config."),
    "other1": ("other1_config", "Other1 tab: paper width, volume, alarm, USB mode, …"),
    "print": ("receipt_print", "Print a list of items (the original receipt-print CLI)."),
}


def _load_main(module_name: str) -> Callable[[list[str] | None], int]:
    """Import the named sibling module and return its main() function."""
    # When this script lives in the repo root the sibling modules
    # are right next to it on sys.path.
    mod = importlib.import_module(module_name)
    if not hasattr(mod, "main"):
        raise RuntimeError(f"module {module_name} has no main()")
    return mod.main  # type: ignore[no-any-return]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # Custom top-level dispatch — argparse subparsers can't gracefully forward
    # arbitrary args to a child main(), so we do the slice ourselves.
    if not argv or argv[0] in ("-h", "--help"):
        _print_top_help()
        return 0
    if argv[0] in ("-V", "--version"):
        print(f"unspooled {__version__}")
        return 0
    area = argv[0]
    if area not in AREAS:
        print(f"error: unknown area {area!r}.", file=sys.stderr)
        _print_top_help(stream=sys.stderr)
        return 2

    module_name, _ = AREAS[area]
    try:
        sub_main = _load_main(module_name)
    except ImportError as e:
        print(f"error: could not import {module_name!r}: {e}", file=sys.stderr)
        return 1

    # Forward the rest of the argv to the area's main().
    return sub_main(argv[1:])


def _print_top_help(stream=sys.stdout) -> None:
    print(__doc__.split("\n\n", 1)[0], file=stream)
    print(file=stream)
    print(f"unspooled {__version__}", file=stream)
    print(file=stream)
    print("Usage: rongta_config.py <area> [args...]", file=stream)
    print("       rongta_config.py --version", file=stream)
    print(file=stream)
    print("Areas:", file=stream)
    width = max(len(a) for a in AREAS)
    for area, (_mod, helptext) in AREAS.items():
        print(f"  {area:<{width}}  {helptext}", file=stream)
    print(file=stream)
    print("Run 'rongta_config.py <area> --help' for area-specific options.", file=stream)


if __name__ == "__main__":
    sys.exit(main())
