# rrs — ranking reverse search

A local NiceGUI app for sourcing (original) video clips out of compilation/ranking/general
videos via reverse image search.

## Install

Requires Python 3.11+, with **ffmpeg + ffprobe** on PATH. **Deno ≥2.0** is also
recommended (`brew install deno` or <https://deno.com/>): yt-dlp runs it to solve
YouTube's signature/nsig challenges. Missing Deno is non-fatal (you get a warning
banner) but available formats degrade.

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"       # contributors: editable install + dev tools
# or, just to run it:
pip install -r requirements.txt
```

IBM Plex Mono woff2 files are bundled under `src/rrs/ui/static/fonts/`
(OFL-1.1 licensed).

### Linux / WSL2 (Debian/Ubuntu)

Windows users can run rrs inside [WSL2](https://learn.microsoft.com/windows/wsl/install)
— install it, then follow the steps below in the Linux shell. `localhost:8080`
is shared with Windows, so you open the app in your normal Windows browser.

Grab the system dependencies (`ffmpeg` includes `ffprobe`), then Deno:

```sh
sudo apt update
sudo apt install -y ffmpeg python3-venv python3-pip
curl -fsSL https://deno.land/install.sh | sh   # then restart the shell so deno is on PATH
```

Then create the venv and install rrs as shown above (`python3 -m venv .venv`,
`source .venv/bin/activate`, `pip install -e ".[dev]"`).

## Run

```sh
export IMGBB_API_KEY=<your-key>   # optional — or enter it in-app on first launch
export DATA_DIR=./data            # optional, defaults to ./data
export MAX_CLIP_DURATION_SEC=180  # optional, default 180; rrs refuses longer
                                  # initial clips (it's built for shorts). 0 = off
rrs                                # or: python -m rrs.main
```

Open <http://localhost:8080>.

Reverse search needs an [imgbb](https://api.imgbb.com/) API key (frames are
uploaded there to get a public URL for the search engines). If you don't set
`IMGBB_API_KEY`, the app gates behind an onboarding screen where you can paste
one; you can change it later from the settings button. Uploaded frames expire on
imgbb automatically (after a week).

## Workflow

1. Paste a YouTube (or other yt-dlp-supported) URL → app downloads at
   1080p, detects scenes, extracts first frame per scene.
2. For each scene: click the frame thumbnail to pick a different frame
   (or add additional frames), then click an engine button to open a
   reverse-image search in a new tab.
3. When you find the source, paste its URL into the scene's source
   field and click DOWNLOAD (highest available quality). OPEN FOLDER
   reveals where clips are saved.
4. Click TRIM CLIP to scrub and save the relevant moment.

Downloads land in the active job's folder. A "Download an extra clip" box at the
bottom of the page lets you pull in any additional video by URL.

Because downloads go through [yt-dlp](https://github.com/yt-dlp/yt-dlp), the URL
doesn't have to be YouTube: yt-dlp supports
[well over a thousand sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)
(Vimeo, TikTok, Twitter/X, Reddit, Twitch, news sites, and many more), plus
direct links to bare video files — so rrs can pull a clip from almost anywhere on
the internet.

## Building a desktop bundle

`scripts/pack.py` builds a standalone bundle (the recipient needs no Python,
ffmpeg, or deno install) with PyInstaller. It runs on macOS, Windows, and Linux —
but PyInstaller can't cross-compile, so build on the OS you're targeting:

```sh
pip install pyinstaller
python scripts/pack.py        # or, on Unix: scripts/rrs-pack
# → dist/rrs-app/  (launcher + _internal/); run dist/rrs-app/rrs-app
# on macOS the bundle also gets start-rrs-macos.command (see below)
```

It bundles rrs's package data (`schema.sql`, `ui/static`) and the
`ffmpeg`/`ffprobe`/`deno` binaries currently on PATH into `_internal/bin/`; the
frozen app puts that dir on PATH at startup (`config._activate_bundled_binaries`).

**Caveats:**
- A dynamically-linked system ffmpeg (e.g. Homebrew) runs on *your* machine but
  not a clean one — drop a *static* ffmpeg/ffprobe into `_internal/bin/` for real
  distribution. CI already does this.
- Bundles are unsigned (not notarized), so macOS Gatekeeper / Windows SmartScreen
  warn on first launch. On **macOS** a downloaded, unzipped bundle is quarantined
  and Gatekeeper otherwise blocks each bundled binary in turn (dozens of "Open
  Anyway" prompts). The bundled `start-rrs-macos.command` clears the quarantine
  flag from the whole folder once, then starts rrs — see [Running on macOS](#running-a-downloaded-bundle-on-macos).
  Sign + notarize if you want it to just work for non-technical users.
- `DATA_DIR` (when unset) defaults to a `data/` folder next to the binary in a
  bundled build, and to `./data` relative to the launch directory in a source
  run. Set `DATA_DIR` to override either.

## Releasing builds (CI)

`.github/workflows/build.yml` builds bundles for **Windows x64, macOS (Apple
Silicon), and Linux x64** on GitHub's native runners (no cross-compile).

- **Tag a release** → builds all three and attaches the zips to a GitHub Release:
  ```sh
  git tag v0.1.0 && git push origin v0.1.0
  ```
- **Manual run** (Actions → "Build bundles" → Run workflow) → zips uploaded as run
  artifacts, no Release. Use this to smoke-test before tagging.

Each job installs Deno and a static ffmpeg per OS, then runs `scripts/pack.py`.
Windows uses `setup-ffmpeg`; macOS arm64 and Linux x64 pull portable builds
directly from ffmpeg.martin-riedl.de (`setup-ffmpeg` has no arm64 build, and its
Linux source goes down periodically).

### Running a downloaded bundle on macOS

The bundles are not notarized by Apple. macOS quarantines anything downloaded
from a browser, so when you unzip `rrs-macos-arm64.zip` Gatekeeper blocks the
app — and because the bundle contains 130+ libraries plus ffmpeg/ffprobe/deno,
clearing them one at a time means an endless string of "Open Anyway" prompts.

The zip includes **`start-rrs-macos.command`**, which removes the quarantine flag
from the entire bundle in one step and then launches rrs. Use it instead of
running `rrs-app` directly:

```sh
# In Terminal (running a script this way is never blocked by Gatekeeper):
bash "/path/to/rrs-macos-arm64/start-rrs-macos.command"
```

Or double-click `start-rrs-macos.command` in Finder (if macOS prompts the first
time, right-click it → Open → Open). Then open <http://localhost:8080>.

## Tests

```sh
pytest
```

## License

[MIT](LICENSE)
