from __future__ import annotations

from rrs.main import _static_dir


def test_static_dir_resolves_to_existing_assets():
    """The static dir must resolve via importlib (frozen-safe), not __file__,
    and actually contain the bundled stylesheet."""
    static_dir = _static_dir()
    assert static_dir.is_dir()
    assert (static_dir / "app.css").is_file()
