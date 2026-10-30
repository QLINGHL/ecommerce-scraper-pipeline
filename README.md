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
├── sentiment.py                 # offline lexicon sentiment classifier (negation + intensifiers, stdlib only)
├── test_sentiment.py          # tests for sentiment.py
├── llm_extract.py               # LLM structured extraction: page text -> unified product JSON (offline parser fallback, no key needed)
├── test_llm_extract.py          # tests for llm_extract.py (fake LLM client, no key needed)
├── extract_emails.py            # standalone email-extraction utility
├── sample_data/
│   ├── sample_page.html         # sample input for extract_emails.py
│   └── sample_reviews.csv       # sample review input for sentiment.py
├── test_pipeline.py             # pipeline unit check on fake raw items
└── output/                      # books.csv / books.json / dataset_summary.md
                                 # books_with_sentiment.csv (derived: title-word sentiment)
```

## How to run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Full crawl (~1,000 books, ~20 minutes at the polite default delay)
scrapy crawl books

# Quick smoke run — stop after 10 items
scrapy crawl books -s CLOSESPIDER_ITEMCOUNT=10
```

Results:

- `output/books.csv`
- `output/books.json`

## Review sentiment classification (offline lexicon)

`sentiment.py` classifies review text into positive / neutral /
negative with a small English polarity lexicon, negation handling
("not good" → negative) and intensifiers ("very good" scores higher
than "good"). No model, no key, stdlib only:

```bash
python sentiment.py --text "I loved this book, brilliant and funny"
# {"label": "positive", "score": 3.0, "positive": 3, "negative": 0}

# enrich any CSV that has a text column
python sentiment.py --input reviews.csv --text-column review \
    --output reviews_with_sentiment.csv
# adds sentiment + sentiment_score columns, prints the label summary

# demo on the bundled sample reviews (8 rows)
python sentiment.py --input sample_data/sample_reviews.csv \
    --text-column review --output /tmp/reviews_with_sentiment.csv
# summary: positive 4, negative 3, neutral 1

# tests (no key needed)
python -m pytest test_sentiment.py -q
```

One honest caveat, documented here rather than hidden: **the books
dataset itself has no review text** — books.toscrape.com ships no
reviews, and the crawl only collects title / price / rating /
availability / UPC. So `output/books_with_sentiment.csv` is a derived
file that classifies **title words** (e.g. "perfect", "dark") instead
of reviews, and it shows exactly what that limitation predicts:
1000 rows, **68 positive, 26 negative, 906 neutral** — titles carry
little sentiment. The classifier itself is built for real review text
(see `sample_data/sample_reviews.csv`); point it at a dataset that
actually has a review column and the same command works unchanged.

## LLM structured extraction

`llm_extract.py` turns raw product-page text into the same unified
JSON record the pipeline produces. With no key it runs the offline
parser (same price / rating / availability rules as `pipelines.py`);
with `OPENAI_API_KEY` set, `--llm` sends the text to an
OpenAI-compatible model and validates the reply, filling any missing
or invalid field from the offline parser — a model failure never loses
the record:

```bash
python llm_extract.py --input page.txt
cat page.txt | python llm_extract.py
python llm_extract.py --input page.txt --llm --output product.json

# tests (no key needed)
python -m pytest test_llm_extract.py -q
```

The copies in `output/` are from a **full crawl of all 1,000 books**
(no items dropped by validation). Headline numbers: prices run
£10.00–£59.99 (average £35.07), ratings spread across all five star
levels, 0 duplicate UPCs. The full breakdown — rating distribution,
top-5 most expensive, data-quality checks — is in
**[output/dataset_summary.md](output/dataset_summary.md)**.

### Sample output

First rows of the full-crawl `books.csv`:

| title | price | currency | rating | availability | stock_count | upc |
|---|---|---|---|---|---|---|
| It's Only the Himalayas | 45.17 | GBP | 2 | In stock | 19 | A22124811BFA8350 |
| Libertarianism for Beginners | 51.33 | GBP | 2 | In stock | 19 | A18A4F574854ACED |
| Mesaerion: The Best Science Fiction Stories 1800-1849 | 37.59 | GBP | 1 | In stock | 19 | E30F54CEA9B38190 |

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
