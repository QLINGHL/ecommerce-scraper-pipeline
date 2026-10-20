# Scrapy settings for the bookstore_scraper project.
#
# Target site: https://books.toscrape.com — a public sandbox built
# specifically for practising web scraping. Even so, we crawl politely:
# a download delay, a descriptive user agent, and AutoThrottle enabled.

BOT_NAME = "bookstore_scraper"

SPIDER_MODULES = ["bookstore_scraper.spiders"]
NEWSPIDER_MODULE = "bookstore_scraper.spiders"

# Identify ourselves honestly instead of pretending to be a browser.
USER_AGENT = (
    "bookstore-scraper-pipeline/1.0 "
    "(+https://books.toscrape.com practice project; Scrapy)"
)

# Obey robots.txt.
ROBOTSTXT_OBEY = True

# --- Be polite ---------------------------------------------------------
# One request at a time, with a delay between requests.
CONCURRENT_REQUESTS = 4
DOWNLOAD_DELAY = 1.0
RANDOMIZE_DOWNLOAD_DELAY = True

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 10.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

# Cache responses during development to avoid re-hitting the site.
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 3600
HTTPCACHE_DIR = "httpcache"
HTTPCACHE_IGNORE_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408, 429]

# --- Pipelines ---------------------------------------------------------
# Lower number = runs earlier.
ITEM_PIPELINES = {
    "bookstore_scraper.pipelines.CleaningPipeline": 100,
    "bookstore_scraper.pipelines.DuplicatesPipeline": 200,
    "bookstore_scraper.pipelines.ValidationPipeline": 300,
}

# --- Feed exports ------------------------------------------------------
# `scrapy crawl books` writes both files automatically.
FEEDS = {
    "output/books.csv": {
        "format": "csv",
        "encoding": "utf-8",
        "overwrite": True,
        "fields": [
            "title",
            "price",
            "currency",
            "rating",
            "availability",
            "stock_count",
            "upc",
            "product_url",
        ],
    },
    "output/books.json": {
        "format": "json",
        "encoding": "utf-8",
        "overwrite": True,
        "indent": 2,
    },
}

# Keep logs readable.
LOG_LEVEL = "INFO"

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
