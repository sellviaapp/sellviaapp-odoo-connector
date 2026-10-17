#!/usr/bin/env python3
"""Create the installable Odoo Apps ZIP with one top-level module folder."""

from __future__ import annotations

import ast
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "sellviaapp_connector"
DIST = ROOT / "dist"


def main() -> None:
    manifest = ast.literal_eval((MODULE / "__manifest__.py").read_text(encoding="utf-8"))
    version = manifest["version"]
    DIST.mkdir(exist_ok=True)
    output = DIST / f"sellviaapp_connector-{version}.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(MODULE.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            archive.write(path, Path("sellviaapp_connector") / path.relative_to(MODULE))
    if output.stat().st_size >= 50 * 1024 * 1024:
        raise SystemExit("Release ZIP exceeds the 50 MiB Odoo import limit")
    print(f"Created {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
