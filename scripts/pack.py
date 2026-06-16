#!/usr/bin/env python3
"""Build a standalone rrs desktop bundle with PyInstaller.

Cross-platform: runs on macOS, Windows, and Linux. PyInstaller cannot
cross-compile, so run this *on the OS you want a bundle for* (a Windows .exe
must be built on Windows).

Produces dist/rrs-app/ — a onedir bundle (launcher + _internal/). It bundles:
  - rrs's own package data (schema.sql, ui/static), which PyInstaller does not
    pick up on its own, and
  - the ffmpeg / ffprobe / deno binaries currently on PATH, under _internal/bin/
    so the frozen app finds them (see config._activate_bundled_binaries).

Usage:
    python scripts/pack.py            # or: scripts/rrs-pack  (Unix wrapper)

Prereqs: pip install -e ".[dev]" pyinstaller

Distribution caveats:
  * A system ffmpeg may be *dynamically linked* (e.g. Homebrew on macOS), so a
    bundle built from it runs on your machine but can fail elsewhere. Drop a
    *static* ffmpeg/ffprobe build into _internal/bin/ before distributing.
  * macOS Gatekeeper / Windows SmartScreen will warn on an unsigned bundle.
    Sign (+ notarize on macOS) before handing it to non-technical users.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# PyInstaller's --add-data separator: ':' on POSIX, ';' on Windows.
SEP = os.pathsep
BINARIES = ("ffmpeg", "ffprobe", "deno")


def main() -> int:
    try:
        import nicegui
        import PyInstaller.__main__ as pyinstaller

        from rrs.config import BUNDLED_BIN_SUBDIR
    except ImportError as exc:
        print(
            f'error: {exc.name} not installed. Run: pip install -e ".[dev]" pyinstaller',
            file=sys.stderr,
        )
        return 1

    os.chdir(REPO)

    print("==> cleaning previous build")
    for d in ("build", "dist"):
        shutil.rmtree(REPO / d, ignore_errors=True)
    (REPO / "rrs-app.spec").unlink(missing_ok=True)

    # Replicate what nicegui-pack does (bundle the nicegui package data), but
    # via the PyInstaller API so it is shell- and OS-agnostic.
    nicegui_dir = Path(nicegui.__file__).parent
    add_data = {
        nicegui_dir: "nicegui",
        REPO / "src" / "rrs" / "store" / "schema.sql": "rrs/store",
        REPO / "src" / "rrs" / "ui" / "static": "rrs/ui/static",
    }

    print("==> running PyInstaller (onedir)")
    pyinstaller.run(
        [
            str(REPO / "src" / "rrs" / "main.py"),
            "--name=rrs-app",
            "--onedir",
            "--clean",
            "--noconfirm",
            *(f"--add-data={src}{SEP}{dest}" for src, dest in add_data.items()),
        ]
    )

    bin_dir = REPO / "dist" / "rrs-app" / "_internal" / BUNDLED_BIN_SUBDIR
    bin_dir.mkdir(parents=True, exist_ok=True)
    print(f"==> bundling native binaries into {bin_dir}")
    missing = []
    for name in BINARIES:
        src = shutil.which(name)
        if not src:
            print(f"  warning: '{name}' not on PATH — not bundled", file=sys.stderr)
            missing.append(name)
            continue
        dst = bin_dir / Path(src).name  # keeps the .exe suffix on Windows
        shutil.copy2(src, dst)
        os.chmod(dst, 0o755)  # no-op on Windows, needed on POSIX
        print(f"  + {Path(src).name}  ({src})")

    launcher = "rrs-app.exe" if os.name == "nt" else "rrs-app"
    print(f"\n==> done: dist/rrs-app/{launcher}")
    if missing:
        print(f"   missing (not bundled): {', '.join(missing)}")
    print("   reminder: a dynamically-linked system ffmpeg won't run on other machines —")
    print("   swap in a static build before distributing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
