#!/usr/bin/env python3
"""Generate QR pairing payload for Rabbit R1 <-> Hermes bridge.

Reads RABBIT_R1_TOKEN and RABBIT_R1_PORT from ~/.hermes/.env, detects LAN IPs,
and renders QR to terminal plus a PNG file for easy scanning.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import qrcode


def load_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def detect_lan_ips():
    out = subprocess.check_output(["ip", "-4", "-o", "addr"], text=True)
    ips = []
    for line in out.splitlines():
        m = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)", line)
        if not m:
            continue
        ip = m.group(1)
        if ip.startswith("127.") or ip.startswith("169.254.") or ip.startswith("172.17."):
            continue
        ips.append(ip)
    if not ips:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
        finally:
            s.close()
    return ips


def main():
    env_path = Path.home() / ".hermes" / ".env"
    env = load_env(env_path)
    token = env.get("RABBIT_R1_TOKEN") or os.environ.get("RABBIT_R1_TOKEN")
    if not token:
        print("ERROR: RABBIT_R1_TOKEN not set in ~/.hermes/.env", file=sys.stderr)
        return 1
    port = int(env.get("RABBIT_R1_PORT") or os.environ.get("RABBIT_R1_PORT") or 18789)

    ips = detect_lan_ips()
    if not ips:
        print("ERROR: no LAN IP detected", file=sys.stderr)
        return 1

    payload = {
        "type": "clawdbot-gateway",
        "version": 1,
        "ips": ips,
        "port": port,
        "token": token,
        "protocol": "ws",
    }
    payload_json = json.dumps(payload, separators=(",", ":"))

    print("=== Rabbit R1 pairing payload ===")
    print("IPs       :", ips)
    print("Port      :", port)
    print("Token     :", token[:8] + "..." + token[-4:], "(len=" + str(len(token)) + ")")
    print("Payload   :", len(payload_json), "bytes")
    print()

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )
    qr.add_data(payload_json)
    qr.make(fit=True)

    print("=== QR (scan with R1: swipe left -> click to scan) ===")
    qr.print_ascii(invert=True)

    png_path = Path.home() / ".hermes" / "r1-pair.png"
    img = qr.make_image(fill_color="black", back_color="white")
    with open(png_path, "wb") as fh:
        img.save(fh)
    print("\nSaved PNG:", png_path)

    print("\n=== Connection URLs (for debugging) ===")
    for ip in ips:
        print("  ws://" + ip + ":" + str(port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
