# rrs — ranking reverse search

A local NiceGUI app for sourcing video clips out of compilation/ranking
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

## Tests

```sh
pytest
```

## Spec

See `docs/superpowers/specs/2026-06-14-ranking-reverse-search-design.md`.
