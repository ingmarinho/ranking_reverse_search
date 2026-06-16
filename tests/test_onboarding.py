from __future__ import annotations

from rrs.ui.onboarding import _mask_key


def test_mask_key_shows_last_four():
    assert _mask_key("abcdef1234") == "••••••1234"


def test_mask_key_short_key_fully_masked():
    assert _mask_key("abc") == "•••"


def test_mask_key_empty():
    assert _mask_key("") == ""
