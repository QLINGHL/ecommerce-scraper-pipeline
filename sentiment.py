#!/usr/bin/env python3
"""Offline lexicon sentiment classification for scraped text.

Turns a piece of text (typically a product review) into a sentiment
label::

    {"label": "positive", "score": 2.5, "positive": 2, "negative": 0}

No model, no API key, no third-party dependency -- just a small
English polarity lexicon plus two rules that matter for review text:

* **Negation**: ``not`` / ``no`` / ``never`` flip the polarity of the
  next few words, so "not good" scores negative instead of positive.
* **Intensifiers**: ``very`` / ``really`` / ``extremely`` amplify the
  next polarity word; ``somewhat`` / ``slightly`` dampen it.

This is a deliberately transparent baseline, in the spirit of the
offline fallback in ``llm_extract.py``: it is easy to audit, it runs
anywhere, and it degrades gracefully (unknown words simply do not
count) instead of failing. It is not a substitute for a trained
classifier -- sarcasm, domain slang and long-range context will fool
it -- but for triaging scraped review text into positive / neutral /
negative buckets it is a useful first pass, and it pairs naturally
with the LLM extraction in ``llm_extract.py`` when a key is available.

Usage::

    # classify one review on the command line
    python sentiment.py --text "I loved this book, brilliant and funny"

    # enrich a CSV: adds ``sentiment`` and ``sentiment_score`` columns
    python sentiment.py --input reviews.csv --text-column review \\
        --output reviews_with_sentiment.csv

    # the books dataset has no review text (books.toscrape.com ships
    # no reviews), so its derived file classifies title words instead
    # -- mostly neutral, and documented as such in the README:
    python sentiment.py --input output/books.csv --text-column title \\
        --output output/books_with_sentiment.csv
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Lexicon
# ---------------------------------------------------------------------------

POSITIVE_WORDS = {
    "love", "loved", "loves", "lovely", "excellent", "great", "wonderful",
    "amazing", "awesome", "brilliant", "fantastic", "superb", "perfect",
    "beautiful", "enjoyable", "enjoyed", "delightful", "delight",
    "fascinating", "gripping", "moving", "charming", "witty", "funny",
    "fun", "inspiring", "helpful", "insightful", "masterpiece", "gem",
    "treasure", "heartwarming", "touching", "powerful", "elegant",
    "clever", "smart", "engaging", "absorbing", "memorable", "rich",
    "vivid", "honest", "warm", "tender", "joyful", "happy", "pleased",
    "satisfied", "recommend", "recommended", "best", "favorite",
    "favourite", "impressive", "remarkable", "outstanding", "superior",
    "good", "nice", "fine", "solid", "strong", "fresh", "original",
}

NEGATIVE_WORDS = {
    "hate", "hated", "hates", "terrible", "awful", "horrible", "dreadful",
    "boring", "bore", "bored", "dull", "tedious", "disappointing",
    "disappointed", "disappointment", "poor", "weak", "flat", "bland",
    "shallow", "pointless", "waste", "wasted", "confusing", "confused",
    "annoying", "frustrating", "frustrated", "bad", "worst", "ugly",
    "sad", "depressing", "dark", "grim", "slow", "dragging", "messy",
    "sloppy", "thin", "empty", "hollow", "forced", "clichéd", "cliche",
    "predictable", "overrated", "underwhelming", "mediocre", "flawed",
    "broken", "failed", "failure", "regret", "avoid", "skip", "painful",
}

NEGATIONS = {"not", "no", "never", "neither", "nor", "n't"}

INTENSIFIERS = {
    "very": 1.5,
    "really": 1.5,
    "extremely": 2.0,
    "incredibly": 2.0,
    "absolutely": 2.0,
    "totally": 1.5,
    "highly": 1.5,
    "so": 1.5,
    "somewhat": 0.5,
    "slightly": 0.5,
    "a": 1.0,  # placeholder so "a bit" is handled below, not here
}

# "a bit" / "a little" dampen the next polarity word.
_DAMPENING_PHRASES = (("a", "bit"), ("a", "little"), ("kind", "of"))

_TOKEN_RE = re.compile(r"[a-z]+(?:n't)?|[^\s]")
_NEGATION_WINDOW = 3


def _tokens(text):
    """Lowercase word tokens; punctuation kept as separate tokens so
    it can bound the negation window."""
    if text is None:
        return []
    return _TOKEN_RE.findall(str(text).lower())


def classify(text):
    """Classify *text*.

    Returns ``{"label", "score", "positive", "negative"}`` where
    ``label`` is ``"positive"`` / ``"negative"`` / ``"neutral"``,
    ``score`` is the weighted polarity sum, and ``positive`` /
    ``negative`` count the matched lexicon words (before weighting).
    Empty or wordless text is neutral with score 0.
    """
    tokens = _tokens(text)
    score = 0.0
    positive = negative = 0
    negate_left = 0
    multiplier = 1.0
    prev = None
    for token in tokens:
        if prev is not None and (prev, token) in _DAMPENING_PHRASES:
            multiplier = 0.5
            prev = token
            continue
        if token in NEGATIONS or token.endswith("n't"):
            negate_left = _NEGATION_WINDOW
            prev = token
            continue
        if token in INTENSIFIERS and token != "a":
            multiplier = INTENSIFIERS[token]
            prev = token
            continue
        if token in POSITIVE_WORDS or token in NEGATIVE_WORDS:
            polarity = 1.0 if token in POSITIVE_WORDS else -1.0
            if negate_left > 0:
                polarity = -polarity
            weighted = polarity * multiplier
            score += weighted
            if polarity > 0:
                positive += 1
            else:
                negative += 1
            negate_left = 0
            multiplier = 1.0
        else:
            if negate_left > 0:
                negate_left -= 1
            if not token.isalpha():
                # punctuation ends a negation scope
                negate_left = 0
            multiplier = 1.0 if token.isalpha() else multiplier
        prev = token
    if score > 0:
        label = "positive"
    elif score < 0:
        label = "negative"
    else:
        label = "neutral"
    return {
        "label": label,
        "score": score,
        "positive": positive,
        "negative": negative,
    }


def summarize(results):
    """Count labels in an iterable of :func:`classify` results."""
    counts = Counter(r["label"] for r in results)
    return {
        "positive": counts.get("positive", 0),
        "negative": counts.get("negative", 0),
        "neutral": counts.get("neutral", 0),
        "total": sum(counts.values()),
    }


def enrich_csv(input_path, output_path, text_column,
               sentiment_column="sentiment", score_column="sentiment_score"):
    """Read *input_path* CSV, append sentiment columns for
    *text_column*, write to *output_path*.

    Returns the label summary dict. Rows are preserved in order and
    count; a missing text column raises :class:`ValueError` instead
    of silently producing an empty column.
    """
    with open(input_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{input_path} has no header row")
        if text_column not in reader.fieldnames:
            raise ValueError(
                f"text column {text_column!r} not in {input_path} "
                f"(columns: {', '.join(reader.fieldnames)})"
            )
        rows = list(reader)
        fieldnames = list(reader.fieldnames) + [sentiment_column, score_column]

    results = []
    for row in rows:
        result = classify(row.get(text_column, ""))
        row[sentiment_column] = result["label"]
        row[score_column] = result["score"]
        results.append(result)

    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return summarize(results)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Offline lexicon sentiment classification.")
    parser.add_argument("--text", help="classify this single text")
    parser.add_argument("--input", help="input CSV file to enrich")
    parser.add_argument("--output", help="output CSV file (default: stdout)")
    parser.add_argument("--text-column", default="review",
                        help="text column in the input CSV (default: review)")
    parser.add_argument("--sentiment-column", default="sentiment")
    parser.add_argument("--score-column", default="sentiment_score")
    args = parser.parse_args(argv)

    if args.text is not None:
        print(json.dumps(classify(args.text), ensure_ascii=False))
        return 0

    if not args.input:
        parser.error("one of --text or --input is required")

    input_path = Path(args.input)
    if args.output:
        summary = enrich_csv(
            input_path, args.output, args.text_column,
            args.sentiment_column, args.score_column)
        print(f"# sentiment summary: {json.dumps(summary)}", file=sys.stderr)
        return 0

    # No --output: stream the enriched CSV to stdout.
    with open(input_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or args.text_column not in reader.fieldnames:
            raise ValueError(
                f"text column {args.text_column!r} not in {input_path}")
        fieldnames = list(reader.fieldnames) + [args.sentiment_column,
                                                args.score_column]
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()
        results = []
        for row in reader:
            result = classify(row.get(args.text_column, ""))
            row[args.sentiment_column] = result["label"]
            row[args.score_column] = result["score"]
            results.append(result)
            writer.writerow(row)
    print(f"# sentiment summary: {json.dumps(summarize(results))}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
