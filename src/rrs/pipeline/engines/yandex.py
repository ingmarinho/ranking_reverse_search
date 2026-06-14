from .base import Engine

ENGINE = Engine(
    id="yandex",
    name="Yandex Images",
    category="western",
    enabled_by_default=True,
    status="ready",
    url_template="https://yandex.com/images/search?rpt=imageview&url={image_url}",
)
