from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from rrs.config import Config
    from rrs.store.db import Database

# A 1x1 transparent PNG, base64-encoded. Used as a throwaway probe to validate an
# imgbb API key without uploading anything meaningful.
_TEST_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lE"
    "QVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class ImgbbError(RuntimeError):
    pass


def _imgbb_upload(
    image_b64: str, api_key: str, timeout: float, extra_params: dict | None = None
) -> dict:
    """POST a base64 image to imgbb and return the response's `data` object.

    Raises ImgbbError on a transport failure, an error status, or a response
    missing the expected `data` field.
    """
    try:
        resp = httpx.post(
            "https://api.imgbb.com/1/upload",
            params={"key": api_key, **(extra_params or {})},
            data={"image": image_b64},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise ImgbbError(f"imgbb request failed: {exc}") from exc

    if resp.status_code >= 400:
        raise ImgbbError(f"imgbb {resp.status_code}: {resp.text[:200]}")

    try:
        return resp.json()["data"]
    except (KeyError, ValueError) as exc:
        raise ImgbbError(f"imgbb malformed response: {resp.text[:200]}") from exc


def upload_image(path: Path, api_key: str, timeout: float = 30.0) -> str:
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    data = _imgbb_upload(encoded, api_key, timeout)
    try:
        return data["url"]
    except (KeyError, TypeError) as exc:
        raise ImgbbError(f"imgbb malformed response: missing url ({data!r:.200})") from exc


def validate_imgbb_key(api_key: str, timeout: float = 15.0) -> None:
    """Validate an imgbb key by uploading a self-expiring 1x1 probe image.

    Raises ImgbbError if imgbb rejects the key (or the request fails). On success
    the probe is deleted best-effort; expiration=60 guarantees cleanup regardless.
    """
    data = _imgbb_upload(_TEST_PNG_B64, api_key, timeout, {"expiration": 60})
    delete_url = data.get("delete_url") if isinstance(data, dict) else None
    if delete_url:
        try:
            httpx.get(delete_url, timeout=timeout)
        except httpx.HTTPError:
            pass  # best-effort; expiration=60 is the guaranteed cleanup


def effective_imgbb_key(db: Database, cfg: Config) -> str | None:
    """The key actually in effect: the in-app (DB) value wins over the env var."""
    return db.get_imgbb_key() or cfg.imgbb_api_key
