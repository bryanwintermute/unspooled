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


def test_default_sanitizer_translates_smart_quotes_and_em_dashes():
    """Default sanitize=True turns smart-quotes / em-dashes into ASCII.

    This is a behavior CHANGE from v0.2.0 (which silently `?`-replaced
    them at CP437 encode time). The new default matches what callers
    almost always actually want; opt-out with sanitize=False to get
    the old behavior.
    """
    r = Receipt(timestamp=False)
    r.add_items(["smart \u201cquotes\u201d and em\u2014dashes"])
    out = r.to_bytes()
    assert b'"quotes"' in out
    assert b"em--dashes" in out
    assert b"?" not in out


def test_sanitize_false_preserves_v020_silent_question_mark_replacement():
    """Opt-out path: sanitize=False reproduces v0.2.0 CP437 fallback.

    This is the byte-equality contract for downstream consumers that
    already do their own preprocessing and want raw v0.2.0 behavior.
    """
    r = Receipt(timestamp=False, sanitize=False)
    r.add_items(["smart \u201cquotes\u201d and em\u2014dashes"])
    out = r.to_bytes()
    assert b"?" in out


def test_sanitize_dict_extends_default_map():
    r = Receipt(timestamp=False, sanitize={"\u00B5": "u"})  # micro-sign
    r.add_items(["10 \u00B5s"])
    out = r.to_bytes()
    assert b"10 us" in out
    # Defaults still apply on top:
    r2 = Receipt(timestamp=False, sanitize={"\u00B5": "u"})
    r2.add_items(["\u201Chi\u201D"])
    assert b'"hi"' in r2.to_bytes()


def test_sanitize_callable_replaces_default_pipeline():
    r = Receipt(timestamp=False, sanitize=lambda s: s.upper())
    r.add_items(["hello"])
    assert b"HELLO" in r.to_bytes()


def test_sanitize_invalid_type_raises():
    with pytest.raises(TypeError):
        Receipt(timestamp=False, sanitize=42)


def test_sanitize_is_idempotent():
    """sanitize(sanitize(x)) == sanitize(x) — no double-translation drift."""
    from receipt_print import sanitize
    s = "smart \u201cquotes\u201d, em\u2014dash, ellipsis\u2026, arrow\u2192, caf\u00E9"
    once = sanitize(s)
    twice = sanitize(once)
    assert once == twice


def test_sanitize_strips_accents_via_nfkd():
    """`caf\u00E9` (e + acute as one char) → `cafe` via NFKD + combining-mark drop."""
    from receipt_print import sanitize
    assert sanitize("caf\u00E9") == "cafe"
    assert sanitize("na\u00EFve") == "naive"
    assert sanitize("r\u00F6le") == "role"

def test_sanitize_translates_fractions():
    """Sanitizer translates Latin-1 unicode fractions into ASCII equivalents."""
    from receipt_print import sanitize
    # Standalone fractions (no leading digit) → ASCII forms.
    assert sanitize("\u00BC cup") == "1/4 cup"
    assert sanitize("\u00BD off") == "1/2 off"
    assert sanitize("\u00BE inch") == "3/4 inch"


def test_sanitize_inserts_space_for_mixed_numbers():
    """Mixed-number convention: `1\u00BC` should render as `1 1/4`, not `11/4`.

    Without the digit-fraction spacing pass, the recipe-style
    `"1\u00BC cups"` (one and a quarter cups) would silently degrade
    to `"11/4 cups"` — visually eleven-quarters, semantically wrong.
    """
    from receipt_print import sanitize
    assert sanitize("1\u00BC cups") == "1 1/4 cups"
    assert sanitize("2\u00BD tsp") == "2 1/2 tsp"
    assert sanitize("3\u00BE lb") == "3 3/4 lb"
    # Multi-digit prefix also works.
    assert sanitize("10\u00BD oz") == "10 1/2 oz"


def test_sanitize_number_forms_block_also_supported():
    """The spacing regex covers the whole \u2150-\u215E Number Forms block.

    These chars aren't in DEFAULT_SANITIZE_MAP yet (which only lists
    \u00BC-\u00BE), so the *translation* is whatever NFKD decomposes
    them to. But the *spacing* pass still fires, which is what we're
    asserting here — the regex stays valid as the map is extended.
    """
    from receipt_print import sanitize
    # \u2153 = ⅓. NFKD decomposes to "1\u20444" (digit + fraction-slash + digit).
    # The spacing regex inserts a space before it; the leading digit gets
    # the separator regardless of whether \u2153 itself is mapped.
    result = sanitize("1\u2153 cups")
    assert result.startswith("1 "), f"expected leading-digit space, got {result!r}"


def test_sanitize_does_not_insert_space_for_non_fraction_chars():
    """`5\u00D7` (5 + multiplication-sign) → `5x`, no space inserted."""
    from receipt_print import sanitize
    assert sanitize("5\u00D73") == "5x3"
    assert sanitize("5\u21923") == "5->3"


def test_default_sanitize_map_is_extendable_via_constant_import():
    """Consumers should be able to import + read DEFAULT_SANITIZE_MAP."""
    from receipt_print import DEFAULT_SANITIZE_MAP
    assert "\u2014" in DEFAULT_SANITIZE_MAP  # em-dash
    assert DEFAULT_SANITIZE_MAP["\u2014"] == "--"
    assert "\u2192" in DEFAULT_SANITIZE_MAP  # arrow
    assert DEFAULT_SANITIZE_MAP["\u2192"] == "->"
    assert "\u00BD" in DEFAULT_SANITIZE_MAP  # half fraction
    assert DEFAULT_SANITIZE_MAP["\u00BD"] == "1/2"


def test_sanitize_preserves_ascii_unchanged():
    """Pure ASCII input must round-trip unchanged through the sanitizer."""
    from receipt_print import sanitize
    s = "milk\neggs\nbread [ ] 1. - hello world!"
    assert sanitize(s) == s


def test_ascii_only_input_is_byte_identical_with_and_without_sanitize():
    """v0.2.0 byte-equality contract: pure ASCII input emits identical
    bytes whether sanitize=True (new default) or sanitize=False (v0.2.0
    behavior). Anything else is a regression for downstream callers
    pinning to a fixture."""
    r_new = Receipt(timestamp=False, sanitize=True)
    r_old = Receipt(timestamp=False, sanitize=False)
    items = ["milk", "eggs", "bread"]
    r_new.add_items(items)
    r_old.add_items(items)
    assert r_new.to_bytes() == r_old.to_bytes()


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
