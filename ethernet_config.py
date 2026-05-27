#!/usr/bin/env python3
"""Configure Ethernet on the Rongta RP332 receipt printer.

Reverse-engineered from PrinterTool.exe v2.63.0's Ethernet tab via the same
Wine + logging-CUPS-backend technique as `nv_config.py`. See
`docs/wine-cups-backend-recovers-nv-bytes.md` for the recovery
methodology.

Five distinct Rongta-vendor commands recovered:

    1f 62 44 <b>          DHCP on/off       (b: 1=enable, 0=disable)
    1f 69 <a> <b> <c> <d> set IP            (4 bytes, big-endian dotted quad)
    1f 25 00 <a> <b> <c> <d>  set subnet mask
    1f 25 01 <a> <b> <c> <d>  set gateway
    1f 6d <6 bytes>       set MAC           (Ethernet ID, big-endian 6-byte address)
    1f 70 <speed> <duplex> <auto>  set link mode (1/1/1 = 100Mbps full auto)

Setting an IP via Set is shown as 3 concatenated sub-commands (IP + submask +
gateway). The vendor tool also exposes "Set2" which uses a single command
`1f 4e <IP><GW><SUB>` (note: IP/GW/SUB order) that does the same thing in
14 bytes instead of 20. MAC-Set is the 5th button on the Ethernet tab and
has been verified by a round-trip: set fake MAC '12:34:56:78:9a:bc', read
the self-test (showed exactly those bytes), then restore the factory MAC.

WARNING: these writes are persistent (NV-RAM). Writing wrong IP / subnet /
gateway values can leave the printer unreachable on the LAN. Recovery
requires either physical USB access (this tool) or a temporary IP that
matches whatever subnet the printer thinks it's on.

The most useful single command for fresh-out-of-the-box RP332s is:

    python3 ethernet_config.py --dhcp on

which flips DHCP on so the printer can be reached via DHCP-assigned IP
without any further static config.
"""
from __future__ import annotations

import argparse
import ipaddress
import sys
from pathlib import Path

DEFAULT_DEVICE = "/dev/rongta-receipt"


def _ip_to_bytes(addr: str) -> bytes:
    v4 = ipaddress.IPv4Address(addr)
    return v4.packed  # big-endian dotted quad


def build_dhcp(enable: bool) -> bytes:
    return bytes([0x1F, 0x62, 0x44, 0x01 if enable else 0x00])


def build_set_ip(ip: str) -> bytes:
    return bytes([0x1F, 0x69]) + _ip_to_bytes(ip)


def build_set_submask(mask: str) -> bytes:
    return bytes([0x1F, 0x25, 0x00]) + _ip_to_bytes(mask)


def build_set_gateway(gw: str) -> bytes:
    return bytes([0x1F, 0x25, 0x01]) + _ip_to_bytes(gw)


def build_set_static(ip: str, mask: str, gw: str) -> bytes:
    """Compose the same 3-command sequence the GUI's 'Set' button emits."""
    return build_set_ip(ip) + build_set_submask(mask) + build_set_gateway(gw)


def build_set_static_2(ip: str, mask: str, gw: str) -> bytes:
    """The GUI's 'Set2' button: a single 1f 4e command packing IP+GW+SUB.

    NOTE the order: IP, then GATEWAY, then SUBNET. Different from the
    natural-looking IP/SUB/GW order. Don't ask me why.
    """
    return bytes([0x1F, 0x4E]) + _ip_to_bytes(ip) + _ip_to_bytes(gw) + _ip_to_bytes(mask)


def _mac_to_bytes(mac: str) -> bytes:
    """Parse 'aa:bb:cc:dd:ee:ff' or 'aa-bb-cc-dd-ee-ff' to 6 raw bytes."""
    parts = mac.replace("-", ":").split(":")
    if len(parts) != 6:
        raise ValueError(f"MAC must have 6 octets, got {mac!r}")
    return bytes(int(p, 16) for p in parts)


def build_set_mac(mac: str) -> bytes:
    """Set the printer's Ethernet ID (MAC address).

    WARNING: this is persistent. Note the original MAC before changing,
    so you can restore it if something goes wrong. The self-test report
    shows it on the 'Ethernet ID' line.
    """
    return bytes([0x1F, 0x6D]) + _mac_to_bytes(mac)


def build_set_duplex(speed: str, duplex: str, auto: bool) -> bytes:
    """Set link duplex / speed.

    speed:   '10' or '100'  (10mbps or 100mbps)
    duplex:  'half' or 'full'
    auto:    True = auto-negotiate, False = force.

    Our reverse-engineered observation: the tool's default selection of
    '100Mbps Full Duplex' emits `1f 70 01 01 01`. We haven't yet captured
    other dropdown values so the byte mapping below is best-guess based
    on the pattern.
    """
    s = 0x01 if speed == "100" else 0x00
    d = 0x01 if duplex == "full" else 0x00
    a = 0x01 if auto else 0x00
    return bytes([0x1F, 0x70, s, d, a])


def write_bytes(dev: Path, data: bytes) -> None:
    with dev.open("wb", buffering=0) as f:
        f.write(data)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    sp_dhcp = sub.add_parser("dhcp", help="Enable / disable DHCP.")
    sp_dhcp.add_argument("state", choices=["on", "off"])

    sp_static = sub.add_parser(
        "static",
        help="Set a static IP (also configures submask + gateway).",
    )
    sp_static.add_argument("--ip", required=True, help="e.g. 10.20.0.42")
    sp_static.add_argument("--mask", default="255.255.255.0")
    sp_static.add_argument("--gateway", required=True, help="e.g. 10.20.0.1")
    sp_static.add_argument(
        "--mode",
        choices=["set", "set2"],
        default="set",
        help="Two equivalent commands exist; default 'set' matches the GUI's main button.",
    )

    sp_duplex = sub.add_parser("duplex", help="Set link mode.")
    sp_duplex.add_argument("--speed", choices=["10", "100"], default="100")
    sp_duplex.add_argument("--duplex", choices=["half", "full"], default="full")
    sp_duplex.add_argument("--auto", action="store_true", default=True)

    sp_mac = sub.add_parser(
        "mac",
        help="Set the printer's MAC address (Ethernet ID).",
    )
    sp_mac.add_argument(
        "address",
        help=(
            "MAC address, e.g. 'a8:01:57:3b:ca:60' or 'a8-01-57-3b-ca-60'. "
            "Note the original before changing — restoring requires knowing it."
        ),
    )

    sp_raw = sub.add_parser(
        "raw",
        help="Write arbitrary hex bytes (for testing recovered protocols).",
    )
    sp_raw.add_argument("hex_bytes", help="e.g. '1f624401'")

    for sp in (sp_dhcp, sp_static, sp_duplex, sp_mac, sp_raw):
        sp.add_argument("--device", default=DEFAULT_DEVICE)
        sp.add_argument(
            "--dry-run",
            action="store_true",
            help="Print bytes that would be written, don't actually write.",
        )

    args = p.parse_args(argv)

    if args.cmd == "dhcp":
        data = build_dhcp(args.state == "on")
    elif args.cmd == "static":
        if args.mode == "set":
            data = build_set_static(args.ip, args.mask, args.gateway)
        else:
            data = build_set_static_2(args.ip, args.mask, args.gateway)
    elif args.cmd == "duplex":
        data = build_set_duplex(args.speed, args.duplex, args.auto)
    elif args.cmd == "mac":
        data = build_set_mac(args.address)
    elif args.cmd == "raw":
        data = bytes.fromhex(args.hex_bytes.replace(" ", "").replace(":", ""))
    else:
        p.error("unknown subcommand")

    if args.dry_run:
        print(data.hex(" "))
        return 0

    dev = Path(args.device)
    try:
        write_bytes(dev, data)
    except PermissionError:
        print(
            f"error: cannot write to {dev} (not in 'plugdev' group?).",
            file=sys.stderr,
        )
        return 2
    except FileNotFoundError:
        print(
            f"error: {dev} not present. Is the printer plugged in?",
            file=sys.stderr,
        )
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
