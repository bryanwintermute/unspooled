"""Byte-level regression tests for receipt_print.Receipt as a library.

These complement test_dry_run_bytes.py (which tests the CLI dispatcher
end-to-end). They lock the public `Receipt` API and the default-vs-58mm
print widths, since `unspooled` is positioned as a vendorable / importable
ESC/POS renderer for downstream apps (like `tickertape`).
"""
from __future__ import annotations

import pytest

from receipt_print import (
    CUT_FULL,
    DEFAULT_PRINT_WIDTH,
    INIT,
    Receipt,
)


def test_default_print_width_is_42():
    """80mm Font A. Don't change without bumping a major."""
    assert DEFAULT_PRINT_WIDTH == 42


def test_empty_receipt_starts_with_init_and_ends_with_cut():
    """No title, no timestamp, no items → ESC @ + ESC t 0 + 5 LF + GS V 0."""
    r = Receipt(timestamp=False)
    out = r.to_bytes()
    assert out.startswith(INIT)
    assert out.endswith(CUT_FULL)


def test_no_cut_omits_cut_command():
    r = Receipt(timestamp=False, cut=False)
    out = r.to_bytes()
    assert not out.endswith(CUT_FULL)


def test_default_width_renders_42col_hr():
    """The horizontal rule under the items is 42 dashes (80mm Font A)."""
    r = Receipt(timestamp=False)
    r.add_items(["x"])
    out = r.to_bytes()
    assert b"-" * 42 + b"\n" in out
    assert b"-" * 43 + b"\n" not in out


def test_58mm_width_renders_32col_hr():
    """print_width=32 (58mm Font A) → 32-dash horizontal rules."""
    r = Receipt(timestamp=False, print_width=32)
    r.add_items(["x"])
    out = r.to_bytes()
    assert b"-" * 32 + b"\n" in out
    assert b"-" * 33 + b"\n" not in out


def test_print_width_kwarg_affects_textwrap():
    """A long item gets wrapped at print_width, not the default."""
    long_text = "x" * 80
    short = Receipt(timestamp=False, print_width=20)
    short.add_items([long_text])
    out = short.to_bytes()
    # All 80 'x's are present.
    assert out.count(b"x") == 80
    # Lines that contain only 'x's (no escape bytes, no prefix bracket) must
    # be at most print_width = 20 cols. The first wrapped chunk shares a
    # line with the printer-init escape sequence ('\x1b@\x1bt\x00[ ] xxxx…'),
    # so skip that one by requiring the line to be all printable + spaces.
    lines = [line for line in out.split(b"\n") if b"x" in line]
    assert len(lines) >= 2, f"expected wrap; got {lines!r}"
    for line in lines:
        # Strip the prefix-only first line, which carries init escapes.
        if line.startswith(b"\x1b"):
            continue
        # Subsequent wrapped lines should be at most print_width cols, with
        # the 4-col continuation indent '    ' prepended by textwrap.
        assert len(line) <= 20, f"line too long: {line!r}"


def test_cp437_fallback_for_unsupported_chars():
    """Smart quotes / em-dashes should encode to ? (not crash)."""
    r = Receipt(timestamp=False)
    r.add_items(["smart \u201cquotes\u201d and em\u2014dashes"])
    out = r.to_bytes()
    # CP437 errors='replace' produces '?' for unknown chars.
    assert b"?" in out


def test_checkbox_style_emits_brackets():
    r = Receipt(timestamp=False, style="checkbox")
    r.add_items(["milk"])
    assert b"[ ] milk" in r.to_bytes()


def test_numbered_style_emits_numbers():
    r = Receipt(timestamp=False, style="numbered")
    r.add_items(["milk", "eggs"])
    out = r.to_bytes()
    assert b"1. milk" in out
    assert b"2. eggs" in out


def test_bullet_style_emits_dashes():
    r = Receipt(timestamp=False, style="bullet")
    r.add_items(["milk"])
    assert b"- milk" in r.to_bytes()


def test_plain_style_has_no_prefix():
    r = Receipt(timestamp=False, style="plain")
    r.add_items(["milk"])
    out = r.to_bytes()
    # No checkbox / bullet / numbered prefix was applied.
    assert b"[ ] milk" not in out
    assert b"- milk" not in out
    assert b"1. milk" not in out
    # And the literal item text is still in the output.
    assert b"milk\n" in out


def test_title_is_uppercased_and_centered():
    r = Receipt(title="costco", timestamp=False)
    out = r.to_bytes()
    assert b"COSTCO" in out
    # Center-align is ESC a 1
    assert b"\x1b\x61\x01" in out


def test_items_round_trip_through_add_items():
    """add_items() strips whitespace and drops empty lines."""
    r = Receipt(timestamp=False, style="plain")
    r.add_items(["  milk  ", "", "eggs\n", "  "])
    assert r.items == ["milk", "eggs"]


@pytest.mark.parametrize(
    "width,expected_dashes",
    [
        (32, 32),  # 58mm Font A
        (42, 42),  # 80mm Font A (default)
        (56, 56),  # 80mm Font B
    ],
)
def test_horizontal_rule_width_matches_print_width(width, expected_dashes):
    r = Receipt(timestamp=False, print_width=width)
    r.add_items(["x"])
    out = r.to_bytes()
    assert b"-" * expected_dashes + b"\n" in out


def test_back_compat_constructor_without_print_width():
    """The print_width kwarg is optional — existing code that doesn't pass
    it must keep working with the historical default."""
    r = Receipt(timestamp=False)
    r.add_items(["milk"])
    # No exception, output is non-empty, and contains the 42-dash HR.
    out = r.to_bytes()
    assert b"-" * 42 + b"\n" in out
