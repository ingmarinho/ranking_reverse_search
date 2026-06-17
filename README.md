# rrs — ranking reverse search

A local NiceGUI app for sourcing (original) video clips out of compilation/ranking/general
videos via reverse image search.

## Install

Requires Python 3.11+ and ffmpeg on PATH.

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

IBM Plex Mono woff2 files are bundled under `src/rrs/ui/static/fonts/`
(OFL-1.1 licensed).

## Run

```sh
export IMGBB_API_KEY=<your-key>
export DATA_DIR=./data            # optional, defaults to ./data
export MAX_CLIP_DURATION_SEC=180  # optional, default 180; rrs refuses longer
                                  # initial clips (it's built for shorts). 0 = off
rrs                                # or: python -m rrs.main
```

Open <http://localhost:8080>.

## Workflow

1. Paste a YouTube (or other yt-dlp-supported) URL → app downloads at
   1080p, detects scenes, extracts first frame per scene.
2. For each scene: click the frame thumbnail to pick a different frame
   (or add additional frames), then click an engine button to open a
   reverse-image search in a new tab.
3. When you find the source, paste its URL into the scene's source
   field and click DOWNLOAD (highest available quality).
4. Click TRIM CLIP to scrub and save the relevant moment.

## Building a desktop bundle

`scripts/pack.py` builds a standalone bundle (the recipient needs no Python,
ffmpeg, or deno install) with PyInstaller. It runs on macOS, Windows, and Linux —
but PyInstaller can't cross-compile, so build on the OS you're targeting:

```sh
pip install pyinstaller
python scripts/pack.py        # or, on Unix: scripts/rrs-pack
# → dist/rrs-app/  (launcher + _internal/); run dist/rrs-app/rrs-app
```

It bundles rrs's package data (`schema.sql`, `ui/static`) and the
`ffmpeg`/`ffprobe`/`deno` binaries currently on PATH into `_internal/bin/`; the
frozen app puts that dir on PATH at startup (`config._activate_bundled_binaries`).

**Caveats:**
- A dynamically-linked system ffmpeg (e.g. Homebrew) runs on *your* machine but
  not a clean one — drop a *static* ffmpeg/ffprobe into `_internal/bin/` for real
  distribution. CI already does this.
- Bundles are unsigned, so macOS Gatekeeper / Windows SmartScreen warn on first
  launch. Sign + notarize before handing to non-technical users.
- `DATA_DIR` defaults to `./data` relative to the launch directory.

## Releasing builds (CI)

`.github/workflows/build.yml` builds bundles for **Windows x64, macOS (Apple
Silicon), and Linux x64** on GitHub's native runners (no cross-compile).

- **Tag a release** → builds all three and attaches the zips to a GitHub Release:
  ```sh
  git tag v0.1.0 && git push origin v0.1.0
  ```
- **Manual run** (Actions → "Build bundles" → Run workflow) → zips uploaded as run
  artifacts, no Release. Use this to smoke-test before tagging.

Each job installs Deno and a static ffmpeg per OS (macOS arm64 pulls from
ffmpeg.martin-riedl.de, since `setup-ffmpeg` has no arm64 build), then runs
`scripts/pack.py`.

## Tests

```sh
pytest
```
