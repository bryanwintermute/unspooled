# Recovering vendor NV-write byte protocols via Wine + CUPS-backend logging

**When the bytes you need live ONLY inside a closed-source Windows
config tool, and the device is on a Pi you can't run Windows on, the
right move is not USB packet capture — it's a logging CUPS backend.**

usbmon works, but you spend more time debugging tshark filters,
"phantom" enumeration traffic, and timing windows than you do reading
bytes. A CUPS backend that just `tee`s every job to disk gives you a
perfect, byte-precise, per-click log file with zero noise — no
descriptor reads, no control transfers, no decode-from-pcap pain.

## The setup that actually worked (RP332, dev-box, 2026-05)

```
Octoprint (Raspberry Pi, armv7)
  ├── Rongta RP332 printer on USB
  ├── usbipd -D                    ← exports the printer over TCP 3240
  └── usbip bind -b 1-1.3

dev-box (Debian 12 QEMU VM, x86_64)
  ├── modprobe vhci-hcd; usbip attach -r octoprint -b 1-1.3
  ├── usblp claims /dev/usb/lp0
  ├── udev rule pins /dev/rongta-receipt symlink, group=plugdev
  ├── CUPS  raw queue 'rongta-raw'  →  custom backend  →  /dev/rongta-receipt
  ├── Wine 8.0 (32-bit prefix) running PrinterTool.exe v2.63.0
  ├── Xvfb :99
  └── x11vnc on 0.0.0.0:5900  ← phone VNCs in for the actual clicks
```

`PrinterTool.exe` opens its CreateFileW/WriteFile path through Wine's
winspool → CUPS → the custom backend → printer. usbip-over-LAN means we
never had to move the cable, and usbmon on the dev-box vhci_hcd bus would
have worked too, but we never had to use it once the backend logging was
in place.

## The custom CUPS backend

```bash
#!/bin/bash
# /usr/lib/cups/backend/rongta  (chmod 0700 — see below)
set -e
DEVICE=/dev/rongta-receipt
LOGDIR=/tmp/rongta-writes
mkdir -p "$LOGDIR"
chmod 0777 "$LOGDIR"

# CUPS calls the backend with no args during enumeration ("here's what
# this backend can talk to"); answer with a single device line.
if [ $# -eq 0 ]; then
  echo 'direct rongta "Unknown" "Rongta RP332 Receipt Printer"'
  exit 0
fi

# Normal call: write to device AND keep a copy.
TS=$(date +%Y%m%d-%H%M%S-%N)
LOG="$LOGDIR/${TS}.bin"
if [ $# -eq 6 ]; then
  tee "$LOG" < "$6" > "$DEVICE"
else
  tee "$LOG" > "$DEVICE"
fi
chmod 0644 "$LOG"
exit 0
```

Attach it as:

```bash
lpadmin -p rongta-raw -E -v 'rongta:/dev/rongta-receipt' -m raw
```

Each click on a "Save" / "Set" button in the Windows tool produces
one new file in `/tmp/rongta-writes/`, named by nanosecond timestamp.
Diffing four files gave us the complete bit-mapping of the Rongta
"Base tab" NV write in about 30 seconds.

## Footguns we hit

### 1. CUPS backend file mode controls who runs it

CUPS runs backends as the `lp` user *unless* the backend's file is
mode `0700`. With `0755`, our `cat > /dev/rongta-receipt` got
`Permission denied` (lp isn't in `plugdev`) and the job sat in the
queue forever as "completed-with-no-output". **Use mode 0700 if you
need the backend to write to a device root owns.**

```bash
chmod 0700 /usr/lib/cups/backend/rongta   # runs as root
chmod 0755 /usr/lib/cups/backend/rongta   # runs as 'lp'  (default User)
```

### 2. CUPS's stock `file://` backend doesn't write to char devices

We started with `lpadmin -v file:/dev/rongta-receipt`. CUPS happily
accepted jobs, reported them completed, and showed correct byte counts
— but nothing reached the printer. The file backend opens with
`O_WRONLY|O_CREAT|O_TRUNC` semantics that don't work for character
devices. Symptom is silent: the print queue looks fine and there's no
error in `error_log`. **Don't use `file://` for `/dev/*` devices —
write a custom backend.**

### 3. Wine's USB SetupAPI path is greyed out

`PrinterTool.exe`'s connection dialog offers USB / COM / Printer Driver.
The USB option uses `SetupDiGetClassDevsW` to enumerate
`\\?\USB#VID_XXXX&PID_XXXX#...` device interface paths, which Wine
doesn't reproduce faithfully. The radio is greyed out before you can
click. **Use the "Printer Driver" path** — the tool will talk through
WINSPOOL.DRV → Wine's CUPS bridge → our logging backend.

### 4. The COM / serial path also fails

Mapping `$WINEPREFIX/dosdevices/com1` to `/dev/rongta-receipt` lets you
*select* COM1 in the tool, but the tool then calls `GetCommState` /
`SetCommState` on the device. Those fail on `/dev/usb/lp0` (not a TTY)
and the tool refuses to send a single byte. ("You need Configure com
port first.")

### 5. tshark on usbmon misdetects printer-class bulk-OUT as IPP-USB

For short payloads (2-4 bytes), tshark's IPPUSB dissector swallows the
data field with a "Malformed Packet" error and won't show the bytes in
the `usb.capdata` column. Workaround: dump the raw frame with
`tshark -x` and read the bytes at the end of the hex dump (after the
URB header). Or just use a logging CUPS backend and skip the pcap path.

### 6. The "phantom" 12 control transfers when usbmon opens

The first 12 frames of every usbmon-on-vhci_hcd capture are control
transfers reading the printer's USB descriptors. They happen even
when no application is talking to the printer. They're some
udev/usblp poll triggered by debugfs activation. Skip them — they're
not part of any application's write.

### 7. Timed capture windows are too easy to miss

When you tell a human "click within 60 seconds", they will click at
second 75 every single time. Either use an open-ended capture
(`tshark` Ctrl-C'd manually) or — better — switch to the logging-
backend approach, which has no timing window at all.

## The bytes (for the Rongta RP332's "Base" tab)

Documented in detail in `nv_config.py`. The
17-byte sequence is three concatenated `1F xx <args>` Rongta-vendor
commands:

```
1f 73 02 <c3> <c4> <c5> <c6> <c7> <c8> <c9> <c10>   # set NV block 2
1f 72 <c13>                                         # set auto-reprint
1f 74 <c16>                                         # set buzzer-after-print
```

Cutter/Buzzer/Drawer are **inverted booleans** (`0=on, 1=off`) — every
other boolean is normal. Numeric settings (char/line, density, code
page, font) are direct values. Position 9 has no observable effect at
value 1 — left as 0 by default.

## Follow-on: driving the GUI from terminal via xdotool

Once the logging-backend capture loop is in place, the next bottleneck
is human click latency. For a tab with many distinct "Set" buttons
(the RP332's Ethernet tab has 5: IP-Set, Set2, DHCP-Set, MAC-Set,
Duplex-Set) you can fully script the click + popup-dismissal +
log-archival cycle:

```bash
# tools we need on the dev host:
#   - Xvfb (headless X server)
#   - x11vnc (only for monitoring; not strictly required)
#   - xdotool (the actual driver)
#   - scrot (verify state after each click)

# Click by ABSOLUTE screen coordinates (Xvfb-without-WM doesn't honour
# xdotool's --window-relative clicks):
xdotool mousemove $x $y && xdotool click 1

# Dismiss validation popups (vendor tools love these for empty fields):
xdotool key Return    # focuses-OK-button on Wine modal dialogs

# Wait for the CUPS backend to flush, then grab the latest .bin:
sleep 0.8
f=$(ls -t /tmp/rongta-writes/*.bin | head -1)
mv "$f" "/tmp/rongta-writes-eth/01-<descriptive-label>.bin"
```

**Field-typing footgun**: MFC IPv4 address widgets accept the **period**
key to auto-advance to the next octet (`xdotool type '192.168.1.99'`
works). But MAC address widgets are 6 separate Edit controls with **no
auto-advance** — typing `'aa-bb-cc-...'` puts the `aa` in octet 1 and
the `-bb-cc-...` literal into octet 1's overflow buffer (i.e., nothing
visible happens after the first octet). For MAC, click the first box
and `xdotool key Tab` between each octet:

```bash
for octet in aa bb cc dd ee ff; do
  xdotool key ctrl+a; xdotool key Delete
  xdotool type "$octet"
  xdotool key Tab
done
```

**Always do an isolated round-trip** for destructive RE: capture
"set value to FOO" → restore "set value back to original". The
restoration confirms the byte format you derived (compare what the
self-test report says before, during, after). Worked example: MAC-Set
RE — fake `12:34:56:78:9a:bc`, verify self-test shows it, restore
factory `a8:01:57:3b:ca:60`, verify self-test restored. Both writes
were exactly `1f 6d <6 bytes>`, confirming the format.

**Watch for firmware echo prints.** The Rongta firmware
autonomously prints a small confirmation receipt for *every*
Ethernet Set command (`1f 69` IP, `1f 25 00` submask, `1f 25 01`
gateway, `1f 4e` IP+GW+SUB, `1f 6d` MAC, `1f 62 44` DHCP — Bryan
confirmed all of them). The receipt renders each byte as decimal
(e.g. `1f 6d 12 34 56 78 9a bc` prints `Curr MAC: 18 52 86 120
154 188`). This is great for verification (the printer tells you
what it now thinks the field is, no self-test needed) but also
means **destructive RE consumes paper linearly**. Budget
accordingly, and ack the confirmation prints when reading captured
logs (they aren't bytes you have to model in your CLI; the
firmware drives them). Similarly, the `1f 7b X` mode-toggle family
prints human-readable confirmations (e.g. `1f 7b 75 00` prints
"USB Mode is: Printer!").

**Beware kernel write-buffer delayed-flush after usbip detach.**
We had `/dev/rongta-receipt` go stale: usbip lost the attach,
the udev rule removed the symlink, and a subsequent shell-redirect
created a regular FILE with the same path under `root:lp` 0600
perms. Several writes by the user (now invisibly going to disk)
queued bytes there. When usbip was re-attached and the symlink
restored, the *queued* file contents weren't immediately flushed
to the new device — but as soon as a fresh write went through,
the printer caught up with concatenated bytes from the prior
"writes". The result was a confused multi-command print
("OUTOUTOUTOUT…HELLO WORLD!…USB Mode is: Printer! RESET…") that
mixed sentinels from PaperSave commands, the BlackMark Next-Black-
Mark easter egg, the USB-mode firmware echo, and the leading edge
of the Reset-button failure handler. Diagnostic: if you see
nonsense ASCII salads on the printer that don't correspond to any
single recent command, look for a stale regular-file at the symlink
path that's eating writes silently. Fix: `sudo rm /dev/<symlink> &&
sudo udevadm trigger --action=change /sys/class/usbmisc/lp0 && sudo
udevadm settle`.

**Don't assume "constant-looking" bytes are actually constant.** The
first cut of the Base-tab decode treated `1f 73 02 ...` as the
fixed command prefix "set NV block 2", because the captured bytes
ALWAYS started that way. Turned out byte[2] is the **Baud Rate index**
(0=4800, 1=9600, 2=19200 default, …) — the vendor tool just always
rewrites the current baud rate on every Set, so the captured value
"happened to be" 02. Only by deliberately changing one of the
non-checkbox controls (the Baud Rate dropdown) did the truth come
out: byte[2] flipped from 02→01 → 03 in lockstep with the dropdown
selection. Similarly byte[9], originally documented as "no effect",
turned out to be **Parity** (0=None, 1=Odd, 2=Even) — and changing
the Parity dropdown is the only way to reveal it. **Tour every
control, not just the checkboxes**; "this byte doesn't change"
usually means "I haven't yet found the control that changes it",
not "this byte is reserved".

**Some buttons just don't work.** The Base tab's "Reset" button on
this Rongta firmware sends a 13-byte structured packet
(`1b 1b 45 02 01 02 06 00 00 00 00 0c 5a`) which the firmware
replies to with "Setting Fail!" — actual state is unchanged. Don't
chase what these commands "mean" in the printer's expected
protocol; just document that they're broken in this firmware
version and move on. The CLI you've built (which can write any
known-good NV state) is itself the factory-reset.

**Static analysis can skip enumeration clicks for big dropdowns.**
The Code Page dropdown on the Rongta tool has 43 entries — clicking
each one would burn ~22 inches of paper for the firmware-echo
receipts. Instead, dump the UTF-16LE strings out of the PE's `.rdata`
section with `strings -el -t d <exe>`, filter for code-page-shaped
literals, and read them **in descending file offset order**: that
matches MSVC's bottom-up string-literal emission, which matches
the C++ source order, which matches the order the tool's
`AddString()` calls were made, which matches the dropdown order,
which matches the wire byte. **One spot-click verifies the entire
table** (we clicked CP850 = expected index 2, observed byte[8]=02 ✓).

Anti-pattern caveat: this only works for dropdowns whose backing
storage is a contiguous block of string literals. Dropdowns
populated dynamically (from registry, a config file, or runtime
discovery) need actual clicks. If you can see the strings in
`strings -el`, you can probably read off the indices.

## The pattern, generalised

When reverse-engineering a vendor's NV-write protocol:

1. **Don't start with USB capture.** Start with whatever the
   application talks to. If it's the Windows printer spooler, write
   a custom CUPS backend that tees jobs to disk. If it's a TCP
   socket, write a logging proxy. If it's a serial port, use
   `socat -d -d ... | tee`.
2. **One click = one log file.** Use nanosecond timestamps for
   filenames so two clicks within a second don't collide.
3. **Diff in chronological order.** Four files comparing
   {all-off, only-A, only-B, only-C} will tell you the byte
   positions of A/B/C in one round of clicks.
4. **Inverted booleans are common** in cheap printer firmware where
   "0" means "default minimal behaviour, no add-ons". Don't assume
   sane encodings.
5. **The "wait, that didn't change anything" byte** at the end of
   your mapping is often a reserved/future-use field. Document it
   as unknown and move on.

## See also

- [`vendor-mobile-sdks-may-stub-nv-config.md`](./vendor-mobile-sdks-may-stub-nv-config.md) —
  the lesson on why we ended up here in the first place. The mobile
  SDKs stub NV-config methods; that lesson establishes that the
  bytes can only come from the Windows tool. This lesson is how
  we extracted them.
- [`escpos-thermal-printers-need-no-cups-driver.md`](./escpos-thermal-printers-need-no-cups-driver.md) —
  the parent lesson about driver-free ESC/POS printing.
- [`safe-replay-tool-pattern.md`](./safe-replay-tool-pattern.md) —
  for the inverse case where you have full API access and want to
  mirror state.
- `nv_config.py` — the working CLI built
  from the bytes recovered here.
