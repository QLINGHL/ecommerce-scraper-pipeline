# Item pipelines: clean -> deduplicate -> validate.
#
# The cleaning helpers (parse_price, parse_rating, normalize_text, ...)
# are plain functions so they can be unit-tested without Scrapy.

import re

from scrapy.exceptions import DropItem

# ---------------------------------------------------------------------------
# Cleaning helpers
# ---------------------------------------------------------------------------

CURRENCY_SYMBOLS = {
    "£": "GBP",
    "$": "USD",
    "€": "EUR",
    "¥": "JPY",
}

RATING_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
}

_PRICE_RE = re.compile(r"([£$€¥])\s*([0-9][0-9,]*\.?[0-9]*)")
_STOCK_RE = re.compile(r"\((\d+)\s+available\)", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value):
    """Collapse all whitespace runs to single spaces and strip the ends."""
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value)).strip()


def parse_price(raw):
    """Parse a raw price string like '£51.77' -> (51.77, 'GBP').

    Returns (None, None) when no price can be found.
    """
    if raw is None:
        return None, None
    match = _PRICE_RE.search(str(raw))
    if not match:
        return None, None
    symbol, amount = match.groups()
    try:
        price = float(amount.replace(",", ""))
    except ValueError:
        return None, None
    return price, CURRENCY_SYMBOLS.get(symbol, symbol)


def parse_rating(raw):
    """Map a rating word ('Three') or digit to an int 0..5, else None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    word = normalize_text(raw).lower()
    if word in RATING_WORDS:
        return RATING_WORDS[word]
    if word.isdigit():
        return int(word)
    return None


def parse_availability(raw):
    """Parse raw availability text -> (status, stock_count).

    'In stock (22 available)' -> ('In stock', 22)
    'Out of stock'            -> ('Out of stock', 0)
    """
    text = normalize_text(raw)
    if not text:
        return "", None
    lowered = text.lower()
    if "out of stock" in lowered:
        return "Out of stock", 0
    if "in stock" in lowered:
        match = _STOCK_RE.search(text)
        count = int(match.group(1)) if match else None
        return "In stock", count
    return text, None


# Fields that must be present (and non-empty) for a record to be kept.
REQUIRED_FIELDS = ("title", "price", "upc", "product_url")


def clean_item(item):
    """Return a new dict with the cleaned final fields for *item*.

    Raw ``*_raw`` fields are consumed and not copied over.
    """
    price, currency = parse_price(item.get("price_raw", item.get("price")))
    availability, stock_count = parse_availability(
        item.get("availability_raw", item.get("availability"))
    )
    return {
        "title": normalize_text(item.get("title")),
        "price": price,
        "currency": currency,
        "rating": parse_rating(item.get("rating_raw", item.get("rating"))),
        "availability": availability,
        "stock_count": stock_count,
        "product_url": normalize_text(item.get("product_url")),
        "upc": normalize_text(item.get("upc")).upper(),
    }


# ---------------------------------------------------------------------------
# Pipelines (wired up in settings.py, in this order)
# ---------------------------------------------------------------------------


class CleaningPipeline:
    """Stage 1: normalize text, parse price / rating / availability."""

    def process_item(self, item, spider):
        cleaned = clean_item(item)
        item.clear()
        item.update(cleaned)
        return item


class DuplicatesPipeline:
    """Stage 2: drop records whose UPC was already seen in this crawl."""

    def __init__(self):
        self.seen_upcs = set()

    def process_item(self, item, spider):
        upc = item.get("upc")
        if upc:
            if upc in self.seen_upcs:
                raise DropItem(f"Duplicate item found (UPC: {upc})")
            self.seen_upcs.add(upc)
        return item


class ValidationPipeline:
    """Stage 3: drop incomplete records instead of exporting junk."""

    def process_item(self, item, spider):
        missing = [
            field
            for field in REQUIRED_FIELDS
            if item.get(field) in (None, "")
        ]
        if missing:
            raise DropItem(
                f"Incomplete item, missing {missing}: {dict(item)!r}"
            )
        return item
