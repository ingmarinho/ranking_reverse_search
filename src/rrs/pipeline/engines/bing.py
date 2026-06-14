from .base import Engine

ENGINE = Engine(
    id="bing",
    name="Bing Visual Search",
    category="western",
    enabled_by_default=True,
    status="ready",
    url_template="https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:{image_url}",
)
