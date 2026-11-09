"""Tests for dataset_summary.py (price histogram + report generator).

Run:  python -m pytest test_dataset_summary.py -q
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dataset_summary import (  # noqa: E402
    load_books, price_histogram, render_histogram, render_markdown,
    summarize,
)


def test_histogram_bins_cover_full_range():
    bins = price_histogram([10.0, 14.99, 15.0, 59.99], bin_width=5)
    assert bins[0]["lo"] == 10 and bins[0]["hi"] == 15
    assert bins[-1]["lo"] == 55 and bins[-1]["hi"] == 60
    assert len(bins) == 10
    assert sum(b["count"] for b in bins) == 4


def test_histogram_boundary_price_starts_next_bin():
    # 15.00 belongs to the 15-20 bin, not 10-15.
    bins = price_histogram([10.0, 15.0, 19.99], bin_width=5)
    assert bins[0]["count"] == 1
    assert bins[1]["count"] == 2


def test_histogram_max_price_stays_in_last_bin():
    bins = price_histogram([10.0, 60.0], bin_width=5)
    assert bins[-1]["count"] == 1  # 60.00 is the top edge, not a new bin
    assert sum(b["count"] for b in bins) == 2


def test_histogram_shares_sum_to_one():
    bins = price_histogram([11.0, 22.0, 33.0, 44.0, 55.0], bin_width=5)
    assert abs(sum(b["share"] for b in bins) - 1.0) < 1e-9


def test_histogram_identical_prices_single_bin():
    bins = price_histogram([25.0, 25.0, 25.0], bin_width=5)
    assert len(bins) == 1
    assert bins[0]["count"] == 3


def test_histogram_empty_prices():
    assert price_histogram([], bin_width=5) == []


def test_histogram_rejects_non_positive_width():
    try:
        price_histogram([10.0], bin_width=0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("expected ValueError for bin_width=0")


def test_render_histogram_scales_longest_bar_to_full_width():
    bins = price_histogram([11.0] * 10 + [51.0], bin_width=5)
    chart = render_histogram(bins, bar_width=10)
    lines = chart.splitlines()
    assert lines[0] == "```" and lines[-1] == "```"
    busiest = next(l for l in lines if "£10–£15" in l)
    assert busiest.count("#") == 10
    assert "10 (90.9%)" in busiest


def test_render_histogram_empty():
    assert "(no prices)" in render_histogram([])


def test_load_books_parses_types(tmp_path):
    src = tmp_path / "books.csv"
    src.write_text("title,price,currency,rating,availability,stock_count,"
                   "upc,product_url\nA Book,12.50,GBP,4,In stock,3,"
                   "ABC123,http://x\n", encoding="utf-8")
    rows = load_books(src)
    assert rows[0]["price"] == 12.5
    assert rows[0]["rating"] == 4
    assert rows[0]["stock_count"] == 3


def test_summarize_small_dataset():
    rows = [
        {"title": "Cheap", "price": 11.0, "currency": "GBP", "rating": 5,
         "availability": "In stock", "stock_count": 1, "upc": "A1",
         "product_url": "http://x/1"},
        {"title": "Dear", "price": 58.0, "currency": "GBP", "rating": 1,
         "availability": "Out of stock", "stock_count": 0, "upc": "A2",
         "product_url": "http://x/2"},
    ]
    summary = summarize(rows)
    assert summary["total"] == 2
    assert summary["price_min"] == 11.0 and summary["price_max"] == 58.0
    assert summary["price_avg"] == 34.5
    assert summary["in_stock"] == 1
    assert summary["ratings"] == {1: 1, 2: 0, 3: 0, 4: 0, 5: 1}
    assert summary["top5"][0]["title"] == "Dear"
    assert summary["duplicate_upcs"] == 0
    assert sum(b["count"] for b in summary["histogram"]) == 2
    assert summary["sentiment"] is None


def test_summarize_counts_duplicate_upcs():
    rows = [
        {"title": "A", "price": 10.0, "currency": "GBP", "rating": 3,
         "availability": "In stock", "stock_count": 1, "upc": "DUP",
         "product_url": "http://x/1"},
        {"title": "B", "price": 20.0, "currency": "GBP", "rating": 3,
         "availability": "In stock", "stock_count": 1, "upc": "DUP",
         "product_url": "http://x/2"},
    ]
    assert summarize(rows)["duplicate_upcs"] == 1


def test_render_markdown_contains_histogram_section():
    summary = summarize([
        {"title": "A", "price": 12.0, "currency": "GBP", "rating": 4,
         "availability": "In stock", "stock_count": 2, "upc": "U1",
         "product_url": "http://x/1"},
        {"title": "B", "price": 47.0, "currency": "GBP", "rating": 2,
         "availability": "In stock", "stock_count": 0, "upc": "U2",
         "product_url": "http://x/2"},
    ])
    text = render_markdown(summary)
    assert "## Price distribution" in text
    assert "£10–£15" in text
    assert "| £10–£15 | 1 | 50.0% |" in text
    assert "## Rating distribution" in text
    assert "| 4 | 1 | 50.0% |" in text


def test_full_crawl_histogram_matches_known_numbers():
    """End-to-end on the real 1000-book CSV: histogram must add up and
    the headline stats must match the previously published summary."""
    csv_path = Path(__file__).parent / "output" / "books.csv"
    rows = load_books(csv_path)
    summary = summarize(
        rows,
        Path(__file__).parent / "output" / "books_with_sentiment.csv")
    assert summary["total"] == 1000
    assert summary["price_min"] == 10.0
    assert summary["price_max"] == 59.99
    assert round(summary["price_avg"], 2) == 35.07
    assert round(summary["price_median"], 2) == 35.98
    assert summary["ratings"] == {1: 226, 2: 196, 3: 203, 4: 179, 5: 196}
    assert summary["duplicate_upcs"] == 0
    assert len(summary["histogram"]) == 10  # £10-15 ... £55-60
    assert sum(b["count"] for b in summary["histogram"]) == 1000
    assert summary["sentiment"] == {"positive": 68, "negative": 26,
                                    "neutral": 906, "total": 1000}
    text = render_markdown(summary)
    assert "The Perfect Play (Play by Play #1)" in text
    assert "## Price distribution" in text


def test_regenerated_report_writes_histogram(tmp_path):
    src = tmp_path / "books.csv"
    with open(src, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["title", "price", "currency", "rating",
                         "availability", "stock_count", "upc",
                         "product_url"])
        writer.writerow(["A", "12.00", "GBP", "4", "In stock", "2",
                         "U1", "http://x/1"])
        writer.writerow(["B", "47.00", "GBP", "2", "In stock", "0",
                         "U2", "http://x/2"])
    out = tmp_path / "summary.md"
    import dataset_summary
    rc = dataset_summary.main(["--input", str(src), "--sentiment",
                               str(tmp_path / "missing.csv"),
                               "--output", str(out)])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "## Price distribution" in text
    assert "| £10–£15 | 1 | 50.0% |" in text
    assert "Title-word sentiment" not in text  # no sentiment file
