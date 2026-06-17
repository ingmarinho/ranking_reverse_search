#!/bin/bash
# rrs launcher for macOS.
#
# The rrs bundle is not notarized by Apple, so when you download and unzip it,
# macOS quarantines every file inside. Gatekeeper then blocks them one at a time
# ("...cannot be opened because Apple cannot check it for malicious software"),
# which means dozens of "Open Anyway" prompts — one per bundled library.
#
# This script clears that quarantine flag from the WHOLE bundle in a single
# step, then starts rrs. You only deal with Gatekeeper once (for this script),
# instead of once per file.
#
# Easiest: open Terminal and run (quarantine never blocks a script run this way):
#     bash "/path/to/start-rrs-macos.command"
# Or double-click it in Finder (approve once via right-click > Open if prompted).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Clearing macOS quarantine on the rrs bundle (one-time)..."
xattr -dr com.apple.quarantine "$DIR" 2>/dev/null || true

echo "==> Starting rrs. Open http://localhost:8080 in your browser; press Ctrl-C here to quit."
exec "$DIR/rrs-app" "$@"
