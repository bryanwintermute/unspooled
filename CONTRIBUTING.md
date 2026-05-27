# Contributing to unspooled

Thanks for your interest! Quick orientation on what's tested,
what isn't, and what kind of help is most useful.

## Tested vs untested (YMMV)

- **Tested on:** Rongta RP332 (RP332A revision, USB id
  `0fe6:811e`, firmware shipping with `PrinterTool.exe` v2.63.0).
  This is the only SKU the maintainer has on hand.
- **Likely works on (untested):** other Rongta SKUs that share
  the same `PrinterTool.exe` config tool — RP325, RP326, RP328,
  RP330, RP410, etc. The protocol is the same wire format across
  the line; only the available settings differ.
- **Definitely won't work as-is:** non-Rongta thermal printers,
  even ones that accept ESC/POS. The Rongta-vendor commands
  (`1f 73 …`, `1f 1b 1f …`, `1f 7b …`, etc.) are proprietary
  extensions, not standard ESC/POS.

The bytes are **not officially documented anywhere we've seen.**
Rongta hasn't published a spec, and the vendor mobile SDKs ship
the relevant methods as stub implementations
(see `docs/vendor-mobile-sdks-may-stub-nv-config.md`). Treat
every new model as needing fresh empirical capture, not protocol
divination.

## Issue + PR policy

This is a side-project. The maintainer's policy is:

- **File an issue if something doesn't work** — there's a
  template for RP332 bugs and one for other-SKU compatibility
  reports. They have different SLAs (informally: RP332 bugs
  best-effort soon, other-SKU reports best-effort whenever).
- **No SLA on responses** — please don't be surprised if it
  takes weeks.
- **PRs are the fastest path to a fix**, especially for SKUs
  the maintainer can't test directly.
- **No promises on landing PRs**, but if you read this file and
  follow it, you're already ~90% of the way there.

## Help especially wanted

The maintainer has **no WiFi/Bluetooth-equipped Rongta hardware
on hand**, so the corresponding tabs in `PrinterTool.exe` were
never reverse-engineered. If you have such hardware AND are
willing to repeat the Wine + logging-CUPS-backend technique on
it, please open an issue using the "Help wanted — WiFi /
Bluetooth support" template. The technique is fully documented
in [`docs/wine-cups-backend-recovers-nv-bytes.md`](docs/wine-cups-backend-recovers-nv-bytes.md);
the missing piece is just the hardware.

Same goes for the "Search Printer" tab (UDP-broadcast discovery
protocol).

## How to add support for a new SKU

1. **Set up the RE harness** described in
   [`docs/wine-cups-backend-recovers-nv-bytes.md`](docs/wine-cups-backend-recovers-nv-bytes.md):
   - usbip-export the printer to an x86_64 Linux host
   - Install Wine + Xvfb + x11vnc + the custom CUPS backend
   - Verify a click on the vendor tool's "Set" produces a `.bin`
     file in `/tmp/rongta-writes/`
2. **Capture the SKU's defaults.** Click every Set button with
   no field changes. Save the resulting `.bin` files. Compare
   to the existing tests in `tests/test_dry_run_bytes.py`.
3. **Diff against RP332.** If the bytes match exactly, the SKU
   shares the protocol — just add the SKU to the README and
   the tested-on list. If the bytes differ, figure out where:
   - Different `1f 73 XX` opcode? → likely a vendor-extension
     versioning byte; document it.
   - Extra/missing 3-byte sub-records? → the SKU has more or
     fewer settings; extend the dataclass.
   - Different encoding for a known setting? → most likely
     an inverted-vs-normal boolean swap. Document.
4. **Add tests.** Every new byte sequence belongs in
   `tests/test_dry_run_bytes.py` with a clear label and a citation
   of the SKU + firmware version. The tests are intentionally
   verbose-by-design — they exist to lock in vendor wire format,
   so the labels should be readable years from now.
5. **Open a PR** using the PR template. Include:
   - The new tests
   - A README update naming the newly-supported SKU
   - A note in `docs/` if the SKU has bytes we didn't see on
     RP332 (a new lesson, OR a section in
     `rongta-rp332-vendor-tool-replacement-recap.md`)

## Code style

- **Stdlib only.** Don't add `pip install` dependencies for
  runtime code. The whole point is that this CLI works on any
  Pi with Python 3.9+ and zero setup.
- **Pytest dev-dep is OK** for the test suite (it doesn't ship
  to runtime).
- **One module per area** — each `*_config.py` corresponds to one
  tab in `PrinterTool.exe`. Don't fold them together; the per-tab
  granularity helps reverse-engineers map back to the vendor UI.
- **Document the wire format in module docstrings.** Each module's
  module-level docstring lists the bytes, the encoding, and any
  footguns (inverted booleans, endianness flips, firmware-echo
  prints, …). New commands need the same treatment.

## Running tests

```bash
python3 -m pip install --user pytest    # one-time
python3 -m pytest tests/ -v
```

The full suite is 48 byte-equality tests at the time of this
writing; it runs in ~0.1s.

## Reporting protocol-related bugs

If the bytes the CLI sends don't match what your printer expects
(or, more commonly, "I set X via this CLI and the self-test
report shows Y"), use the relevant issue template. The
information requested by the template is the bare minimum
needed to even start triaging.

## Out of scope

- **Print-rendering features** beyond `receipt_print.py`. If you
  want fancy layout / barcodes / images, the
  [`python-escpos`](https://github.com/python-escpos/python-escpos)
  library is excellent and we'd prefer not to duplicate it.
- **PyPI packaging.** This is a stdlib-only repo intentionally;
  the friction of "clone, run" is acceptable for this audience.
- **GUI wrappers.** The CLI is the surface; if you want a GUI,
  build it as a separate project that shells out.
