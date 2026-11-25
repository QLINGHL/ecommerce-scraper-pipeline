#!/usr/bin/env python3
"""Near-duplicate detection for scraped product pages.

Two product pages that say almost the same thing are usually the
same product listed twice -- a re-list, a mirror, or a crawl that
followed two URLs to one page. The UPC-based dedupe in
``bookstore_scraper/pipelines.py`` only catches exact duplicates;
this module catches the *near* ones, where the text differs a little
(a different price line, an extra paragraph, a reordered sentence)
but the content is the same.

Method: plain **term-frequency cosine similarity** on word tokens.
No model, no API key, no third-party dependency -- stdlib only, in
the spirit of ``sentiment.py`` and ``llm_extract.py``'s offline
fallback.

* ``similarity(a, b)`` -- cosine of the two texts' word-frequency
  vectors: 1.0 for identical word multisets (word order does not
  matter), 0.0 for texts sharing no word, 0.0 if either text is empty.
* ``find_pairs(texts, threshold=0.85)`` -- every (i, j, score) pair
  at or above the threshold, best first.
* ``find_groups(texts, threshold=0.85)`` -- pairs merged into groups
  with union-find, so a chain A~B, B~C becomes one group even when
  A and C are just under the threshold.
* ``enrich_csv(...)`` -- adds a ``duplicate_group`` column to a CSV
  (0 = unique, 1..N = group number), same shape as
  ``sentiment.enrich_csv``.

The default threshold of 0.85 is a starting point, not a law:
short titles share few words, so a pair of five-word titles needs
almost every word to match to clear it, while long descriptions
clear it easily. Tune it on your own data -- run with ``--report``
first and eyeball the borderline pairs.

Usage::

    # similarity of two texts
    python near_duplicates.py --text-a "red leather wallet" \\
        --text-b "red leather wallet handmade"

    # find duplicate groups among product titles in a CSV
    python near_duplicates.py --input output/books.csv \\
        --text-column title --threshold 0.85 --report

    # write the CSV back with a duplicate_group column
    python near_duplicates.py --input output/books.csv \\
        --text-column title --output output/books_deduped.csv
"""

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_THRESHOLD = 0.85

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text):
    """Lowercase word tokens; punctuation and case are ignored so
    "Red Wallet!" and "red wallet" tokenize identically."""
    if text is None:
        return []
    return _TOKEN_RE.findall(str(text).lower())


def term_frequencies(text):
    """Word -> count mapping for *text*."""
    return Counter(_tokens(text))


def _cosine(counter_a, counter_b):
    """Cosine similarity of two term-frequency Counters."""
    if not counter_a or not counter_b:
        return 0.0
    dot = sum(count * counter_b[word]
              for word, count in counter_a.items()
              if word in counter_b)
    if dot == 0:
        return 0.0
    norm_a = math.sqrt(sum(count * count for count in counter_a.values()))
    norm_b = math.sqrt(sum(count * count for count in counter_b.values()))
    # Clamp: identical vectors can land a hair above 1.0 in floats.
    return min(1.0, dot / (norm_a * norm_b))


def similarity(text_a, text_b):
    """Cosine similarity of two texts' word-frequency vectors.

    Returns a float in [0.0, 1.0]: 1.0 for texts with the same words
    in the same counts, 0.0 for texts sharing no word or an empty
    text.
    """
    return _cosine(term_frequencies(text_a), term_frequencies(text_b))


def _check_threshold(threshold):
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be between 0 and 1, got {threshold}")


def find_pairs(texts, threshold=DEFAULT_THRESHOLD):
    """All near-duplicate pairs in *texts*.

    Returns a list of ``(i, j, score)`` tuples with ``i < j`` and
    ``score >= threshold``, sorted by score descending. Texts are
    compared pairwise, so this is O(n^2) -- fine for a catalogue of
    a few thousand rows, not for a million.
    """
    _check_threshold(threshold)
    vectors = [term_frequencies(text) for text in texts]
    pairs = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            score = _cosine(vectors[i], vectors[j])
            if score >= threshold:
                pairs.append((i, j, score))
    pairs.sort(key=lambda pair: (-pair[2], pair[0], pair[1]))
    return pairs


def find_groups(texts, threshold=DEFAULT_THRESHOLD):
    """Near-duplicate groups in *texts*.

    Returns a list of index lists, one per group of two or more
    texts that are pairwise linked at or above *threshold* (linked
    transitively: A~B and B~C put A, B and C in one group). Groups
    are sorted largest first, then by their lowest index; indices
    inside a group are ascending. Singletons are not returned.
    """
    pairs = find_pairs(texts, threshold)
    parent = list(range(len(texts)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j, _score in pairs:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    buckets = {}
    for index in range(len(texts)):
        buckets.setdefault(find(index), []).append(index)
    groups = [sorted(members) for members in buckets.values()
              if len(members) > 1]
    groups.sort(key=lambda members: (-len(members), members[0]))
    return groups


def summarize_groups(texts, threshold=DEFAULT_THRESHOLD):
    """Summary dict for a list of texts: total rows, how many sit in
    a duplicate group, and the groups themselves (as index lists)."""
    groups = find_groups(texts, threshold)
    return {
        "total": len(texts),
        "duplicate_rows": sum(len(group) for group in groups),
        "groups": len(groups),
        "group_sizes": [len(group) for group in groups],
    }


def enrich_csv(input_path, output_path, text_column,
               threshold=DEFAULT_THRESHOLD,
               group_column="duplicate_group"):
    """Read *input_path* CSV, append a duplicate-group column for
    *text_column*, write to *output_path*.

    Rows are preserved in order and count; a missing text column
    raises :class:`ValueError` instead of silently producing an
    empty column. The group column holds 0 for unique rows and
    1..N for rows in a duplicate group (groups numbered largest
    first). Returns the summary dict from :func:`summarize_groups`.
    """
    _check_threshold(threshold)
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
        fieldnames = list(reader.fieldnames) + [group_column]

    texts = [row.get(text_column, "") for row in rows]
    groups = find_groups(texts, threshold)
    group_of = {}
    for number, members in enumerate(groups, start=1):
        for index in members:
            group_of[index] = number
    for index, row in enumerate(rows):
        row[group_column] = group_of.get(index, 0)

    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary = summarize_groups(texts, threshold)
    summary["groups_detail"] = groups
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Near-duplicate detection by word-frequency "
                    "cosine similarity.")
    parser.add_argument("--text-a", help="first text to compare")
    parser.add_argument("--text-b", help="second text to compare")
    parser.add_argument("--input", help="input CSV file to scan")
    parser.add_argument("--output", help="output CSV file (adds a "
                        "duplicate_group column)")
    parser.add_argument("--text-column", default="title",
                        help="text column in the input CSV "
                             "(default: title)")
    parser.add_argument("--threshold", type=float,
                        default=DEFAULT_THRESHOLD,
                        help="similarity at or above which two texts "
                             "count as near-duplicates (default: 0.85)")
    parser.add_argument("--report", action="store_true",
                        help="print duplicate groups instead of writing "
                             "a CSV")
    args = parser.parse_args(argv)

    if args.text_a is not None or args.text_b is not None:
        if args.text_a is None or args.text_b is None:
            parser.error("--text-a and --text-b must be given together")
        print(json.dumps({
            "similarity": similarity(args.text_a, args.text_b),
        }))
        return 0

    if not args.input:
        parser.error("one of --text-a/--text-b or --input is required")

    input_path = Path(args.input)
    with open(input_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{input_path} has no header row")
        if args.text_column not in reader.fieldnames:
            raise ValueError(
                f"text column {args.text_column!r} not in {input_path} "
                f"(columns: {', '.join(reader.fieldnames)})"
            )
        rows = list(reader)
    texts = [row.get(args.text_column, "") for row in rows]

    if args.report or not args.output:
        groups = find_groups(texts, args.threshold)
        summary = summarize_groups(texts, args.threshold)
        print(json.dumps(summary, ensure_ascii=False))
        for number, members in enumerate(groups, start=1):
            print(f"\n# group {number} ({len(members)} rows):")
            for index in members:
                print(f"  [{index}] {texts[index]}")
        return 0

    summary = enrich_csv(input_path, args.output, args.text_column,
                         args.threshold)
    detail = summary.pop("groups_detail")
    print(f"# near-duplicate summary: {json.dumps(summary)}",
          file=sys.stderr)
    print(f"# wrote {args.output} "
          f"({len(rows)} rows, {len(detail)} groups)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
