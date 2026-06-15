from .base import Engine

ENGINE = Engine(
    id="sogou",
    name="Sogou Images",
    category="chinese",
    enabled_by_default=True,
    status="ready",
    url_template="https://pic.sogou.com/ris?query={image_url}",
)
