from __future__ import annotations

from rrs.store.db import CropRect
from rrs.ui.modals import crop_from_payload


def test_none_payload_returns_none():
    assert crop_from_payload(None) is None


def test_empty_dict_returns_none():
    assert crop_from_payload({}) is None


def test_valid_payload_returns_croprect():
    r = crop_from_payload({"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4})
    assert r == CropRect(0.1, 0.2, 0.3, 0.4)


def test_sub_min_size_returns_none():
    # w below MIN_CROP_FRACTION (0.01) is a stray click, not a crop.
    assert crop_from_payload({"x": 0.1, "y": 0.1, "w": 0.005, "h": 0.5}) is None


def test_out_of_range_is_clamped():
    r = crop_from_payload({"x": -0.2, "y": 0.5, "w": 5.0, "h": 5.0})
    assert r is not None
    assert r.x == 0.0 and r.y == 0.5
    # w/h clamped so the box stays inside the frame.
    assert abs(r.x + r.w - 1.0) < 1e-9
    assert abs(r.y + r.h - 1.0) < 1e-9
    assert r.w > 0.01
    assert r.h > 0.01


def test_exact_min_size_is_rejected():
    assert crop_from_payload({"x": 0.1, "y": 0.1, "w": 0.01, "h": 0.5}) is None


def test_sub_min_height_returns_none():
    assert crop_from_payload({"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.005}) is None


def test_non_numeric_returns_none():
    assert crop_from_payload({"x": "a", "y": 0.1, "w": 0.5, "h": 0.5}) is None
