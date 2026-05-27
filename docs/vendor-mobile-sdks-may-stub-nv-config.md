# Vendor mobile SDKs may stub NV-config APIs — disassemble to verify

**When you're reverse-engineering a proprietary device protocol
from a vendor's published mobile SDK, the presence of a method in
the public header does NOT imply that method is implemented.**
Vendors routinely scaffold an API surface they intend to fill in
later, then ship the SDK with the implementation as a one-line
stub that returns `nil` / `null` / empty.

If the function you need is the *only* exposed entry point for
the feature you're trying to characterise (e.g. cutter-enable,
buzzer-enable, code-page-default — features stored in non-volatile
printer memory), and the public mobile SDK's documentation says
that function exists, **disassemble the static lib to verify it's
real**. The header lies, the symbol table doesn't.

## Concrete case (Rongta RP332, 2025)

Trying to derive the cutter-enable NV-flag command for a
Rongta RP332 thermal receipt printer without using Rongta's
Windows-only config tool. Path: find an open-source SDK, locate
the NV-config write method, extract its byte template.

**Sources explored:**

| Source | What it had | What it didn't |
|---|---|---|
| `cyb3rjerry/rongta-escpos` (Go) | runtime ESC/POS for RP325/6/7/8 | no NV-config |
| `Malik12tree/capacitor-thermal-printer` iOS vendored SDK | full `Cmd.h` headers, declares `getRestoreFactoryCmd` etc | impl is in closed `.a` |
| Windows `PrinterTool.exe` + `.po` localisation | resource IDs (`PO_IDC_CHECK_BASE_CUTTER`), source-path leak (`O:\code\RongtaPrinter\RongtaPrinterTool`) | no readable byte sequences in the C++ binary |
| `MarkZoneTech/EPOS-SDK-Android` | full Android SDK jar v2.0.42 (2020), parseable bytecode | NV-config methods didn't exist yet in 2020 |
| `MarkZoneTech/EPO-SDK-IOS` | iOS SDK v4.10.17 (newest), full `libRTPrinterSDK.a` arm64 | see below |

**The smoking gun:**

The header `Cmd.h` in v4.10.17 declares `GetCutPaperCmd:`,
`GetBeepCmd:interval:`, `GetCommonSetCmd:` and friends. The
Mach-O object file `ESCCmd.o` (extracted from
`libRTPrinterSDK.a` arm64 slice) contains all those symbols.
Disassembling each with capstone showed:

```text
-[ESCCmd GetCutPaperCmd:]                  136 bytes  — real, dispatches on CutterMode
-[ESCCmd GetBeepCmd:interval:]              68 bytes  — real, emits 1B 42 level interval
-[ESCCmd GetOpenDrawerCmd:startTime:...]    72 bytes  — real, emits 1B 70 pin start end
-[ESCCmd GetHeaderCmd]                      60 bytes  — real, emits 1B 40 (ESC @ init)
-[ESCCmd GetCommonSetCmd:]                   8 bytes  — STUB: `mov x0, #0; ret`
```

`GetCommonSetCmd:` — the function whose name and parameter
(`CommonSetting *`) strongly suggested it was the NV-config
writer — is **8 bytes of arm64 that returns nil**. The vendor
scaffolded the API, shipped the SDK, and never wrote the
implementation in. The NV-config bytes simply do not exist
anywhere in the published mobile SDKs. They live exclusively
in the closed Windows config tool's binary.

## The pattern

This is consistent with the way many hardware vendors organise
their SDK surface area:

- **Mobile / app-developer SDK**: runtime control only —
  formatting, cutting, beeping, image printing. The things an
  app shows the user.
- **Windows / Linux config utility**: NV / firmware
  configuration — one-time setup the customer does once on
  install. The vendor's profit centre is not "be easy for
  developers", it's "your hardware fleet has to ride this
  one-time-setup path that we control".

Stubbed-out NV-config methods in the mobile SDK are the bridge
between "we documented it for developers" and "the bytes live
elsewhere". The headers are aspirational. The .a is reality.

## How to detect it

```bash
# Universal binary → extract one slice
python3 - <<'PY' >/tmp/slice.a
import struct
data = open('libRTPrinterSDK.a','rb').read()
magic, nfat = struct.unpack('>II', data[:8])
assert magic == 0xcafebabe
for i in range(nfat):
    e = 8 + i*20
    cpu, sub, off, size, _ = struct.unpack('>iiIII', data[e:e+20])
    if cpu == 0x0100000c:  # CPU_TYPE_ARM64
        import sys; sys.stdout.buffer.write(data[off:off+size])
        break
PY

ar x /tmp/slice.a ESCCmd.o   # or whatever .o has your target method

# Pull the function bytes out and feed to capstone:
python3 -c "
from capstone import *
import struct
data = open('ESCCmd.o','rb').read()
# ... parse Mach-O LC_SEGMENT_64 to find __TEXT,__text bounds and
# the n_value of the '-[ClassName MethodName:]' symbol, slice, disassemble.
"
```

The dead-giveaway pattern for a stub is **5 lines or fewer of
arm64 ending in `mov x0, #0; ret`** (or on x86_64, `xor eax,
eax; ret`). Real implementations of "build a command buffer"
methods on Objective-C are typically 50–200+ bytes:
prologue → buffer alloc → byte stores → ImportBytes:len: call
→ epilogue.

`-[ESCCmd GetCutPaperCmd:]` for the half/full cut switch was
136 bytes and emitted exactly `1B 6D` or `1B 69` — exactly the
bytes the older Android jar (parsed via constant pool +
bytecode walk) said it would. The two sources cross-confirm
each other. When `GetCommonSetCmd:` came out at 8 bytes, that
was conclusive.

## Why this matters operationally

It tells you to **stop hunting for the bytes in the wrong
place** and accept that the only derivation paths are:

1. **USB packet capture** of the Windows tool in action
   (Wine + `usbmon` on Linux, or a Windows VM with USBPcap).
   Definitive but multi-step.
2. **Wire-level proprietary protocol RE** of the Windows tool
   itself (Ghidra / IDA). Same scale of effort.
3. **Just run the Windows tool once.** Pragmatic.

Don't burn another two evenings trying to find the bytes in
some sibling repo, some newer jar, some forum post. The vendor
deliberately keeps them out of public sources.

## Companion

This lesson came out of the Rongta RP332 cutter-enable
investigation; see `escpos-thermal-printers-need-no-cups-driver.md`
for the broader pattern (driver-free ESC/POS printing) and the
`` directory for the working CLI that
came out of the project.

## Tooling notes

On Debian 12 with no passwordless sudo and PEP-668 lockdown,
the capstone install path that works:

```bash
python3 -m venv --without-pip /tmp/cap-venv
curl -sSLO https://bootstrap.pypa.io/get-pip.py
/tmp/cap-venv/bin/python3 get-pip.py --quiet
/tmp/cap-venv/bin/pip install --quiet capstone
/tmp/cap-venv/bin/python3 my-disasm.py
```

GNU `objdump` (Debian binutils 2.40) does **not** read Mach-O —
it returns `file format not recognized`. Capstone + a hand-
rolled Mach-O parser is the lowest-friction path on Linux
when `llvm-objdump` isn't installed and you can't sudo.

## See also

- `escpos-thermal-printers-need-no-cups-driver.md` — the parent
  lesson on driver-free ESC/POS, includes the NV-flag footgun.
- `wine-cups-backend-recovers-nv-bytes.md` — the **follow-on**:
  the bytes we couldn't find in the mobile SDKs were recovered
  by running PrinterTool.exe under Wine on a separate x86_64 box
  (with the printer USB-IP-exported from the Pi over LAN) and
  logging every CUPS spool job to disk via a custom backend.
  17 bytes, four clicks, complete bit-mapping in 30 seconds. The
  resulting CLI ships as `nv_config.py`.
- `safe-replay-tool-pattern.md` — for the inverse case where
  you DO have full vendor API access and want to mirror state.
