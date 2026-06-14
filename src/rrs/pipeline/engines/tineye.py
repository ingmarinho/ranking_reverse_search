from .base import Engine

ENGINE = Engine(
    id="tineye",
    name="TinEye",
    category="western",
    enabled_by_default=True,
    status="ready",
    url_template="https://tineye.com/search?url={image_url}",
)
