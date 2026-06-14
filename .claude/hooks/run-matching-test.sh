#!/usr/bin/env bash
# PostToolUse hook: when a source module under src/rrs/ is edited, run its
# matching test file (tests/test_<module>.py) if one exists. Surfaces
# regressions immediately. Stays quiet when there is no matching test.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
py="$repo_root/.venv/bin/python"
[[ -x "$py" ]] || py="$(command -v python3 || true)"
[[ -n "$py" ]] || exit 0

file_path="$("$py" -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
print(data.get("tool_input", {}).get("file_path", ""))
' 2>/dev/null || true)"

# Only react to edits of src/rrs/**/*.py
case "$file_path" in
  *"/src/rrs/"*.py) ;;
  *) exit 0 ;;
esac

module="$(basename "$file_path" .py)"
[[ "$module" == "__init__" ]] && exit 0

test_file="$repo_root/tests/test_${module}.py"
[[ -f "$test_file" ]] || exit 0

# Run only the matching test file; -p no:cacheprovider keeps it side-effect free.
output="$(cd "$repo_root" && "$py" -m pytest "$test_file" -q -p no:cacheprovider 2>&1)" || {
  # Feed failures back to Claude via stderr + non-zero (exit 2 = blocking message).
  echo "Matching tests failed for $module (tests/test_${module}.py):" >&2
  echo "$output" | tail -25 >&2
  exit 2
}
exit 0
