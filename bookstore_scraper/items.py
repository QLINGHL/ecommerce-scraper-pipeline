# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class BookItem(scrapy.Item):
    """One scraped product (book) record.

    The spider fills the ``*_raw`` fields straight from the HTML; the
    pipelines then turn them into the cleaned final fields.
    """

    # --- final, cleaned fields (what ends up in the CSV / JSON export) ---
    title = scrapy.Field()
    price = scrapy.Field()          # float, e.g. 51.77
    currency = scrapy.Field()       # ISO-ish symbol/code, e.g. "GBP" / "£"
    rating = scrapy.Field()         # int 1..5
    availability = scrapy.Field()   # "In stock" / "Out of stock"
    stock_count = scrapy.Field()    # int or None
    product_url = scrapy.Field()
    upc = scrapy.Field()

    # --- raw fields, populated by the spider, consumed by pipelines ---
    price_raw = scrapy.Field()
    rating_raw = scrapy.Field()
    availability_raw = scrapy.Field()
