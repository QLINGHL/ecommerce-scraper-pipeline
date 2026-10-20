#!/usr/bin/env python3
"""Tiny standalone check of the cleaning pipeline on fake raw items.

Run:  python test_pipeline.py
(No Scrapy install needed — it imports the pure helper functions and
replicates the three pipeline stages: clean -> dedupe -> validate.)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bookstore_scraper.pipelines import REQUIRED_FIELDS, clean_item

RAW_ITEMS = [
    {  # normal record, messy whitespace
        "title": "  A Light in the   Attic ",
        "price_raw": "£51.77",
        "rating_raw": "Three",
        "availability_raw": "\n    In stock (22 available)\n",
        "product_url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        "upc": "a897fe39b1053632",
    },
    {  # duplicate of #1 (same UPC, different case) -> must be dropped
        "title": "A Light in the Attic",
        "price_raw": "£51.77",
        "rating_raw": "Three",
        "availability_raw": "In stock (22 available)",
        "product_url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        "upc": "A897FE39B1053632",
    },
    {  # out of stock, dollar price, numeric rating
        "title": "Tipping the Velvet",
        "price_raw": "$53.74",
        "rating_raw": "1",
        "availability_raw": "Out of stock",
        "product_url": "https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html",
        "upc": "e30f54cea2aec58f",
    },
    {  # incomplete: no price -> must be dropped by validation
        "title": "Broken Record",
        "price_raw": "currently unavailable",
        "rating_raw": "Five",
        "availability_raw": "In stock",
        "product_url": "https://books.toscrape.com/catalogue/broken_1/index.html",
        "upc": "deadbeefdeadbeef",
    },
]


def run_pipeline(raw_items):
    """Replicates CleaningPipeline -> DuplicatesPipeline -> ValidationPipeline."""
    seen_upcs, kept, dropped = set(), [], []
    for raw in raw_items:
        cleaned = clean_item(raw)                                # stage 1: clean
        upc = cleaned.get("upc")
        if upc and upc in seen_upcs:                             # stage 2: dedupe
            dropped.append((cleaned, "duplicate UPC"))
            continue
        if upc:
            seen_upcs.add(upc)
        missing = [f for f in REQUIRED_FIELDS                     # stage 3: validate
                   if cleaned.get(f) in (None, "")]
        if missing:
            dropped.append((cleaned, f"missing {missing}"))
            continue
        kept.append(cleaned)
    return kept, dropped


def main():
    kept, dropped = run_pipeline(RAW_ITEMS)
    print(f"Input: {len(RAW_ITEMS)} raw items -> kept {len(kept)}, dropped {len(dropped)}\n")
    print("KEPT:")
    for item in kept:
        print(" ", item)
    print("\nDROPPED:")
    for item, reason in dropped:
        print(f"  ({reason}) {item['title']!r} upc={item['upc']}")

    assert len(kept) == 2, "expected exactly 2 records to survive"
    assert kept[0]["price"] == 51.77 and kept[0]["currency"] == "GBP"
    assert kept[0]["rating"] == 3 and kept[0]["stock_count"] == 22
    assert kept[0]["title"] == "A Light in the Attic"
    assert kept[1]["availability"] == "Out of stock" and kept[1]["stock_count"] == 0
    print("\nAll assertions passed.")


if __name__ == "__main__":
    main()
