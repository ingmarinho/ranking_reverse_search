#!/usr/bin/env bash
# PostToolUse hook: format + autofix the edited Python file with Ruff.
# Reads the hook JSON from stdin, extracts the edited file path, and runs
# `ruff check --fix` then `ruff format` on it. No-ops for non-.py files.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Prefer the venv ruff; fall back to PATH. Silently no-op if neither exists.
ruff_bin="$repo_root/.venv/bin/ruff"
[[ -x "$ruff_bin" ]] || ruff_bin="$(command -v ruff || true)"
[[ -n "$ruff_bin" ]] || exit 0

# Extract tool_input.file_path from the hook payload on stdin.
file_path="$("$repo_root/.venv/bin/python" -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
print(data.get("tool_input", {}).get("file_path", ""))
' 2>/dev/null || true)"

[[ -n "$file_path" && "$file_path" == *.py && -f "$file_path" ]] || exit 0

"$ruff_bin" check --fix --quiet "$file_path" || true
"$ruff_bin" format --quiet "$file_path" || true
exit 0
