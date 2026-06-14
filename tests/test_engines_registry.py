from __future__ import annotations

import pytest

from rrs.pipeline.engines import ALL_ENGINES, get_engine


@pytest.mark.parametrize(
    "engine_id, expected_host",
    [
        ("google_lens", "lens.google.com"),
        ("yandex", "yandex.com"),
        ("bing", "bing.com"),
        ("tineye", "tineye.com"),
        ("saucenao", "saucenao.com"),
    ],
)
def test_ready_engines_emit_url_with_image(engine_id: str, expected_host: str):
    e = get_engine(engine_id)
    assert e is not None
    assert e.status == "ready"
    url = e.search_url("https://i.ibb.co/abc/x.jpg")
    assert url is not None
    assert expected_host in url
    assert "i.ibb.co" in url or "%2Fi.ibb.co" in url or "i.ibb.co" in url.lower()


def test_registry_has_stubbed_engines():
    ids = {e.id for e in ALL_ENGINES}
    for stub in ("baidu", "sogou", "qihoo360", "naver", "lenso", "pimeyes", "karma_decay"):
        assert stub in ids, f"missing stub {stub}"
    assert all(get_engine(s).status == "todo" for s in ("baidu", "sogou", "naver"))


def test_get_engine_unknown_returns_none():
    assert get_engine("nope") is None


def test_default_enabled_engines_are_ready():
    for e in ALL_ENGINES:
        if e.enabled_by_default:
            assert e.status == "ready"
