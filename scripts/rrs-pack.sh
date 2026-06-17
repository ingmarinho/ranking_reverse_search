#!/usr/bin/env bash
#
# rrs-pack — Unix convenience wrapper around scripts/pack.py.
#
# The real, cross-platform build logic lives in scripts/pack.py so macOS, Linux,
# and Windows share one implementation. On Windows, run it directly:
#
#     python scripts\pack.py
#
# Prereqs: pip install -e ".[dev]" pyinstaller

set -euo pipefail
exec "${PYTHON:-python}" "$(dirname "$0")/pack.py" "$@"
