"""Byte-equality regression tests for every reverse-engineered command.

Each parametrized case asserts that the named subcommand's ``--dry-run``
output exactly matches bytes captured from the proprietary
``PrinterTool.exe`` v2.63.0 via the Wine + logging-CUPS-backend technique
documented in ``docs/wine-cups-backend-recovers-nv-bytes.md``.

These are NOT unit tests of internal helpers; they're contract tests
asserting that the CLI's user-facing behaviour matches the vendor wire
protocol. If any of these break, EITHER the wire protocol decoding
changed (likely a bug) OR a default value moved (also a bug — these
defaults are factory-default-matching).

Adding a test: capture bytes from the vendor tool, paste here as a new
parametrize entry. The label in the first column is purely for pytest
output readability.
"""
from __future__ import annotations

import pytest

import rongta_config


def _run(argv: list[str], capsys) -> str:
    """Invoke the unified CLI with argv and return its stdout."""
    rc = rongta_config.main(argv)
    captured = capsys.readouterr()
    assert rc == 0, f"CLI exited {rc} for argv={argv!r}; stderr={captured.err!r}"
    return captured.out.strip()


# Every captured byte sequence here was observed in /tmp/rongta-writes/
# during the Wine reverse-engineering session of 2026-05-25..27.
BASE_CASES = [
    # (label, argv, expected_hex)
    (
        "defaults — cutter only, baud 19200, parity none",
        ["base", "--cutter", "on", "--dry-run"],
        "1f 73 02 00 01 01 00 00 00 00 00 1f 72 00 1f 74 00",
    ),
    (
        "all off — every boolean disabled",
        ["base", "--cutter", "off", "--dry-run"],
        "1f 73 02 01 01 01 00 00 00 00 00 1f 72 00 1f 74 00",
    ),
    (
        "buzzer on alongside cutter on",
        ["base", "--cutter", "on", "--buzzer", "on", "--dry-run"],
        "1f 73 02 00 00 01 00 00 00 00 00 1f 72 00 1f 74 00",
    ),
    (
        "drawer on alongside cutter on",
        ["base", "--cutter", "on", "--drawer", "on", "--dry-run"],
        "1f 73 02 00 01 00 00 00 00 00 00 1f 72 00 1f 74 00",
    ),
    (
        "auto-reprint on",
        ["base", "--auto-reprint", "on", "--dry-run"],
        "1f 73 02 00 01 01 00 00 00 00 00 1f 72 01 1f 74 00",
    ),
    (
        "buzzer-after-print on",
        ["base", "--buzzer-after-print", "on", "--dry-run"],
        "1f 73 02 00 01 01 00 00 00 00 00 1f 72 00 1f 74 01",
    ),
    (
        "baud 9600 → byte[2]=01",
        ["base", "--baud-rate", "9600", "--dry-run"],
        "1f 73 01 00 01 01 00 00 00 00 00 1f 72 00 1f 74 00",
    ),
    (
        "baud 38400 → byte[2]=03",
        ["base", "--baud-rate", "38400", "--dry-run"],
        "1f 73 03 00 01 01 00 00 00 00 00 1f 72 00 1f 74 00",
    ),
    (
        "parity even → byte[9]=02",
        ["base", "--parity", "even", "--dry-run"],
        "1f 73 02 00 01 01 00 00 00 02 00 1f 72 00 1f 74 00",
    ),
    (
        "parity odd → byte[9]=01",
        ["base", "--parity", "odd", "--dry-run"],
        "1f 73 02 00 01 01 00 00 00 01 00 1f 72 00 1f 74 00",
    ),
    (
        "code-page pc850 → byte[8]=02",
        ["base", "--code-page", "pc850", "--dry-run"],
        "1f 73 02 00 01 01 00 00 02 00 00 1f 72 00 1f 74 00",
    ),
    (
        "code-page wcp1252 → byte[8]=10 (verified vs self-test + 2017 SDK)",
        ["base", "--code-page", "wcp1252", "--dry-run"],
        "1f 73 02 00 01 01 00 00 10 00 00 1f 72 00 1f 74 00",
    ),
    (
        "code-page pc874 → byte[8]=2f (only known from self-test, not in dropdown)",
        ["base", "--code-page", "pc874", "--dry-run"],
        "1f 73 02 00 01 01 00 00 2f 00 00 1f 72 00 1f 74 00",
    ),
    (
        "code-page wcp1251 → byte[8]=06 (from self-test, sanity-check the gap)",
        ["base", "--code-page", "wcp1251", "--dry-run"],
        "1f 73 02 00 01 01 00 00 06 00 00 1f 72 00 1f 74 00",
    ),
    (
        "code-page-raw 42 (=ISO-8859-8 [Hebrew], also tests raw passthrough)",
        ["base", "--code-page-raw", "42", "--dry-run"],
        "1f 73 02 00 01 01 00 00 2a 00 00 1f 72 00 1f 74 00",
    ),
    (
        "font c → byte[10]=02",
        ["base", "--font", "c", "--dry-run"],
        "1f 73 02 00 01 01 00 00 00 00 02 1f 72 00 1f 74 00",
    ),
    (
        "density dark → byte[7]=01",
        ["base", "--density", "dark", "--dry-run"],
        "1f 73 02 00 01 01 00 01 00 00 00 1f 72 00 1f 74 00",
    ),
    (
        "char-per-line 42 → byte[6]=01",
        ["base", "--char-per-line", "42", "--dry-run"],
        "1f 73 02 00 01 01 01 00 00 00 00 1f 72 00 1f 74 00",
    ),
]

ETHERNET_CASES = [
    (
        "dhcp on",
        ["ethernet", "dhcp", "on", "--dry-run"],
        "1f 62 44 01",
    ),
    (
        "dhcp off",
        ["ethernet", "dhcp", "off", "--dry-run"],
        "1f 62 44 00",
    ),
    (
        "static set (3 sub-commands)",
        [
            "ethernet", "static",
            "--ip", "192.168.168.255",
            "--mask", "255.255.255.0",
            "--gateway", "192.168.1.1",
            "--dry-run",
        ],
        "1f 69 c0 a8 a8 ff 1f 25 00 ff ff ff 00 1f 25 01 c0 a8 01 01",
    ),
    (
        "static set2 (single command)",
        [
            "ethernet", "static", "--mode", "set2",
            "--ip", "192.168.168.255",
            "--mask", "255.255.255.0",
            "--gateway", "192.168.1.1",
            "--dry-run",
        ],
        "1f 4e c0 a8 a8 ff c0 a8 01 01 ff ff ff 00",
    ),
    (
        "MAC set",
        ["ethernet", "mac", "a8:01:57:3b:ca:60", "--dry-run"],
        "1f 6d a8 01 57 3b ca 60",
    ),
    (
        "MAC accepts hyphens",
        ["ethernet", "mac", "a8-01-57-3b-ca-60", "--dry-run"],
        "1f 6d a8 01 57 3b ca 60",
    ),
    (
        "duplex defaults (100M full auto)",
        ["ethernet", "duplex", "--dry-run"],
        "1f 70 01 01 01",
    ),
    (
        "raw bytes passthrough",
        ["ethernet", "raw", "1f 62 44 01", "--dry-run"],
        "1f 62 44 01",
    ),
]

PAPERSAVE_CASES = [
    (
        "defaults (all off)",
        ["papersave", "--dry-run"],
        "1d 28 45 10 00 05 65 00 00 66 00 00 67 00 00 68 00 00 69 00 00 1d 28 45 04 00 02 4f 55 54",
    ),
    (
        "delete-top enable",
        ["papersave", "--delete-top", "enable", "--dry-run"],
        "1d 28 45 10 00 05 65 01 00 66 00 00 67 00 00 68 00 00 69 00 00 1d 28 45 04 00 02 4f 55 54",
    ),
    (
        "delete-middle enable",
        ["papersave", "--delete-middle", "enable", "--dry-run"],
        "1d 28 45 10 00 05 65 00 00 66 01 00 67 00 00 68 00 00 69 00 00 1d 28 45 04 00 02 4f 55 54",
    ),
    (
        "cut-line-interval 75%",
        ["papersave", "--cut-line-interval", "75%", "--dry-run"],
        "1d 28 45 10 00 05 65 00 00 66 00 00 67 03 00 68 00 00 69 00 00 1d 28 45 04 00 02 4f 55 54",
    ),
]

BLACKMARK_CASES = [
    (
        "enable",
        ["blackmark", "enable", "--dry-run"],
        "1f 1b 1f 80 04 05 06 44",
    ),
    (
        "disable",
        ["blackmark", "disable", "--dry-run"],
        "1f 1b 1f 80 04 05 06 66",
    ),
    (
        "length 300mm",
        ["blackmark", "length", "300", "--dry-run"],
        "1f 1b 1f 81 04 05 06 09 60",
    ),
    (
        "length 100mm",
        ["blackmark", "length", "100", "--dry-run"],
        "1f 1b 1f 81 04 05 06 03 20",
    ),
    (
        "width 10mm",
        ["blackmark", "width", "10", "--dry-run"],
        "1f 1b 1f 82 04 05 06 00 50",
    ),
    (
        "print-after 5mm",
        ["blackmark", "print-after", "5", "--dry-run"],
        "1d 28 46 04 00 01 00 00 28",
    ),
    (
        "cut-after 7mm",
        ["blackmark", "cut-after", "7", "--dry-run"],
        "1d 28 46 04 00 02 00 00 38",
    ),
    (
        "mystery-set",
        ["blackmark", "mystery-set", "--dry-run"],
        "1f 1b 1f 83 04 05 06 01",
    ),
]

OTHER1_CASES = [
    (
        "chinese enable",
        ["other1", "chinese", "enable", "--dry-run"],
        "1f 1b 1f fe 00",
    ),
    (
        "chinese disable",
        ["other1", "chinese", "disable", "--dry-run"],
        "1f 1b 1f fe 01",
    ),
    (
        "alarm-beep open",
        ["other1", "alarm-beep", "open", "--dry-run"],
        "1f 1b 1f 19 02 01",
    ),
    (
        "alarm-light open",
        ["other1", "alarm-light", "open", "--dry-run"],
        "1f 1b 1f 19 03 01",
    ),
    (
        "cutter-query",
        ["other1", "cutter-query", "--dry-run"],
        "1f 1b 1f 19 00 02",
    ),
    (
        "run-out-of-paper disable",
        ["other1", "run-out-of-paper", "disable", "--dry-run"],
        "1f 7b 70 00",
    ),
    (
        "run-out-of-paper enable",
        ["other1", "run-out-of-paper", "enable", "--dry-run"],
        "1f 7b 70 01",
    ),
    (
        "usb-mode printer",
        ["other1", "usb-mode", "printer", "--dry-run"],
        "1f 7b 75 00",
    ),
    (
        "print-width 80mm",
        ["other1", "print-width", "80mm", "--dry-run"],
        "1f 1b 1f a4 01 02 03 11 12 13 55",
    ),
    (
        "print-width 58mm",
        ["other1", "print-width", "58mm", "--dry-run"],
        "1f 1b 1f a4 01 02 03 11 12 13 33",
    ),
    (
        "volume moderate (Epson GS ( E fn=1)",
        ["other1", "volume", "moderate", "--dry-run"],
        "1d 28 45 04 00 01 03 00",
    ),
    (
        "volume softly",
        ["other1", "volume", "softly", "--dry-run"],
        "1d 28 45 04 00 01 02 00",
    ),
    (
        "volume loud",
        ["other1", "volume", "loud", "--dry-run"],
        "1d 28 45 04 00 01 04 00",
    ),
]


def _ids(cases):
    return [c[0] for c in cases]


@pytest.mark.parametrize("label,argv,expected", BASE_CASES, ids=_ids(BASE_CASES))
def test_base(label, argv, expected, capsys):
    assert _run(argv, capsys) == expected


@pytest.mark.parametrize("label,argv,expected", ETHERNET_CASES, ids=_ids(ETHERNET_CASES))
def test_ethernet(label, argv, expected, capsys):
    assert _run(argv, capsys) == expected


@pytest.mark.parametrize("label,argv,expected", PAPERSAVE_CASES, ids=_ids(PAPERSAVE_CASES))
def test_papersave(label, argv, expected, capsys):
    assert _run(argv, capsys) == expected


@pytest.mark.parametrize("label,argv,expected", BLACKMARK_CASES, ids=_ids(BLACKMARK_CASES))
def test_blackmark(label, argv, expected, capsys):
    assert _run(argv, capsys) == expected


@pytest.mark.parametrize("label,argv,expected", OTHER1_CASES, ids=_ids(OTHER1_CASES))
def test_other1(label, argv, expected, capsys):
    assert _run(argv, capsys) == expected
