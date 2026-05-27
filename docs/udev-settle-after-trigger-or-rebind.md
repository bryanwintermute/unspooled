# udev rule looks broken — `ls` ran before `udevadm settle`

**Date learned:** 2026-05-23
**Context:** Installing a udev rule on the `<printer-host>` Pi to pin the
Rongta RP332 receipt printer to `/dev/rongta-receipt` and grant the
`plugdev` group write access, so we don't need `sudo` for every print.

The rule itself:

```udev
SUBSYSTEM=="usbmisc", KERNEL=="lp[0-9]*", \
  ATTRS{idVendor}=="0fe6", ATTRS{idProduct}=="811e", \
  MODE="0660", GROUP="plugdev", SYMLINK+="rongta-receipt"
```

After the install + reload, every immediate check looked like the
rule did nothing:

```text
$ sudo install -m 0644 99-rongta-receipt.rules /etc/udev/rules.d/
$ sudo udevadm control --reload-rules
$ sudo udevadm trigger --action=change /sys/class/usbmisc/lp0
$ ls -la /dev/usb/lp0 /dev/rongta-receipt
ls: cannot access '/dev/rongta-receipt': No such file or directory
crw-rw---- 1 root lp 180, 0 May 23 18:48 /dev/usb/lp0
```

No symlink. Group still `lp`, not `plugdev`. Looks like a rule bug.

Tried `unbind`/`bind` via sysfs — same result, even worse:

```text
$ sudo sh -c 'echo 1-1.3 > /sys/bus/usb/drivers/usb/unbind && \
              sleep 1 && \
              echo 1-1.3 > /sys/bus/usb/drivers/usb/bind'
$ ls -la /dev/usb/lp0 /dev/rongta-receipt
ls: cannot access '/dev/rongta-receipt': No such file or directory
crw------- 1 root root 180, 0 May 23 19:12 /dev/usb/lp0
```

Even the `0660 plugdev` from the *default* `lp0` (which the kernel
would have set up cleanly on its own) is gone — `root:root 0600`,
the bare kernel-default with no userland processing.

## What's actually happening

`udevadm trigger` and USB unbind/bind both fire kernel `uevent`s
asynchronously. udev (the userland daemon) receives them on a netlink
socket, matches rules, and applies properties. **`ls` runs in a
separate process and doesn't wait for udev to finish.** What you see
is the device file as the kernel created it before udev got around
to processing the event.

The race window is short — milliseconds to ~100ms — but a fast shell
beats it every time. The footgun:

- Symptom looks exactly like a broken rule (no symlink, kernel-default
  permissions).
- `udevadm test` shows the rule *would* match and emit `DEVLINKS=…`,
  which makes you suspect even harder that something between rule
  evaluation and rule application is broken. Nothing is broken; you
  just observed too soon.

## The fix: `udevadm settle`

`udevadm settle` blocks until the udev queue is empty. Always run it
between "thing that triggers a uevent" and "thing that inspects the
result":

```bash
sudo udevadm trigger --action=change /sys/class/usbmisc/lp0
sudo udevadm settle
ls -la /dev/usb/lp0 /dev/rongta-receipt
# lrwxrwxrwx 1 root root         7 May 23 19:14 /dev/rongta-receipt -> usb/lp0
# crw-rw---- 1 root plugdev 180, 0 May 23 19:14 /dev/usb/lp0
```

Same applies to unbind/bind via sysfs:

```bash
sudo sh -c 'echo 1-1.3 > /sys/bus/usb/drivers/usb/unbind && \
            echo 1-1.3 > /sys/bus/usb/drivers/usb/bind' && \
sudo udevadm settle && \
ls -la /dev/rongta-receipt
```

And to plug events. After physically replugging a USB device, the
correct ritual is "settle, then check" — not "check immediately,
panic, replug again".

## Diagnostic ladder when a udev rule seems not to apply

1. **Did the rule load?**
   `udevadm control --reload-rules` after installing. Filenames
   without an extension or with a dot-prefix are skipped by udev's
   loader (apt config has the same trap — see
   `proxmox-nag-survives-upgrades-via-apt-hook.md`).

2. **Would the rule match this device, in principle?**
   `sudo udevadm test --action=add /sys/class/usbmisc/lp0 2>&1 | grep -iE 'rule|DEVLINKS|GROUP|MODE'`.
   Reads the rules file, walks the device's parent chain, and prints
   what the resolved properties *would* be. Doesn't touch /dev. The
   single highest-signal check.

3. **Did it actually apply?**
   Trigger or replug, then `udevadm settle`, then `ls`. Skip the
   settle and step 3 will lie to you about steps 1 and 2.

4. **Match form pitfall:** `SUBSYSTEM==` (singular) matches the
   device itself. `ATTRS{}=` (plural) walks the parent chain. Rules
   that mix levels need both. For `/dev/usb/lp0`, the device is at
   subsystem `usbmisc` but `idVendor` / `idProduct` live on the
   USB-device parent — hence `SUBSYSTEM=="usbmisc"` paired with
   `ATTRS{idVendor}==`/`ATTRS{idProduct}==`.

5. **Group membership lag:** Adding the user to a new group requires
   a new login session — `id` won't show the new group until then,
   and processes started before the change won't have it. The rule's
   `GROUP=` doesn't help if the user isn't actually in the group at
   process-credential time.

## Why it's specifically a footgun

The race is invisible in scripted dev work because you read output
between commands. It bites hardest in:

- **Interactive debugging**, where you type `ls` immediately after
  `trigger`. Your shell is the source of the race.
- **Ansible / automation pipelines** that trigger + verify in the
  same task. Without an explicit `udevadm settle`, the verify step
  passes (file exists) or fails (symlink missing) non-deterministically.
- **Test suites** that simulate plug events with `udevadm trigger`
  and then assert on the resulting state. Flaky unless settle is
  enforced.

The cure is one extra line. The disease is hours of staring at a
rule that already works.

## See also

- `README.md` — the in-production rule and
  install procedure that uses this settle pattern.
- `escpos-thermal-printers-need-no-cups-driver.md` — sibling lesson
  from the same Rongta debugging session: why the udev path even
  applies here (skipping CUPS for receipt printers means writing
  raw bytes to `/dev/usb/lpN`, which is exactly where rules like
  this live).
- `udev-systemd-mount-template-pattern.md` — same general territory
  (udev-driven host integration), different domain (USB-storage
  auto-mount). Also lives or dies on understanding udev's async
  contract.
