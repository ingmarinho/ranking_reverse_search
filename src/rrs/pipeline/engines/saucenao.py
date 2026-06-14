from .base import Engine

ENGINE = Engine(
    id="saucenao",
    name="SauceNAO",
    category="specialized",
    enabled_by_default=False,
    status="ready",
    url_template="https://saucenao.com/search.php?url={image_url}",
)
