from .base import Engine

ENGINE = Engine(
    id="google_lens",
    name="Google Lens",
    category="western",
    enabled_by_default=True,
    status="ready",
    url_template="https://lens.google.com/uploadbyurl?url={image_url}",
)
