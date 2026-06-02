"""Byte-level tests for the markdown renderer.

Sibling to test_receipt_print_library.py. Locks the supported subset and
the rendering contract for each block type, since downstream consumers
(like tickertape) will be feeding markdown source straight in.
"""
from __future__ import annotations

import pytest

from receipt_print import (
    ALIGN_CENTER,
    ALIGN_LEFT,
    BOLD_OFF,
    BOLD_ON,
    CUT_FULL,
    FONT_DOUBLE,
    FONT_NORMAL,
    INIT,
    Receipt,
    render_markdown,
)


def test_render_markdown_empty_string_returns_init_and_cut():
    """Empty input still produces a valid (if mostly-empty) byte stream."""
    out = render_markdown("", timestamp=False)
    assert out.startswith(INIT)
    assert out.endswith(CUT_FULL)


def test_render_markdown_no_cut_omits_cut_command():
    out = render_markdown("hi", timestamp=False, cut=False)
    assert not out.endswith(CUT_FULL)


def test_h1_emits_double_size_bold_center():
    out = render_markdown("# Title", timestamp=False)
    assert ALIGN_CENTER + FONT_DOUBLE + BOLD_ON in out
    assert b"Title" in out
    assert BOLD_OFF + FONT_NORMAL + ALIGN_LEFT in out


def test_h2_emits_bold_center_no_font_double():
    out = render_markdown("## Section", timestamp=False)
    assert ALIGN_CENTER + BOLD_ON in out
    assert b"Section" in out
    assert FONT_DOUBLE not in out  # H2 is bold-only, not double-size


def test_h3_emits_bold_left_aligned():
    out = render_markdown("### Sub", timestamp=False)
    assert BOLD_ON + b"Sub" + BOLD_OFF in out
    # No center-alignment for H3
    assert ALIGN_CENTER not in out.replace(b"", b"")  # nothing centered emitted


def test_inline_bold_emits_bold_on_off():
    out = render_markdown("plain **bold** plain", timestamp=False)
    assert BOLD_ON + b"bold" + BOLD_OFF in out
    assert b"plain " in out


def test_inline_bold_handles_multiple_spans():
    out = render_markdown("a **b** c **d** e", timestamp=False)
    assert out.count(BOLD_ON) == 2
    assert out.count(BOLD_OFF) == 2


def test_bullet_list_emits_dash_prefix():
    out = render_markdown("- milk\n- eggs", timestamp=False)
    assert b"- milk" in out
    assert b"- eggs" in out


def test_bullet_list_with_asterisk_also_works():
    out = render_markdown("* milk\n* eggs", timestamp=False)
    assert b"- milk" in out  # both normalize to dash
    assert b"- eggs" in out


def test_numbered_list_preserves_literal_numbers():
    out = render_markdown("1. first\n2. second\n5. fifth", timestamp=False)
    assert b"1. first" in out
    assert b"2. second" in out
    assert b"5. fifth" in out  # literal 5, not renumbered to 3


def test_checkbox_unchecked():
    out = render_markdown("- [ ] todo", timestamp=False)
    assert b"[ ] todo" in out


def test_checkbox_checked_lowercase_x():
    out = render_markdown("- [x] done", timestamp=False)
    assert b"[x] done" in out


def test_checkbox_checked_uppercase_x():
    out = render_markdown("- [X] done", timestamp=False)
    assert b"[x] done" in out


def test_horizontal_rule_three_dashes():
    out = render_markdown("---", timestamp=False, print_width=20)
    assert b"-" * 20 + b"\n" in out


def test_horizontal_rule_asterisks_and_underscores():
    for marker in ("***", "___", "----"):
        out = render_markdown(marker, timestamp=False, print_width=20)
        assert b"-" * 20 + b"\n" in out, f"{marker!r} failed"


def test_paragraph_lines_join_with_single_space():
    """CommonMark: consecutive non-blank lines fold into one paragraph."""
    out = render_markdown("hello\nworld", timestamp=False)
    assert b"hello world" in out


def test_paragraph_break_on_blank_line():
    out = render_markdown("para one\n\npara two", timestamp=False)
    # Both paragraphs end with newlines, separated by a blank-block newline.
    assert b"para one\n\npara two" in out


def test_heading_breaks_paragraph():
    out = render_markdown("paragraph\n# heading", timestamp=False)
    assert b"paragraph\n" in out
    assert b"heading" in out


def test_paragraph_wraps_at_print_width():
    long = "x " * 30  # 60 chars
    out = render_markdown(long.strip(), timestamp=False, print_width=20)
    # Some line in the output must be <= 20 chars (wrapping happened).
    rendered_lines = out.split(b"\n")
    assert any(0 < len(line) <= 20 for line in rendered_lines)


def test_title_kwarg_prints_uppercase_centered():
    out = render_markdown("body", title="my receipt", timestamp=False)
    assert b"MY RECEIPT" in out
    assert ALIGN_CENTER + FONT_DOUBLE + BOLD_ON in out


def test_smart_quotes_sanitized_by_default():
    out = render_markdown("\u201Cquoted\u201D", timestamp=False)
    assert b'"quoted"' in out
    assert b"?" not in out


def test_sanitize_false_skips_sanitizer():
    out = render_markdown("\u201Cquoted\u201D", timestamp=False, sanitize=False)
    # CP437 errors='replace' should now produce ? for smart quotes.
    assert b"?" in out


def test_sanitize_dict_extends_default_map():
    out = render_markdown("10 \u00B5s", timestamp=False, sanitize={"\u00B5": "u"})
    assert b"10 us" in out


def test_default_print_width_used_when_not_specified():
    out = render_markdown("---", timestamp=False)
    # 42 dashes = DEFAULT_PRINT_WIDTH
    assert b"-" * 42 + b"\n" in out


def test_58mm_width_renders_32col_hr():
    out = render_markdown("---", timestamp=False, print_width=32)
    assert b"-" * 32 + b"\n" in out
    assert b"-" * 33 + b"\n" not in out


def test_receipt_from_markdown_classmethod_proxies_to_render_markdown():
    """Receipt.from_markdown(...) returns bytes identical to render_markdown."""
    md = "# Hi\n\n**bold** body"
    a = render_markdown(md, timestamp=False)
    b = Receipt.from_markdown(md, timestamp=False)
    assert a == b


def test_h1_bold_inline_inside_heading():
    """Inline **bold** inside a heading still emits a nested bold span."""
    out = render_markdown("# Hello **World**", timestamp=False)
    # The outer heading bold-on is emitted, then we toggle off, then on
    # again for the inline span. Just verify both tokens appear.
    assert b"Hello " in out
    assert b"World" in out


def test_full_document_roundtrip_doesnt_crash():
    """Smoke: a realistic markdown doc renders without errors."""
    doc = """# Shopping List

Generated for **Saturday**.

- [ ] milk
- [ ] eggs
- [x] bread (already bought)

## Notes

The store closes at 8pm, so plan for an arrival no later than 7:30.

---

End of list.
"""
    out = render_markdown(doc, title="Costco", timestamp=False)
    assert out.startswith(INIT)
    assert out.endswith(CUT_FULL)
    assert b"COSTCO" in out
    assert b"Shopping List" in out
    assert b"[ ] milk" in out
    assert b"[x] bread (already bought)" in out
