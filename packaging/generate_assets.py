#!/usr/bin/env python3
"""Generate native installer icons and Windows version metadata."""

from __future__ import annotations

import argparse
from pathlib import Path
import re

from PIL import Image, ImageDraw


PRODUCT_NAME = "WiFi Agent"
PUBLISHER = "Akshaj Tiwari"
PROJECT_URL = "https://github.com/akshajtiwari/Wifi-Agent"


def normalized_version(value: str) -> tuple[str, tuple[int, int, int, int]]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        raise ValueError("Version must contain three numeric components, for example 1.2.0.")
    release = tuple(int(part) for part in match.groups())
    parts = (*release, 0)
    if any(part > 65535 for part in parts):
        raise ValueError("Each version component must be between 0 and 65535.")
    display = ".".join(str(part) for part in release)
    return display, parts


def app_icon(size: int = 1024) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    scale = size / 1024

    def box(values: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        return tuple(round(value * scale) for value in values)  # type: ignore[return-value]

    draw.rounded_rectangle(box((62, 62, 962, 962)), radius=round(218 * scale), fill=(24, 105, 218, 255))
    draw.arc(box((216, 220, 808, 782)), 215, 325, fill="white", width=round(82 * scale))
    draw.arc(box((330, 350, 694, 716)), 215, 325, fill="white", width=round(82 * scale))
    draw.ellipse(box((470, 652, 554, 736)), fill="white")
    return image


def windows_version_file(version: str, components: tuple[int, int, int, int]) -> str:
    numeric = ", ".join(str(part) for part in components)
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({numeric}),
    prodvers=({numeric}),
    mask=0x3F,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', '{PUBLISHER}'),
          StringStruct('FileDescription', '{PRODUCT_NAME}'),
          StringStruct('FileVersion', '{version}'),
          StringStruct('InternalName', 'WiFiAgent'),
          StringStruct('LegalCopyright', 'Copyright (c) {PUBLISHER}'),
          StringStruct('OriginalFilename', 'WiFiAgent.exe'),
          StringStruct('ProductName', '{PRODUCT_NAME}'),
          StringStruct('ProductVersion', '{version}'),
          StringStruct('Comments', '{PROJECT_URL}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    version, components = normalized_version(args.version)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = app_icon()
    source.save(
        args.output_dir / "wifi-agent.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    source.save(args.output_dir / "wifi-agent.icns", format="ICNS")
    (args.output_dir / "windows-version-info.txt").write_text(
        windows_version_file(version, components),
        encoding="utf-8",
    )
    (args.output_dir / "wifi_agent_build.py").write_text(
        f'"""Generated build metadata; do not edit."""\n\nBUILD_VERSION = "{version}"\n',
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
