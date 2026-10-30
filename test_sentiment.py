"""Tests for sentiment.py (offline lexicon classifier, no key needed).

Run:  python -m pytest test_sentiment.py -q
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sentiment import classify, enrich_csv, summarize  # noqa: E402


def test_positive_review():
    result = classify("I loved this book, brilliant and funny")
    assert result["label"] == "positive"
    assert result["positive"] == 3
    assert result["negative"] == 0


def test_negative_review():
    result = classify("Terrible, boring and a complete waste of time")
    assert result["label"] == "negative"
    assert result["negative"] >= 3


def test_neutral_when_no_lexicon_words():
    result = classify("The book has 320 pages and a blue cover")
    assert result == {"label": "neutral", "score": 0.0,
                      "positive": 0, "negative": 0}


def test_empty_text_is_neutral():
    assert classify("")["label"] == "neutral"
    assert classify(None)["label"] == "neutral"


def test_negation_flips_polarity():
    assert classify("not good")["label"] == "negative"
    assert classify("never boring")["label"] == "positive"
    assert classify("not terrible")["label"] == "positive"


def test_negation_does_not_leak_past_punctuation():
    # "not good. Great book" -- the second sentence stays positive.
    result = classify("not good. Great book")
    assert result["label"] == "neutral"  # -1 + 1 cancel out
    assert result["positive"] == 1
    assert result["negative"] == 1


def test_intensifier_amplifies_score():
    plain = classify("good")["score"]
    strong = classify("very good")["score"]
    assert strong > plain == 1.0
    dampened = classify("a bit good")["score"]
    assert 0 < dampened < plain


def test_mixed_review_scores_by_balance():
    result = classify("great story but boring ending")
    assert result["label"] == "neutral"
    assert result["positive"] == 1 and result["negative"] == 1


def test_summarize_counts_labels():
    results = [classify(t) for t in
               ("loved it", "hated it", "320 pages", "great book")]
    assert summarize(results) == {"positive": 2, "negative": 1,
                                  "neutral": 1, "total": 4}


def test_enrich_csv_adds_columns_and_preserves_rows(tmp_path):
    src = tmp_path / "reviews.csv"
    dst = tmp_path / "out.csv"
    src.write_text("review,rating\n"
                   '"I loved it, brilliant",5\n'
                   '"Terrible and boring",1\n'
                   '"It has 200 pages",3\n', encoding="utf-8")
    summary = enrich_csv(src, dst, "review")
    assert summary == {"positive": 1, "negative": 1, "neutral": 1, "total": 3}
    with open(dst, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert [r["sentiment"] for r in rows] == ["positive", "negative", "neutral"]
    assert [r["rating"] for r in rows] == ["5", "1", "3"]


def test_enrich_csv_missing_column_raises(tmp_path):
    src = tmp_path / "reviews.csv"
    src.write_text("title,price\nA Book,10\n", encoding="utf-8")
    try:
        enrich_csv(src, tmp_path / "out.csv", "review")
    except ValueError as exc:
        assert "review" in str(exc)
    else:
        raise AssertionError("expected ValueError for missing text column")


def test_sample_reviews_file_classifies_sensibly():
    sample = Path(__file__).parent / "sample_data" / "sample_reviews.csv"
    with open(sample, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    labels = [classify(r["review"])["label"] for r in rows]
    # 5-star rows positive, 1-2 star rows negative, 3-star row neutral.
    assert labels[0] == "positive"
    assert labels[2] == "negative"
    assert labels[3] == "negative"
    assert labels[4] == "neutral"
    assert labels[7] == "negative"
