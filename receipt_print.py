#!/usr/bin/env python3
"""Stdlib-only ESC/POS renderer for 80mm and 58mm thermal receipt printers.

Designed to be:
- usable as a CLI: `python3 receipt_print.py --title 'Costco' < items.txt`
- importable as a library: `from receipt_print import Receipt, render_markdown`

Two rendering paths from the same public surface:

- `Receipt(...)` for a simple list of items with a single uniform style
  (checkbox / bullet / numbered / plain).
- `render_markdown(text, ...)` for a heterogeneous mix of headings,
  bold spans, lists, and paragraphs — a constrained CommonMark subset
  (see the 'Markdown renderer' section below for what's supported).

`Receipt.from_markdown(text, **kwargs)` is a thin classmethod wrapper
around `render_markdown` for API symmetry.

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
`Receipt()` (or `render_markdown()`) for 58mm or other widths.

Text sanitization (on by default since v0.3.0):
Pass `sanitize=False` to skip the NFKD + smart-quote/em-dash/ellipsis/
arrow translation pass. See `sanitize()` for the pipeline and
`DEFAULT_SANITIZE_MAP` for the built-in translations.

References for the command set used here:
  https://escpos.readthedocs.io/en/latest/  (community spec)
  Epson TM-T88 programming reference
"""

from __future__ import annotations

import argparse
import sys
import textwrap
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping

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


# Map of Unicode chars commonly found in real-world text (clipboard pastes,
# markdown source, copied notes) that are NOT in CP437 and would otherwise
# be silently `?`-replaced when encoded for the printer. Mapped to ASCII
# equivalents that DO survive CP437. Extend by passing `sanitize=` a dict;
# the user dict is merged on top of this default map. Replace entirely by
# passing `sanitize=` a callable.
DEFAULT_SANITIZE_MAP: dict[str, str] = {
    # Smart quotes
    "\u2018": "'",   # left single quotation mark
    "\u2019": "'",   # right single quotation mark / apostrophe
    "\u201A": "'",   # single low-9 quotation mark
    "\u201C": '"',   # left double quotation mark
    "\u201D": '"',   # right double quotation mark
    "\u201E": '"',   # double low-9 quotation mark
    # Dashes
    "\u2013": "-",   # en-dash
    "\u2014": "--",  # em-dash
    "\u2015": "--",  # horizontal bar
    "\u2212": "-",   # minus sign
    # Punctuation
    "\u2026": "...", # horizontal ellipsis
    "\u2022": "*",   # bullet
    "\u00B7": "*",   # middle dot
    "\u2027": "*",   # hyphenation point
    "\u00A0": " ",   # non-breaking space
    "\u2009": " ",   # thin space
    "\u200B": "",    # zero-width space
    "\u00AB": '"',   # left guillemet
    "\u00BB": '"',   # right guillemet
    # Arrows (frequent in shell tutorials, todo lists)
    "\u2190": "<-",
    "\u2192": "->",
    "\u2194": "<->",
    "\u21D0": "<=",
    "\u21D2": "=>",
    "\u21D4": "<=>",
    # Math / misc
    "\u00D7": "x",   # multiplication sign
    "\u2713": "v",   # checkmark
    "\u2717": "x",   # ballot x
    "\u2122": "(TM)",
    "\u00AE": "(R)",
    "\u00A9": "(C)",
    "\u00B0": " deg ",
}


def sanitize(
    s: str,
    extra: Mapping[str, str] | None = None,
) -> str:
    """Normalize a string for safe CP437 encoding.

    Pipeline:
      1. Translate via the merged map (DEFAULT_SANITIZE_MAP + extra).
         This pass catches chars whose NFKD decomposition would
         otherwise lose information — `\u00B5` (micro-sign) NFKD-decomposes
         to `\u03BC` (Greek mu), so a user `{"\u00B5": "u"}` mapping
         would silently miss its target if translation happened only
         after NFKD.
      2. Unicode NFKD normalization (decomposes accented chars into
         base + combining marks, so `\u00E9` → `e` + combining acute,
         and step 4 drops the combining mark).
      3. Translate again via the same merged map. This pass catches any
         NFKD-emitted chars that happen to also be in the map.
      4. Strip combining marks (category Mn) that survived NFKD (so
         accented characters that round-tripped through NFKD lose the
         accent instead of being silently `?`-replaced at CP437 time).

    If `extra` is given, it's merged on top of the default map — your
    entries win on key collision. Pass `extra={}` to use only the
    defaults (which is also what `extra=None` does).

    The result is a string. CP437 encoding still happens at the
    `_encode()` layer, which keeps `errors='replace'` as a last-line
    safety net for anything sanitize() didn't catch.

    This function is idempotent: sanitize(sanitize(x)) == sanitize(x).
    """
    table = str.maketrans(
        DEFAULT_SANITIZE_MAP if extra is None else {**DEFAULT_SANITIZE_MAP, **extra}
    )
    s = s.translate(table)
    s = unicodedata.normalize("NFKD", s)
    s = s.translate(table)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


# Type alias for the `sanitize=` constructor argument.
SanitizeArg = bool | Mapping[str, str] | Callable[[str], str]


def _resolve_sanitizer(arg: SanitizeArg) -> Callable[[str], str] | None:
    """Convert a Receipt(sanitize=) argument into a callable or None."""
    if arg is False:
        return None
    if arg is True:
        return sanitize
    if callable(arg):
        return arg
    if isinstance(arg, Mapping):
        return lambda s, _extra=dict(arg): sanitize(s, extra=_extra)
    raise TypeError(
        f"sanitize= must be bool, Mapping, or callable; got {type(arg).__name__}"
    )


def _encode(s: str, sanitizer: Callable[[str], str] | None = None) -> bytes:
    """Encode to CP437 with safe fallback for unsupported chars.

    If `sanitizer` is given, runs the text through it first — typically
    Receipt() resolves the user's `sanitize=` argument to a callable
    once at construction and passes it to every _encode() call so the
    inner-loop overhead is just one function call.
    """
    if sanitizer is not None:
        s = sanitizer(s)
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

    sanitize controls text preprocessing before CP437 encoding:
      - True (default): run text through the built-in sanitize() —
        smart quotes / em-dashes / ellipses / accented chars / common
        arrows become ASCII equivalents instead of being silently
        `?`-replaced by CP437.
      - False: skip the sanitizer. Bytes are identical to v0.2.0 for
        any input. Use this if you've already preprocessed text or
        you want to see exactly which chars CP437 can't handle.
      - dict: extend the built-in map. e.g. sanitize={"\u00B5": "u"}
        adds a micro-sign mapping; defaults still apply for everything
        else. Your entries win on key collision.
      - callable: full custom sanitizer. Signature: (str) -> str.
        Bypasses the built-in map entirely.
    """

    title: str | None = None
    timestamp: bool = True
    items: list[str] = field(default_factory=list)
    style: str = "checkbox"
    cut: bool = True
    print_width: int = DEFAULT_PRINT_WIDTH
    sanitize: SanitizeArg = True

    def __post_init__(self) -> None:
        self._sanitizer = _resolve_sanitizer(self.sanitize)

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
        return _encode(wrapped + "\n", self._sanitizer)

    def to_bytes(self) -> bytes:
        out = bytearray()
        out += INIT + CODEPAGE_CP437

        if self.title:
            out += ALIGN_CENTER + FONT_DOUBLE + BOLD_ON
            out += _encode(self.title.upper(), self._sanitizer) + b"\n"
            out += BOLD_OFF + FONT_NORMAL + ALIGN_LEFT

        if self.timestamp:
            ts = time.strftime("%Y-%m-%d  %H:%M")
            out += ALIGN_CENTER + _encode(ts, self._sanitizer) + b"\n" + ALIGN_LEFT

        if self.title or self.timestamp:
            out += _encode("-" * self.print_width, self._sanitizer) + b"\n"

        for i, item in enumerate(self.items):
            out += self._render_item(i, item)

        if self.items:
            out += _encode("-" * self.print_width, self._sanitizer) + b"\n"

        # Advance paper above the tear/cutter bar (~12mm) then cut.
        out += LF * 5
        if self.cut:
            out += CUT_FULL

        return bytes(out)


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------
# Hand-rolled tokenizer + renderer for a constrained subset of CommonMark.
# Stdlib only — no `markdown`, `mistune`, or `commonmark` dependency.
#
# Supported tokens:
#   # H1                ESC/POS double-size + bold + center
#   ## H2               bold + center
#   ### H3              bold + left-aligned
#   **bold inline**     ESC/POS bold span
#   - item / * item     bullet list (Receipt's "bullet" style)
#   1. item             numbered list (literal number preserved)
#   - [ ] / - [x]       checkbox (also `* [ ]` / `* [x]`)
#   ---                 horizontal rule (also `***` / `___`)
#   blank line          paragraph break
#   anything else       paragraph text, wrapped to print_width
#
# Deliberately out of scope (v1): tables, code blocks, images, links
# (the printer can't follow them), nested lists, blockquotes.
# ---------------------------------------------------------------------------

import re as _re

_RE_HEADING = _re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_RE_HR = _re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$")
_RE_CHECKBOX = _re.compile(r"^[-*]\s+\[([ xX])\]\s+(.+?)\s*$")
_RE_BULLET = _re.compile(r"^[-*]\s+(.+?)\s*$")
_RE_NUMBERED = _re.compile(r"^(\d+)\.\s+(.+?)\s*$")
_RE_BOLD_INLINE = _re.compile(r"\*\*([^*]+?)\*\*")


def _emit_inline(text: str, sanitizer: Callable[[str], str] | None) -> bytes:
    """Encode a single paragraph/heading/item line, honoring **bold** spans."""
    out = bytearray()
    pos = 0
    for m in _RE_BOLD_INLINE.finditer(text):
        if m.start() > pos:
            out += _encode(text[pos:m.start()], sanitizer)
        out += BOLD_ON + _encode(m.group(1), sanitizer) + BOLD_OFF
        pos = m.end()
    if pos < len(text):
        out += _encode(text[pos:], sanitizer)
    return bytes(out)


def _render_markdown_block(
    block_type: str,
    payload,
    sanitizer: Callable[[str], str] | None,
    print_width: int,
) -> bytes:
    """Render one tokenized block to ESC/POS bytes."""
    if block_type == "h1":
        out = ALIGN_CENTER + FONT_DOUBLE + BOLD_ON
        out += _emit_inline(payload, sanitizer) + b"\n"
        out += BOLD_OFF + FONT_NORMAL + ALIGN_LEFT
        return out
    if block_type == "h2":
        out = ALIGN_CENTER + BOLD_ON
        out += _emit_inline(payload, sanitizer) + b"\n"
        out += BOLD_OFF + ALIGN_LEFT
        return out
    if block_type == "h3":
        return BOLD_ON + _emit_inline(payload, sanitizer) + BOLD_OFF + b"\n"
    if block_type == "hr":
        return _encode("-" * print_width, sanitizer) + b"\n"
    if block_type == "paragraph":
        # payload is the merged paragraph text (joined with single spaces).
        wrapped = textwrap.fill(
            payload,
            width=print_width,
            break_long_words=True,
            break_on_hyphens=False,
        )
        return _emit_inline(wrapped, sanitizer) + b"\n"
    if block_type in ("bullet", "checkbox", "numbered"):
        prefix, text = payload  # payload is (prefix_str, text)
        cont_indent = " " * len(prefix)
        wrapped = textwrap.fill(
            text,
            width=print_width,
            initial_indent=prefix,
            subsequent_indent=cont_indent,
            break_long_words=True,
            break_on_hyphens=False,
        )
        return _emit_inline(wrapped, sanitizer) + b"\n"
    if block_type == "blank":
        return b"\n"
    raise ValueError(f"unknown block type: {block_type}")


def _tokenize_markdown(text: str) -> list[tuple[str, object]]:
    """Split markdown into (block_type, payload) tuples.

    Block types: 'h1', 'h2', 'h3', 'hr', 'bullet', 'checkbox', 'numbered',
    'paragraph', 'blank'.

    Paragraph blocks merge consecutive non-blank, non-list-non-heading
    lines into one paragraph (joined by single spaces), CommonMark-style.
    """
    blocks: list[tuple[str, object]] = []
    paragraph_buf: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_buf:
            blocks.append(("paragraph", " ".join(paragraph_buf)))
            paragraph_buf.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            flush_paragraph()
            blocks.append(("blank", None))
            continue

        m = _RE_HR.match(line)
        if m:
            flush_paragraph()
            blocks.append(("hr", None))
            continue

        m = _RE_HEADING.match(line)
        if m:
            flush_paragraph()
            level = len(m.group(1))
            blocks.append((f"h{level}", m.group(2)))
            continue

        m = _RE_CHECKBOX.match(line)
        if m:
            flush_paragraph()
            checked = m.group(1).lower() == "x"
            prefix = "[x] " if checked else "[ ] "
            blocks.append(("checkbox", (prefix, m.group(2))))
            continue

        m = _RE_NUMBERED.match(line)
        if m:
            flush_paragraph()
            prefix = f"{m.group(1)}. "
            blocks.append(("numbered", (prefix, m.group(2))))
            continue

        m = _RE_BULLET.match(line)
        if m:
            flush_paragraph()
            blocks.append(("bullet", ("- ", m.group(1))))
            continue

        paragraph_buf.append(line.strip())

    flush_paragraph()
    # Strip trailing blank blocks for tidy output.
    while blocks and blocks[-1][0] == "blank":
        blocks.pop()
    return blocks


def render_markdown(
    text: str,
    *,
    title: str | None = None,
    timestamp: bool = True,
    cut: bool = True,
    print_width: int = DEFAULT_PRINT_WIDTH,
    sanitize: SanitizeArg = True,
) -> bytes:
    """Render a markdown string to ESC/POS bytes.

    See the 'Markdown renderer' section above for the supported subset.
    Returns a byte stream ready to write to /dev/usb/lp0 (or any other
    ESC/POS device).

    Shares the title / timestamp / horizontal-rule / cut / sanitize
    conventions of Receipt — drop-in equivalent for callers that want
    a printable receipt out of a markdown source instead of a list.
    """
    sanitizer = _resolve_sanitizer(sanitize)

    out = bytearray()
    out += INIT + CODEPAGE_CP437

    if title:
        out += ALIGN_CENTER + FONT_DOUBLE + BOLD_ON
        out += _encode(title.upper(), sanitizer) + b"\n"
        out += BOLD_OFF + FONT_NORMAL + ALIGN_LEFT

    if timestamp:
        ts = time.strftime("%Y-%m-%d  %H:%M")
        out += ALIGN_CENTER + _encode(ts, sanitizer) + b"\n" + ALIGN_LEFT

    if title or timestamp:
        out += _encode("-" * print_width, sanitizer) + b"\n"

    blocks = _tokenize_markdown(text)
    for block_type, payload in blocks:
        out += _render_markdown_block(block_type, payload, sanitizer, print_width)

    if blocks:
        out += _encode("-" * print_width, sanitizer) + b"\n"

    out += LF * 5
    if cut:
        out += CUT_FULL

    return bytes(out)


# Class-level convenience for callers who prefer the Receipt.from_markdown idiom.
def _receipt_from_markdown(cls, text: str, **kwargs) -> bytes:
    """Receipt.from_markdown(text, **kwargs) -> bytes.

    Thin wrapper around render_markdown. Returns bytes directly rather
    than a Receipt instance because markdown is heterogeneous (headings,
    paragraphs, lists) while Receipt is item-list-shaped — the two
    don't compose into a single dataclass without losing information.
    """
    return render_markdown(text, **kwargs)


Receipt.from_markdown = classmethod(_receipt_from_markdown)  # type: ignore[attr-defined]


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
        "--no-sanitize",
        action="store_true",
        help=(
            "Skip the smart-quote / em-dash / accent sanitizer. By default "
            "input text is normalized (NFKD + a built-in map) before CP437 "
            "encoding so curly quotes etc. become ASCII equivalents instead "
            "of being silently `?`-replaced."
        ),
    )
    p.add_argument(
        "--markdown",
        action="store_true",
        help=(
            "Treat the input as markdown (rather than one item per line). "
            "Supports # / ## / ### headings, **bold**, -/* bullets, "
            "1. numbered lists, - [ ] / - [x] checkboxes, and --- horizontal "
            "rules. Bypasses --style. See render_markdown() for the full grammar."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Write rendered bytes to stdout instead of the printer.",
    )
    args = p.parse_args(argv)

    if args.file == "-":
        data = sys.stdin.read()
    else:
        with open(args.file, encoding="utf-8") as f:
            data = f.read()

    if args.markdown:
        payload = render_markdown(
            data,
            title=args.title,
            timestamp=not args.no_timestamp,
            cut=not args.no_cut,
            print_width=args.print_width,
            sanitize=not args.no_sanitize,
        )
    else:
        receipt = Receipt(
            title=args.title,
            timestamp=not args.no_timestamp,
            style=args.style,
            cut=not args.no_cut,
            print_width=args.print_width,
            sanitize=not args.no_sanitize,
        )
        receipt.add_items(data.splitlines())
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
