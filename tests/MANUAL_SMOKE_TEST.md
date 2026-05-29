# Manual smoke-test checklist

The byte-equality test suite (`tests/test_dry_run_bytes.py`) locks in
the **wire protocol** — it guarantees the CLI emits the bytes we
captured from the vendor tool. It does NOT verify that those bytes
make the printer do what we documented they make it do, or that the
udev / `plugdev` / device-path plumbing actually works.

This file is the manual end-to-end checklist for "did the CLI work on
real hardware?". Walk through it before tagging a release, after any
change to the CLI's device-write path, and any time you want to
sanity-check a new SKU.

Expected time: ~10 minutes + ~1 minute per area you smoke-test (each
"Set" command produces a firmware-driven confirmation receipt, so
budget ~12 inches of paper for a full run).

## Before you start

- **Note your firmware version.** Hold FEED on the printer while
  powering it on; the resulting diagnostic receipt prints the
  firmware version near the top (e.g. `GD307_V1.14 23-09-20` on
  the maintainer's RP332).
- **Note your printer's factory MAC.** The same self-test prints
  the Ethernet ID line. Write it down. You may need to restore it
  later in this checklist.
- **Load fresh paper.** Out-of-paper mid-test produces silent
  failures.

Fill in the result column as you go:

## Section 0 — Setup verification

| # | Check | Command | Expected | Pass? |
|---|---|---|---|---|
| 0.1 | `unspooled` is on `PATH` or accessible | `which rongta_config.py` OR `ls ./rongta_config.py` | path or file exists | |
| 0.2 | Version flag works | `./rongta_config.py --version` | `unspooled <version>` | |
| 0.3 | Help renders | `./rongta_config.py --help` | list of 6 areas | |
| 0.4 | Tests pass | `python3 -m pytest tests/` | all green | |
| 0.5 | udev symlink present | `ls -la /dev/rongta-receipt` | symlink → `usb/lp0` | |
| 0.6 | Current user can write | `echo unspooled-smoke > /dev/rongta-receipt` | "unspooled-smoke" prints on paper, no permission error | |
| 0.7 | Self-test trigger works | `printf '\x12T' > /dev/rongta-receipt` | full self-test report prints | |

**If 0.5 or 0.6 fails:** install the udev rule + add yourself to
`plugdev` per the [README](../README.md#setup).

## Section 1 — Capture the BEFORE baseline

Trigger one self-test now and **keep the receipt for comparison**.
We'll write known configs in the following sections, trigger
self-tests after each, and compare line-by-line.

```bash
printf '\x12T' > /dev/rongta-receipt
```

Note these baseline values (they're what you'll restore to at the
end):

| Field | Baseline value |
|---|---|
| Cutter | |
| Beeper | |
| Drawer | |
| Save Paper | |
| BMMode | |
| Chinese | |
| Density | |
| Char/line | |
| Default font | |
| Default code page (Page N / name) | |
| DHCP | |
| Ethernet ID (MAC) | |

## Section 2 — Base tab

For each row: run the CLI command, trigger a self-test, confirm the
indicated field changed on the receipt, then restore via the next row.

| # | Command | What to verify on the resulting self-test | Pass? |
|---|---|---|---|
| 2.1 | `./rongta_config.py base --cutter on` | `Cutter: Yes` | |
| 2.2 | `./rongta_config.py base --cutter off` | `Cutter: No` | |
| 2.3 | `./rongta_config.py base --cutter on --buzzer on` | `Cutter: Yes, Beeper: Yes` (firmware label is "Beeper", not "Buzzer") | |
| 2.4 | `./rongta_config.py base --cutter on --density dark` | `Density: Dark` | |
| 2.5 | `./rongta_config.py base --cutter on --code-page wcp1252` | `Default code page: page 16 / PC1252 Latin I` | |
| 2.6 | `./rongta_config.py base --cutter on --code-page-raw 47` (or `--code-page pc874` if it's named in your version) | `page 47 / CP874` | |
| 2.7 | `./rongta_config.py base --cutter on --font c` | `Default font: Font C` (or similar — the label depends on firmware version) | |
| 2.8 | **RESTORE:** `./rongta_config.py base --cutter on` (or your baseline values from Section 1) | self-test matches Section 1 baseline | |

Don't trigger a self-test after every single row if you want to save
paper — the firmware echoes the change inline. But for fields not in
the echo (e.g. font, code-page name), the self-test is the only
read-back path.

## Section 3 — Ethernet tab

⚠️ The MAC and IP commands are destructive — don't run them without
the baseline written down.

| # | Command | What to verify | Pass? |
|---|---|---|---|
| 3.1 | `./rongta_config.py ethernet dhcp on` | Firmware prints "DHCP: Enable" confirmation; self-test report shows `DHCP: Enabled` | |
| 3.2 | `./rongta_config.py ethernet dhcp off` | Firmware prints "DHCP: Disable"; self-test shows `DHCP: Disabled` | |
| 3.3 | `./rongta_config.py ethernet mac 00:11:22:33:44:55` | Firmware prints "Curr MAC: 0 17 34 51 68 85" (decimal echo). Self-test shows `Ethernet ID: 00-11-22-33-44-55` | |
| 3.4 | **RESTORE MAC:** `./rongta_config.py ethernet mac <your-baseline-MAC>` | Firmware prints decimal echo of restored MAC. Self-test confirms. | |
| 3.5 | `./rongta_config.py ethernet duplex --speed 100 --duplex full` | Self-test shows `Speed: 100M Full` (or similar; firmware label varies) | |

Note: the `static` subcommand isn't in this checklist because it
needs valid LAN values to avoid leaving the printer unreachable from
LAN. If you want to test it, pick an IP in your real subnet.

## Section 4 — PaperSave tab

These all use standard Epson `GS ( E`. No firmware confirmation
print, but the **right side of the next print** changes appearance
when these are non-default.

| # | Command | What to verify | Pass? |
|---|---|---|---|
| 4.1 | `./rongta_config.py papersave --delete-top enable` | Send any test print (e.g. `echo hello \| ./rongta_config.py print`); whitespace at top of receipt should be trimmed compared to default | |
| 4.2 | `./rongta_config.py papersave --cut-line-interval 75%` | Test print should have ~75%-reduced line interval visible-on-paper | |
| 4.3 | **RESTORE:** `./rongta_config.py papersave` (all defaults) | Test print returns to normal spacing | |

PaperSave doesn't show up explicitly on the self-test report on
firmware GD307_V1.14, so the comparison is visual on a real print.

## Section 5 — BlackMark tab

Only meaningful if your paper roll has black registration marks
printed on the back. If your roll is plain receipt paper, just verify
the bytes go through (no crash, no permission error) but expect no
visible difference.

| # | Command | What to verify | Pass? |
|---|---|---|---|
| 5.1 | `./rongta_config.py blackmark enable` | No error. If you have black-mark paper: printer should now align cuts to marks. | |
| 5.2 | `./rongta_config.py blackmark length 100` | No error. | |
| 5.3 | `./rongta_config.py blackmark width 10` | No error. | |
| 5.4 | **RESTORE:** `./rongta_config.py blackmark disable` | No error. Self-test should show `BMMode: No`. | |

## Section 6 — Other1 tab

| # | Command | What to verify | Pass? |
|---|---|---|---|
| 6.1 | `./rongta_config.py other1 chinese enable` | Self-test shows `Chinese: Yes` | |
| 6.2 | `./rongta_config.py other1 chinese disable` | Self-test shows `Chinese: No` | |
| 6.3 | `./rongta_config.py other1 volume loud` | Next buzzer command (e.g. via a cut) sounds louder | |
| 6.4 | `./rongta_config.py other1 alarm-beep open` then `alarm-beep close` | No error. Behavior visible only on actual fault. | |
| 6.5 | `./rongta_config.py other1 print-width 58mm` | Firmware echoes "Print Width: 58mm". **Print width** of subsequent prints actually narrows. | |
| 6.6 | **RESTORE:** `./rongta_config.py other1 print-width 80mm` | Print width returns to 80mm | |

⚠️ **DO NOT TEST** `other1 usb-mode virtual-serial` in this checklist
— it makes the printer re-enumerate as `/dev/ttyACM*` and breaks the
udev rule. If you want to test it, do so deliberately, knowing
you'll need to restore via the alternate device path.

## Section 7 — Print rendering

| # | Command | What to verify | Pass? |
|---|---|---|---|
| 7.1 | `echo -e 'milk\neggs\nbread' \| ./rongta_config.py print --title 'Smoke Test'` | Prints a clean 3-line list with title, timestamp, and auto-cut | |
| 7.2 | `./rongta_config.py print --no-cut --dry-run <<< "test"` | Prints bytes to stdout, ends without `1d 56 00` | |

## Section 8 — Cleanup and final verification

| # | Action | Pass? |
|---|---|---|
| 8.1 | Run `./rongta_config.py base --cutter on` (or your baseline) | |
| 8.2 | Trigger a self-test | |
| 8.3 | Compare self-test to Section 1 baseline — every field matches | |

If 8.3 fails, walk back through the checklist; the field that
doesn't match is probably one you didn't restore.

## Report your run

Once complete, drop the checklist results in a comment on
[issue #1](https://github.com/bryanwintermute/unspooled/issues/1).
Include:

- Date + your firmware version (e.g. `GD307_V1.14 23-09-20`)
- Printer model
- Any rows that failed, with the actual vs expected
- Total paper consumed (helps next reader budget)

## Why this is a checklist, not a script

The end-to-end "did the bytes do the right thing" verification
fundamentally requires reading paper. Some fields (Cutter, DHCP,
MAC) have a firmware-driven inline confirmation print or appear on
the self-test report. Some (PaperSave, BlackMark cut rates,
density) are only visually verifiable. Some (USB mode, alarm light)
have behaviour only observable on an actual fault.

Automating this is [a long-term goal tracked in #1](https://github.com/bryanwintermute/unspooled/issues/1)
— but it's a chunky project (self-hosted runner + camera + OCR
pipeline + paper budget), so for now: humans, paper, eyes.
