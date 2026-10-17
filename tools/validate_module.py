#!/usr/bin/env python3
"""Offline structural validation for the SellViaApp Odoo add-on."""

from __future__ import annotations

import ast
import csv
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "sellviaapp_connector"
MANIFEST_PATH = MODULE / "__manifest__.py"


def fail(message: str) -> None:
    raise AssertionError(message)


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) != 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        fail(f"Not a valid PNG: {path}")
    return struct.unpack(">II", data[16:24])


def load_manifest() -> dict:
    value = ast.literal_eval(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail("Manifest must contain a dictionary")
    return value


def validate_manifest(manifest: dict) -> None:
    required = {"name", "summary", "version", "category", "author", "license", "depends", "data", "support"}
    missing = sorted(required.difference(manifest))
    if missing:
        fail(f"Missing manifest fields: {', '.join(missing)}")
    if len(str(manifest["name"])) > 25:
        fail("Odoo Apps module name must not exceed 25 characters")
    if not re.fullmatch(r"17\.0\.\d+\.\d+\.\d+", str(manifest["version"])):
        fail("Version must follow the Odoo 17 five-part format")
    if manifest["license"] not in {"LGPL-3", "GPL-3", "OPL-1", "OEEL-1", "Other proprietary"}:
        fail("Unsupported manifest licence")
    if manifest.get("installable") is not True:
        fail("Module must be installable")
    if manifest.get("application") is not True:
        fail("Connector must be published as an application")
    for relative in [*manifest["data"], *manifest.get("images", [])]:
        path = MODULE / relative
        if not path.is_file():
            fail(f"Manifest references a missing file: {relative}")


def validate_python() -> None:
    for path in MODULE.rglob("*.py"):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def validate_xml() -> None:
    for path in MODULE.rglob("*.xml"):
        ET.parse(path)


def validate_csv() -> None:
    for path in MODULE.rglob("*.csv"):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if not header or "id" not in header:
                fail(f"CSV file has no Odoo id column: {path}")


def validate_marketplace_assets(manifest: dict) -> None:
    icon = MODULE / "static" / "description" / "icon.png"
    if not icon.is_file():
        fail("Missing static/description/icon.png")
    width, height = png_size(icon)
    if width != height or width < 128:
        fail("Marketplace icon must be square and at least 128 px")
    description = MODULE / "static" / "description" / "index.html"
    if not description.is_file() or description.stat().st_size < 3000:
        fail("Marketplace index.html is missing or incomplete")
    if re.search(r"<script\b|javascript:", description.read_text(encoding="utf-8"), re.I):
        fail("Marketplace description must not contain JavaScript")
    images = manifest.get("images", [])
    if len(images) < 4:
        fail("At least four marketplace images are required")
    for relative in images:
        path = MODULE / relative
        size = png_size(path)
        if size != (1600, 900):
            fail(f"Marketplace image must be 1600x900: {relative} is {size[0]}x{size[1]}")


def validate_no_packaged_secrets() -> None:
    forbidden_names = {".env", "id_rsa", "id_ed25519", "credentials.json"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.name in forbidden_names or path.suffix.lower() in {".pem", ".p12", ".pfx", ".key"}:
            fail(f"Potential secret file must not be committed: {path.relative_to(ROOT)}")
        if path.suffix.lower() not in {".py", ".js", ".xml", ".md", ".rst", ".html", ".yml", ".yaml", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        checks = [
            r"gh[pousr]_[A-Za-z0-9]{30,}",
            r"sk_(?:live|test)_[A-Za-z0-9]{20,}",
            r"AKIA[0-9A-Z]{16}",
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        ]
        for pattern in checks:
            if re.search(pattern, text):
                fail(f"Potential credential in {path.relative_to(ROOT)}")


def main() -> int:
    manifest = load_manifest()
    validate_manifest(manifest)
    validate_python()
    validate_xml()
    validate_csv()
    validate_marketplace_assets(manifest)
    validate_no_packaged_secrets()
    print(f"OK: {manifest['name']} {manifest['version']} passed repository validation")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, SyntaxError, ET.ParseError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
