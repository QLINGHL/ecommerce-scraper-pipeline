# Dataset Summary — books.toscrape.com full catalogue

Generated from the full crawl output (`books.csv` / `books.json`, 1000 records).

## Overview

- **Total books:** 1000
- **Price range:** £10.00 – £59.99
- **Average price:** £35.07
- **Median price:** £35.98
- **In stock:** 1000 of 1000 (100.0%)
- **Currencies:** GBP

## Rating distribution

| Stars | Books | Share |
|------:|------:|------:|
| 1 | 226 | 22.6% |
| 2 | 196 | 19.6% |
| 3 | 203 | 20.3% |
| 4 | 179 | 17.9% |
| 5 | 196 | 19.6% |

## Top 5 most expensive books

| Price | Title | Rating | UPC |
|------:|-------|-------:|-----|
| £59.99 | The Perfect Play (Play by Play #1) | 3 | 9CC207168A03470D |
| £59.98 | Last One Home (New Beginnings #1) | 3 | 07E6810FD3236BDA |
| £59.95 | Civilization and Its Discontents | 2 | 396385E3DE5D18C3 |
| £59.92 | The Barefoot Contessa Cookbook | 5 | 6478CCB4416E6A5D |
| £59.90 | The Diary of a Young Girl | 3 | 54FC03F1E1D355DB |

## Data-quality checks

- Duplicate UPCs: **0** (deduplication verified)
- All prices parsed as numbers: **yes**
- All ratings within 1–5: **yes**
- CSV / JSON row counts agree: **yes (1000)**

## Title-word sentiment (derived, see sentiment.py)

`output/books_with_sentiment.csv` adds `sentiment` + `sentiment_score`
columns, classified from title words by the offline lexicon in
`sentiment.py` (books.toscrape.com ships no review text, so this is
title sentiment, not review sentiment):

| Sentiment | Books | Share |
|-----------|------:|------:|
| positive | 68 | 6.8% |
| negative | 26 | 2.6% |
| neutral | 906 | 90.6% |

Titles carry little sentiment, as expected; the classifier itself is
built for review text (see `sample_data/sample_reviews.csv`).
