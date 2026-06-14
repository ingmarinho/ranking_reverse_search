from __future__ import annotations

import pytest

from rrs.pipeline.engines.base import Engine


def test_engine_search_url_quotes_image_url():
    e = Engine(
        id="t", name="T", category="western", enabled_by_default=True,
        status="ready", url_template="https://example.com/?u={image_url}",
    )
    url = e.search_url("https://i.ibb.co/abc/x.jpg?token=hi&size=1")
    assert "https://example.com/?u=" in url
    assert "%3A" in url and "%2F" in url


def test_engine_stub_status_returns_none():
    e = Engine(
        id="t", name="T", category="chinese", enabled_by_default=False,
        status="todo", url_template=None,
    )
    assert e.search_url("https://i.ibb.co/x.jpg") is None
