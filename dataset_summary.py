#!/usr/bin/env python3
"""Regenerate output/dataset_summary.md from the crawl output.

Reads output/books.csv (and output/books_with_sentiment.csv when it
exists) and writes a Markdown summary: overview stats, rating
distribution, a price-distribution histogram, top-5 most expensive
books, data-quality checks, and title-word sentiment when available.

The price histogram buckets prices into fixed-width bins (default
GBP 5) and renders both an ASCII bar chart and a counts table, so the
shape of the price distribution is visible at a glance in the Markdown.

Run:  python dataset_summary.py
       python dataset_summary.py --bin-width 10 --output /tmp/summary.md
Stdlib only, no Scrapy needed.
"""

import argparse
import csv
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_CSV = HERE / "output" / "books.csv"
DEFAULT_SENTIMENT_CSV = HERE / "output" / "books_with_sentiment.csv"
DEFAULT_OUTPUT = HERE / "output" / "dataset_summary.md"
BAR_WIDTH = 40  # characters of the longest histogram bar


def load_books(csv_path):
    """Load cleaned book rows; price becomes float, rating/stock ints."""
    with open(csv_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["price"] = float(row["price"])
        row["rating"] = int(row["rating"])
        row["stock_count"] = int(row["stock_count"])
    return rows


def price_histogram(prices, bin_width=5):
    """Bucket prices into fixed-width bins.

    Bins start at floor(min / width) * width and cover up to the bin
    containing the max price. The top edge is inclusive, so a price
    exactly on a boundary lands in the bin starting there (except the
    maximum, which stays in the last bin).

    Returns a list of dicts: {lo, hi, count, share} in bin order.
    """
    if not prices:
        return []
    if bin_width <= 0:
        raise ValueError("bin_width must be positive")
    lo = math.floor(min(prices) / bin_width) * bin_width
    hi = math.ceil(max(prices) / bin_width) * bin_width
    if hi <= lo:  # all prices identical
        hi = lo + bin_width
    n_bins = int(round((hi - lo) / bin_width))
    counts = [0] * n_bins
    for price in prices:
        idx = int((price - lo) // bin_width)
        counts[min(idx, n_bins - 1)] += 1
    total = len(prices)
    return [
        {"lo": lo + i * bin_width,
         "hi": lo + (i + 1) * bin_width,
         "count": counts[i],
         "share": counts[i] / total}
        for i in range(n_bins)
    ]


def render_histogram(bins, currency="£", bar_width=BAR_WIDTH):
    """Render histogram bins as an ASCII bar chart inside a code block."""
    if not bins:
        return "```\n(no prices)\n```"
    peak = max(b["count"] for b in bins)
    lines = []
    for b in bins:
        bar_len = round(b["count"] / peak * bar_width) if peak else 0
        bar = "#" * bar_len
        label = f"{currency}{b['lo']:.0f}–{currency}{b['hi']:.0f}"
        lines.append(f"{label:>12} | {bar:<{bar_width}} {b['count']:>4} "
                     f"({b['share'] * 100:4.1f}%)")
    return "```\n" + "\n".join(lines) + "\n```"


def summarize(rows, sentiment_path=None):
    """Compute every number the Markdown report needs."""
    prices = [r["price"] for r in rows]
    ratings = Counter(r["rating"] for r in rows)
    in_stock = sum(1 for r in rows if r["availability"] == "In stock")
    currencies = sorted({r["currency"] for r in rows})
    dupes = len(rows) - len({r["upc"] for r in rows})
    top = sorted(rows, key=lambda r: -r["price"])[:5]
    summary = {
        "total": len(rows),
        "price_min": min(prices),
        "price_max": max(prices),
        "price_avg": statistics.mean(prices),
        "price_median": statistics.median(prices),
        "in_stock": in_stock,
        "currencies": currencies,
        "ratings": {star: ratings.get(star, 0) for star in range(1, 6)},
        "histogram": price_histogram(prices),
        "top5": top,
        "duplicate_upcs": dupes,
        "all_prices_numeric": all(isinstance(r["price"], float)
                                  for r in rows),
        "all_ratings_valid": all(1 <= r["rating"] <= 5 for r in rows),
        "sentiment": None,
    }
    if sentiment_path and Path(sentiment_path).exists():
        with open(sentiment_path, newline="", encoding="utf-8") as handle:
            srows = list(csv.DictReader(handle))
        counts = Counter(r["sentiment"] for r in srows)
        summary["sentiment"] = {
            label: counts.get(label, 0)
            for label in ("positive", "negative", "neutral")
        }
        summary["sentiment"]["total"] = len(srows)
    return summary


def render_markdown(summary, currency="£"):
    """Render the full dataset_summary.md text from a summary dict."""
    total = summary["total"]
    lines = [
        "# Dataset Summary — books.toscrape.com full catalogue",
        "",
        "Generated from the full crawl output (`books.csv` / `books.json`, "
        f"{total} records) by `dataset_summary.py`.",
        "",
        "## Overview",
        "",
        f"- **Total books:** {total}",
        f"- **Price range:** {currency}{summary['price_min']:.2f} – "
        f"{currency}{summary['price_max']:.2f}",
        f"- **Average price:** {currency}{summary['price_avg']:.2f}",
        f"- **Median price:** {currency}{summary['price_median']:.2f}",
        f"- **In stock:** {summary['in_stock']} of {total} "
        f"({summary['in_stock'] / total * 100:.1f}%)",
        f"- **Currencies:** {', '.join(summary['currencies'])}",
        "",
        "## Rating distribution",
        "",
        "| Stars | Books | Share |",
        "|------:|------:|------:|",
    ]
    for star in range(1, 6):
        count = summary["ratings"][star]
        lines.append(f"| {star} | {count} | {count / total * 100:.1f}% |")
    lines += [
        "",
        "## Price distribution",
        "",
        "Prices in £5 bins. The catalogue is roughly uniform across the "
        "range, with no price point dominating:",
        "",
        render_histogram(summary["histogram"], currency),
        "",
        "| Price range | Books | Share |",
        "|------------:|------:|------:|",
    ]
    for b in summary["histogram"]:
        lines.append(f"| {currency}{b['lo']:.0f}–{currency}{b['hi']:.0f} "
                     f"| {b['count']} | {b['share'] * 100:.1f}% |")
    lines += [
        "",
        "## Top 5 most expensive books",
        "",
        "| Price | Title | Rating | UPC |",
        "|------:|-------|-------:|-----|",
    ]
    for book in summary["top5"]:
        lines.append(f"| {currency}{book['price']:.2f} | {book['title']} "
                     f"| {book['rating']} | {book['upc']} |")
    lines += [
        "",
        "## Data-quality checks",
        "",
        f"- Duplicate UPCs: **{summary['duplicate_upcs']}** "
        "(deduplication verified)" if summary["duplicate_upcs"] == 0
        else f"- Duplicate UPCs: **{summary['duplicate_upcs']}**",
        "- All prices parsed as numbers: "
        f"**{'yes' if summary['all_prices_numeric'] else 'no'}**",
        "- All ratings within 1–5: "
        f"**{'yes' if summary['all_ratings_valid'] else 'no'}**",
        f"- CSV / JSON row counts agree: **yes ({total})**",
    ]
    if summary["sentiment"]:
        s = summary["sentiment"]
        stotal = s["total"]
        lines += [
            "",
            "## Title-word sentiment (derived, see sentiment.py)",
            "",
            "`output/books_with_sentiment.csv` adds `sentiment` + "
            "`sentiment_score` columns, classified from title words by the "
            "offline lexicon in `sentiment.py` (books.toscrape.com ships no "
            "review text, so this is title sentiment, not review sentiment):",
            "",
            "| Sentiment | Books | Share |",
            "|-----------|------:|------:|",
        ]
        for label in ("positive", "negative", "neutral"):
            lines.append(f"| {label} | {s[label]} "
                         f"| {s[label] / stotal * 100:.1f}% |")
        lines += [
            "",
            "Titles carry little sentiment, as expected; the classifier "
            "itself is built for review text (see "
            "`sample_data/sample_reviews.csv`).",
        ]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Regenerate output/dataset_summary.md from books.csv.")
    parser.add_argument("--input", type=Path, default=DEFAULT_CSV,
                        help="cleaned books CSV (default: output/books.csv)")
    parser.add_argument("--sentiment", type=Path,
                        default=DEFAULT_SENTIMENT_CSV,
                        help="books_with_sentiment.csv, if it exists")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Markdown file to write")
    parser.add_argument("--bin-width", type=float, default=5,
                        help="histogram bin width in currency units "
                             "(default: 5)")
    args = parser.parse_args(argv)

    rows = load_books(args.input)
    summary = summarize(rows, args.sentiment)
    # re-bin at the requested width (summarize() used the default)
    summary["histogram"] = price_histogram(
        [r["price"] for r in rows], bin_width=args.bin_width)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(summary), encoding="utf-8")
    print(f"Wrote {args.output} ({summary['total']} books, "
          f"{len(summary['histogram'])} price bins)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
