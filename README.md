# E-commerce Web Scraper & Data Pipeline

A production-style [Scrapy](https://scrapy.org/) project that crawls the full
product catalogue of [books.toscrape.com](https://books.toscrape.com),
cleans and deduplicates the raw HTML data through a three-stage item
pipeline, and exports tidy **CSV** and **JSON** datasets.

> **Target site note:** books.toscrape.com is a public sandbox created
> specifically for practising web scraping — no real store is scraped.
> The crawler still behaves politely (delay + AutoThrottle + robots.txt),
> the way it would against a real shop.

## What it does

1. **Crawl** — walks all 50 catalogue listing pages (~1,000 books),
   following the pager, then visits every book's detail page.
2. **Extract** — per book: title, price, star rating, availability,
   product URL, and the UPC (which only exists on the detail page).
3. **Clean** — a pipeline chain normalizes the messy raw strings:
   - price `£51.77` → `price=51.77`, `currency=GBP`
   - rating word `Three` → `3`
   - availability `In stock (22 available)` → `In stock`, `stock_count=22`
   - whitespace collapsed, UPC upper-cased
4. **Deduplicate** — records are deduplicated by UPC across the crawl.
5. **Validate** — incomplete records (missing title / price / UPC / URL)
   are dropped instead of polluting the export.
6. **Export** — feed exporters write `output/books.csv` and
   `output/books.json` automatically at the end of the crawl.

## Tech stack

- **Python 3.10+**
- **Scrapy 2.11+** — spider, item pipelines, feed exporters, AutoThrottle
- No database required; the pipeline pattern ports directly to
  pandas / SQL / Airflow-style ETL jobs.

## Project layout

```
ecommerce-scraper-pipeline/
├── scrapy.cfg
├── requirements.txt
├── bookstore_scraper/
│   ├── items.py                 # BookItem schema (raw + cleaned fields)
│   ├── pipelines.py             # clean -> dedupe -> validate stages
│   ├── settings.py              # politeness, pipelines, feed exports
│   └── spiders/
│       └── books_spider.py      # catalogue + detail page spider
├── extract_emails.py            # standalone email-extraction utility
├── sample_data/
│   └── sample_page.html         # sample input for extract_emails.py
├── test_pipeline.py             # pipeline unit check on fake raw items
└── output/                      # books.csv / books.json land here
```

## How to run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Full crawl (~1,000 books, a few minutes at the polite default delay)
scrapy crawl books

# Quick smoke run — stop after 10 items
scrapy crawl books -s CLOSESPIDER_ITEMCOUNT=10
```

Results:

- `output/books.csv`
- `output/books.json`

### Sample output

| title | price | currency | rating | availability | stock_count | upc |
|---|---|---|---|---|---|---|
| A Light in the Attic | 51.77 | GBP | 3 | In stock | 22 | A897FE39B1053632 |
| Tipping the Velvet | 53.74 | GBP | 1 | In stock | 20 | E30F54CEA2AEC58F |
| Soumission | 50.10 | GBP | 1 | In stock | 20 | 6957F44C3847A3FE |

Fields: `title`, `price` (float), `currency`, `rating` (1–5 int),
`availability`, `stock_count`, `upc`, `product_url`.

## Bonus utility: `extract_emails.py`

A small standalone script (no Scrapy needed) that extracts and dedupes
email addresses from any text/HTML file — handy for lead-list cleanup.
It lowercases addresses, strips trailing punctuation, and unwraps the
common `name [at] domain [dot] com` obfuscation.

```bash
python extract_emails.py sample_data/sample_page.html --stdout
# jane.doe@example-shop.com, sales@…, support@…, … (5 unique)
```

## Tests

```bash
python test_pipeline.py
```

Feeds fake raw items (including a duplicate and an incomplete record)
through the same clean → dedupe → validate logic the spider uses and
asserts the cleaned output.

## Politeness & ethics

- Descriptive user agent, `ROBOTSTXT_OBEY = True`
- `DOWNLOAD_DELAY = 1.0` with AutoThrottle, low concurrency
- HTTP cache enabled during development to avoid repeat hits
- The target is a designated practice site; point this spider at a real
  shop only with the owner's permission and that site's terms in mind.
