"""Tests for near_duplicates.py (TF cosine near-duplicate detection).

Run:  python -m pytest test_near_duplicates.py -q
"""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from near_duplicates import (  # noqa: E402
    enrich_csv, find_groups, find_pairs, similarity, summarize_groups,
    term_frequencies,
)


def test_identical_texts_score_one():
    assert similarity("red leather wallet", "red leather wallet") == 1.0


def test_word_order_does_not_matter():
    assert similarity("red leather wallet", "wallet leather red") == 1.0


def test_case_and_punctuation_ignored():
    assert similarity("Red Leather Wallet!", "red leather wallet") == 1.0


def test_disjoint_texts_score_zero():
    assert similarity("red leather wallet", "blue cotton shirt") == 0.0


def test_empty_text_scores_zero():
    assert similarity("", "red leather wallet") == 0.0
    assert similarity("", "") == 0.0
    assert similarity(None, "red leather wallet") == 0.0


def test_repeated_words_change_score():
    # Same words, different counts: not identical, not disjoint.
    score = similarity("cat cat dog", "cat dog dog")
    assert 0.0 < score < 1.0
    assert abs(score - 0.8) < 1e-9


def test_near_duplicate_scores_high():
    score = similarity(
        "the quick brown fox jumps over the lazy dog",
        "the quick brown fox jumps over a lazy dog",
    )
    assert score > 0.9


def test_find_pairs_threshold_boundary():
    texts = ["red leather wallet", "red leather wallet handmade",
             "blue cotton shirt"]
    pairs = find_pairs(texts, threshold=0.85)
    assert len(pairs) == 1
    assert pairs[0][0] == 0 and pairs[0][1] == 1
    assert pairs[0][2] >= 0.85
    # A threshold of 1.0 keeps only exact duplicates.
    assert find_pairs(texts, threshold=1.0) == []


def test_find_pairs_sorted_best_first():
    texts = ["a b c d", "a b c d", "a b c e", "x y z"]
    pairs = find_pairs(texts, threshold=0.5)
    scores = [score for _i, _j, score in pairs]
    assert scores == sorted(scores, reverse=True)
    assert pairs[0][:2] == (0, 1)
    assert pairs[0][2] == 1.0


def test_find_groups_transitive_chain():
    # A~B and B~C link all three even though A and C are under threshold.
    texts = ["one two three four five six seven eight",
             "one two three four five six seven nine",
             "one two three four five six nine ten"]
    groups = find_groups(texts, threshold=0.85)
    assert groups == [[0, 1, 2]]


def test_find_groups_singletons_excluded():
    texts = ["red leather wallet", "red leather wallet",
             "blue cotton shirt"]
    assert find_groups(texts, threshold=0.85) == [[0, 1]]


def test_find_groups_sorted_largest_first():
    texts = ["a b c", "a b c", "a b c", "x y", "x y", "q w e"]
    groups = find_groups(texts, threshold=0.9)
    assert groups == [[0, 1, 2], [3, 4]]


def test_threshold_out_of_range_rejected():
    with pytest.raises(ValueError, match="between 0 and 1"):
        find_pairs(["a b", "a b"], threshold=1.5)
    with pytest.raises(ValueError, match="between 0 and 1"):
        find_groups(["a b", "a b"], threshold=-0.1)


def test_term_frequencies_counts():
    assert term_frequencies("Cat cat DOG") == {"cat": 2, "dog": 1}


def test_summarize_groups_counts():
    texts = ["red leather wallet", "red leather wallet",
             "blue cotton shirt", "blue cotton shirt", "green hat"]
    summary = summarize_groups(texts, threshold=0.85)
    assert summary == {
        "total": 5,
        "duplicate_rows": 4,
        "groups": 2,
        "group_sizes": [2, 2],
    }


def test_enrich_csv_marks_groups_and_keeps_rows(tmp_path):
    input_path = tmp_path / "pages.csv"
    output_path = tmp_path / "pages_marked.csv"
    with open(input_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["title", "price"])
        writer.writerow(["red leather wallet", "25.00"])
        writer.writerow(["red leather wallet handmade", "25.00"])
        writer.writerow(["blue cotton shirt", "19.99"])
    summary = enrich_csv(input_path, output_path, "title", threshold=0.85)
    assert summary["total"] == 3
    assert summary["groups"] == 1
    with open(output_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert rows[0]["duplicate_group"] == "1"
    assert rows[1]["duplicate_group"] == "1"
    assert rows[2]["duplicate_group"] == "0"


def test_enrich_csv_missing_column_raises(tmp_path):
    input_path = tmp_path / "pages.csv"
    with open(input_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["title"])
        writer.writerow(["red leather wallet"])
    with pytest.raises(ValueError, match="text column"):
        enrich_csv(input_path, tmp_path / "out.csv", "description")
