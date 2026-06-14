---
name: add-engine
description: Scaffold a new reverse-image-search engine for rrs — creates the engine module, wires it into the registry, and adds a registry test. Use when adding or promoting a reverse-search provider.
disable-model-invocation: true
---

# Add a reverse-search engine

Engines live in `src/rrs/pipeline/engines/`. Each is a frozen `Engine` dataclass
(see `base.py`) exposing `search_url(image_url)`, which formats a `url_template`
with the URL-encoded public image URL. The registry (`engines/__init__.py`)
aggregates them; the enabled set is persisted in the `settings` table, seeded
once from `default_enabled_ids()`.

## Inputs to gather

Ask the user (or infer from their request) for:

- **`id`** — snake_case identifier, unique across `ALL_ENGINES` (e.g. `karma_decay`).
- **`name`** — human label (e.g. `Karma Decay`).
- **`category`** — one of `western` | `chinese` | `regional` | `specialized`.
- **`status`** — `ready` (has a working reverse-search-by-URL endpoint) or `todo`
  (no usable URL endpoint yet; a placeholder).
- **`url_template`** — for `ready` engines, the search URL with a literal
  `{image_url}` placeholder where the encoded image URL goes. `None` for `todo`.
- **`enabled_by_default`** — `True` only allowed when `status == "ready"`
  (enforced by `test_default_enabled_engines_are_ready`).

If the user only wants a `todo` placeholder, prefer the **stub shortcut** below.

## Steps for a `ready` engine (dedicated module)

1. **Create `src/rrs/pipeline/engines/<id>.py`** following the existing modules
   (see `tineye.py`):

   ```python
   from .base import Engine

   ENGINE = Engine(
       id="<id>",
       name="<Name>",
       category="<category>",
       enabled_by_default=<True|False>,
       status="ready",
       url_template="https://example.com/search?url={image_url}",
   )
   ```

2. **Register it in `src/rrs/pipeline/engines/__init__.py`**:
   - add `from .<id> import ENGINE as _<id>` alongside the other engine imports
     (keep them alphabetically grouped as they currently are), and
   - add `_<id>` to the `ALL_ENGINES` list (ready engines come before `*_stubs`).

3. **Extend `tests/test_engines_registry.py`**: add an
   `("<id>", "<expected_host>")` row to the
   `test_ready_engines_emit_url_with_image` parametrize list, where
   `<expected_host>` is a substring of the rendered URL (e.g. `example.com`).

## Steps for a `todo` placeholder (stub shortcut)

Add one line to the `STUBS` list in `src/rrs/pipeline/engines/stubs.py`:

```python
Engine("<id>", "<Name>", "<category>", False, "todo", None),
```

Then add `"<id>"` to the stub-id set asserted in
`test_registry_has_stubbed_engines`. No dedicated module is needed.

## Verify

Run the registry tests:

```sh
pytest tests/test_engines_registry.py -q
```

(The PostToolUse hook also runs this automatically after you edit the registry.)

## Notes

- `search_url()` returns `None` whenever `status != "ready"` or
  `url_template is None`, so the UI hides search links for `todo` engines.
- Newly added engines are **not** retroactively enabled for existing installs —
  the enabled set is seeded from `default_enabled_ids()` only on first run and
  thereafter persisted in the `settings` table. Users enable new engines via the
  settings UI.
