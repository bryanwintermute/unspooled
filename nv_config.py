#!/usr/bin/env python3
"""Configure NV-RAM defaults on the Rongta RP332 receipt printer.

Reverse-engineered from the closed-source vendor tool `PrinterTool.exe`
(v2.63.0, 32-bit MFC) by running it under Wine on a Linux host with the
printer USB-IP-exported from the Raspberry Pi, then capturing every byte
the GUI's "Set" button emitted via a custom CUPS backend that logged jobs
to disk.

The Base tab's "Set" command writes 17 bytes: three concatenated
sub-commands, each `1f XX <args>`. The first command's second byte is
the **baud-rate index** (0=4800, 1=9600, 2=19200 default, 3=38400, …);
the vendor tool ALWAYS rewrites this even when the user didn't change
baud rate, so callers of this CLI must pass `--baud-rate-index N` (or
accept the default `2` = 19200, which preserves the factory default).

    1f 73 <baud_idx> <c3> <c4> <c5> <c6> <c7> <c8> <c9> <c10>  # set base config
    1f 72 <c13>                                                # set auto-reprint
    1f 74 <c16>                                                # set buzzer-after-print

Field-by-field (inverted booleans are noted; this is the printer's wire
encoding, NOT what a sane API would look like):

    baud_idx  Baud rate         0=4800, 1=9600, 2=19200 (default),
                                3=38400, 4=57600, 5=115200, 6=230400,
                                7=460800, 8=921600. Irrelevant on USB
                                but persisted in NV and rewritten by
                                every "Set".
    c3   Cutter             0=on, 1=off  (inverted!)
    c4   Buzzer             0=on, 1=off  (inverted!)
    c5   Drawer (cash)      0=on, 1=off  (inverted!)
    c6   Char/line          0=48 (Font A) / 64 (Font B),  1=42 / 56
    c7   Density            0=Light, 1=Dark
    c8   Code page          See CODE_PAGES dict below; source of truth is
                                the printer's power-on self-test report
                                (which prints its own full code-page
                                table — 48 entries, 5 RESERVE slots).
                                Earlier vendor sources (the 2017 Linux
                                SDK enum, dropdown order in
                                PrinterTool.exe) are subsets/wrong.
    c9   Parity            0=None, 1=Odd, 2=Even (serial port parity; irrelevant on USB)
    c10  Default font       0=Font A, 1=Font B (narrow), 2=Font C
    c13  Auto Reprint       0=off, 1=on
    c16  Buzzer After Print 0=off, 1=on

The footer commands `1f 72 …` and `1f 74 …` also implicitly commit the
preceding `1f 73 02 …` write to NV-RAM and soft-reset the printer's
firmware so the new state takes effect immediately.

Usage:

    # Cutter on, everything else off, default formatting (Bryan's preferred).
    python3 nv_config.py --cutter on --buzzer off --drawer off

    # See exactly what would be written, no actual write.
    python3 nv_config.py --cutter on --dry-run

    # Write all settings explicitly (verbose form).
    python3 nv_config.py --cutter on --buzzer off --drawer off \\
        --char-per-line 48 --density light --code-page pc437 \\
        --font a --auto-reprint off --buzzer-after-print off

WARNING: these writes are persistent (NV-RAM). The printer applies the
new state immediately (soft reset). Power-cycling the printer does NOT
revert. There is no "factory reset" command we have reverse-engineered;
to revert a bad write, run nv_config.py again with the desired values.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DEVICE = "/dev/rongta-receipt"

BAUD_RATES = {
    "4800": 0,
    "9600": 1,
    "19200": 2,
    "38400": 3,
    "57600": 4,
    "115200": 5,
    "230400": 6,
    "460800": 7,
    "921600": 8,
}

CODE_PAGES = {
    # SOURCE OF TRUTH: the printer's power-on-self-test report explicitly
    # prints its own code-page table. The receipt this was transcribed from
    # was captured 2026-05-27 on firmware GD307_V1.14 (23-09-20). All 48
    # entries below are the printer firmware's self-documented mapping;
    # this overrides every other source (the 2017 Linux SDK, the
    # PE-strings-in-reverse trick, dropdown order).
    #
    # Stylistic note: the firmware self-test prints these labels with
    # inconsistent "PC" vs "CP" prefixes (e.g. PC437 and PC865 vs CP865,
    # plus a typo "Cyrilliec" at index 7). We normalize to lowercase
    # 'pcNNN' CLI names; the comments below reflect what the firmware
    # actually prints, prefix charm and all.
    #
    # Entries marked RESERVE in the self-test (indices 11, 12, 13, 14, 33)
    # are NOT named here — write --code-page-raw N if you want to test
    # what the firmware does with them. The remaining 43 entries are
    # exposed via these stable kebab-case names:
    "pc437":       0,   # PC437 [Std.Europe]   — default
    "katakana":    1,   # Katakana
    "pc850":       2,   # PC850 [Multilingual]
    "pc860":       3,   # PC860 [Portuguese]
    "pc863":       4,   # PC863 [Canadian]
    "pc865":       5,   # CP865 [Nordic]
    "wcp1251":     6,   # PC1251 [Cyrillic]   (vendor self-test label is "PC1251")
    "pc866":       7,   # PC866 [Cyrilliec]   (sic — firmware misspells "Cyrillic")
    "mik":         8,   # MIK [Cyrillic/Bulgarian]
    "pc755":       9,   # PC755 [EastEurope]
    "iran":       10,   # Iran
    # 11, 12, 13, 14: RESERVE — use --code-page-raw if you want to probe
    "pc862":      15,   # PC862 [Hebrew]
    "wcp1252":    16,   # PC1252 Latin I
    "wcp1253":    17,   # PC1253 [Greek]
    "pc852":      18,   # PC852 [Latina 2]   (sic — "Latina")
    "pc858":      19,   # PC858 Latin
    "iran-ii":    20,   # Iran II
    "latvian":    21,   # Latvian
    "pc864":      22,   # PC864 [Arabic]
    "iso-8859-1": 23,   # ISO-8859-1
    "pc737":      24,   # CP737 [Greek]
    "wcp1257":    25,   # PC1257 [Baltic]
    "thai":       26,   # Thai
    "pc720":      27,   # PC720 [Arabic]
    "pc855":      28,   # PC855
    "pc857":      29,   # PC857 [Turkish]
    "wcp1250":    30,   # PC1250 [Central Eurpoe]   (sic — "Eurpoe")
    "pc775":      31,   # PC775
    "wcp1254":    32,   # PC1254 [Turkish]
    # 33: RESERVE
    "wcp1256":    34,   # PC1256 [Arabic]
    "wcp1258":    35,   # PC1258 [Vietnam]
    "iso-8859-2": 36,   # ISO-8859-2 [Latin 2]
    "iso-8859-3": 37,   # ISO-8859-3
    "iso-8859-4": 38,   # ISO-8859-4 [Baltic]
    "iso-8859-5": 39,   # ISO-8859-5
    "iso-8859-6": 40,   # ISO-8859-6 [Arabic]
    "iso-8859-7": 41,   # ISO-8859-7
    "iso-8859-8": 42,   # ISO-8859-8 [Hebrew]
    "iso-8859-9": 43,   # ISO-8859-9
    "iso-8859-15": 44,  # ISO-8859-15 [Latin 3]   (sic — actually West Europe + Euro)
    "thai2":      45,   # Thai2
    "pc856":      46,   # PC856
    "pc874":      47,   # CP874   (not in dropdown OR 2017 SDK — only self-test knows)
}

DENSITIES = {"light": 0, "dark": 1}
FONTS = {"a": 0, "b": 1, "c": 2}
PARITIES = {"none": 0, "odd": 1, "even": 2}
CHAR_PER_LINE = {"48": 0, "42": 1}  # 48 implies Font A; 42 implies the narrow option


def _bool_inv(name: str, value: str) -> int:
    """Inverted boolean: 'on' -> 0, 'off' -> 1."""
    if value == "on":
        return 0
    if value == "off":
        return 1
    raise ValueError(f"{name}: expected 'on' or 'off', got {value!r}")


def _bool(name: str, value: str) -> int:
    """Normal boolean: 'on' -> 1, 'off' -> 0."""
    if value == "on":
        return 1
    if value == "off":
        return 0
    raise ValueError(f"{name}: expected 'on' or 'off', got {value!r}")


@dataclass
class BaseConfig:
    cutter: str = "on"
    buzzer: str = "off"
    drawer: str = "off"
    char_per_line: str = "48"
    density: str = "light"
    code_page: int = 0
    parity: str = "none"
    font: str = "a"
    auto_reprint: str = "off"
    buzzer_after_print: str = "off"
    baud_rate: str = "19200"

    def to_bytes(self) -> bytes:
        baud_idx = BAUD_RATES[self.baud_rate]
        c3 = _bool_inv("cutter", self.cutter)
        c4 = _bool_inv("buzzer", self.buzzer)
        c5 = _bool_inv("drawer", self.drawer)
        c6 = CHAR_PER_LINE[self.char_per_line]
        c7 = DENSITIES[self.density]
        c8 = int(self.code_page)
        c9 = PARITIES[self.parity]
        c10 = FONTS[self.font]
        c13 = _bool("auto_reprint", self.auto_reprint)
        c16 = _bool("buzzer_after_print", self.buzzer_after_print)

        return bytes([
            0x1F, 0x73, baud_idx,                    # set base config (baud + flags)
            c3, c4, c5, c6, c7, c8, c9, c10,         # 8-byte payload
            0x1F, 0x72, c13,                         # set auto-reprint
            0x1F, 0x74, c16,                         # set buzzer-after-print
        ])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument("--cutter", choices=["on", "off"], default="on")
    p.add_argument("--buzzer", choices=["on", "off"], default="off")
    p.add_argument("--drawer", choices=["on", "off"], default="off",
                   help="Cash-drawer kick output (RJ11 pin trigger).")
    p.add_argument(
        "--baud-rate",
        choices=list(BAUD_RATES),
        default="19200",
        help=(
            "Baud rate for the serial port. Irrelevant on USB but the "
            "Set command always rewrites this byte — default preserves "
            "the factory value."
        ),
    )
    p.add_argument("--char-per-line", choices=list(CHAR_PER_LINE), default="48")
    p.add_argument("--density", choices=list(DENSITIES), default="light")

    code_page = p.add_mutually_exclusive_group()
    code_page.add_argument(
        "--code-page",
        choices=list(CODE_PAGES),
        default="pc437",
        help="Default code page (named).",
    )
    code_page.add_argument(
        "--code-page-raw",
        type=int,
        help="Default code page as a raw byte value (0-255) for unknown pages.",
    )

    p.add_argument("--font", choices=list(FONTS), default="a")
    p.add_argument(
        "--parity",
        choices=list(PARITIES),
        default="none",
        help=(
            "Serial port parity (irrelevant on USB but persisted in NV "
            "and rewritten by every Set)."
        ),
    )
    p.add_argument("--auto-reprint", choices=["on", "off"], default="off")
    p.add_argument("--buzzer-after-print", choices=["on", "off"], default="off")
    p.add_argument(
        "--reserved-9",
        type=int,
        default=None,
        help=argparse.SUPPRESS,  # historical alias; --parity is the new name
    )
    p.add_argument(
        "--device",
        default=DEFAULT_DEVICE,
        help=f"Printer device (default: {DEFAULT_DEVICE}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the 17 bytes that would be written, instead of writing.",
    )

    args = p.parse_args(argv)

    code_page_val = (
        args.code_page_raw if args.code_page_raw is not None
        else CODE_PAGES[args.code_page]
    )

    config = BaseConfig(
        cutter=args.cutter,
        buzzer=args.buzzer,
        drawer=args.drawer,
        char_per_line=args.char_per_line,
        density=args.density,
        code_page=code_page_val,
        parity=args.parity,
        font=args.font,
        auto_reprint=args.auto_reprint,
        buzzer_after_print=args.buzzer_after_print,
        baud_rate=args.baud_rate,
    )

    payload = config.to_bytes()

    if args.dry_run:
        print(payload.hex(" "))
        return 0

    dev = Path(args.device)
    try:
        with dev.open("wb", buffering=0) as f:
            f.write(payload)
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
