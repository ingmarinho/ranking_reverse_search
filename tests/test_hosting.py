from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest
import respx

from rrs.pipeline.hosting import ImgbbError, upload_image


@pytest.fixture
def small_jpeg(tmp_path: Path) -> Path:
    """A 1x1 jpeg byte-blob is enough for upload tests."""
    p = tmp_path / "x.jpg"
    p.write_bytes(
        b"\xff\xd8\xff\xdb\x00C\x00"
        + b"\x08" * 64
        + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        + b"\xff\xc4\x00\x14\x00\x01"
        + b"\x00" * 15
        + b"\xff\xc4\x00\x14\x10\x01"
        + b"\x00" * 15
        + b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x37\xff\xd9"
    )
    return p


@respx.mock
def test_upload_image_success(small_jpeg: Path):
    respx.post("https://api.imgbb.com/1/upload").mock(
        return_value=httpx.Response(
            200, json={"data": {"url": "https://i.ibb.co/abc/x.jpg"}, "success": True}
        )
    )
    url = upload_image(small_jpeg, api_key="k123")
    assert url == "https://i.ibb.co/abc/x.jpg"


@respx.mock
def test_upload_image_sends_base64_form_field(small_jpeg: Path):
    route = respx.post("https://api.imgbb.com/1/upload").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://i.ibb.co/x.jpg"}})
    )
    upload_image(small_jpeg, api_key="k123")
    sent = route.calls.last.request
    body = sent.content.decode()
    assert "image=" in body
    expected = base64.b64encode(small_jpeg.read_bytes()).decode()
    assert expected[:20].replace("+", "%2B").replace("/", "%2F") in body or expected[:20] in body


@respx.mock
def test_upload_image_http_error_raises(small_jpeg: Path):
    respx.post("https://api.imgbb.com/1/upload").mock(
        return_value=httpx.Response(403, text="forbidden")
    )
    with pytest.raises(ImgbbError):
        upload_image(small_jpeg, api_key="bad")


@respx.mock
def test_upload_image_malformed_response_raises(small_jpeg: Path):
    respx.post("https://api.imgbb.com/1/upload").mock(
        return_value=httpx.Response(200, json={"nope": True})
    )
    with pytest.raises(ImgbbError):
        upload_image(small_jpeg, api_key="k")
