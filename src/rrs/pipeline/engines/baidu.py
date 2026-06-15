from .base import Engine

ENGINE = Engine(
    id="baidu",
    name="Baidu Images",
    category="chinese",
    enabled_by_default=True,
    status="ready",
    url_template="https://graph.baidu.com/details?isfromtoy=1&image={image_url}",
)
