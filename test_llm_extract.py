"""Tests for llm_extract.py (no LLM key needed; the model is faked).

Run:  python -m pytest test_llm_extract.py -q
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from llm_extract import (  # noqa: E402
    extract_product,
    main,
    parse_fallback,
)

PAGE = """\
Title: A Light in the Attic
Price: £51.77
Rating: Three out of five stars
Availability: In stock (22 available)
Product URL: https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html
UPC: a897fe39b1053632
"""


def test_fallback_extracts_every_field():
    record = parse_fallback(PAGE)
    assert record == {
        "title": "A Light in the Attic",
        "price": 51.77,
        "currency": "GBP",
        "rating": 3,
        "availability": "In stock",
        "stock_count": 22,
        "product_url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        "upc": "A897FE39B1053632",
    }


def test_fallback_on_prose_finds_price_rating_and_stock():
    record = parse_fallback(
        "Tipping the Velvet costs $53.74, rated 1 out of 5, "
        "Out of stock. See https://example.com/tipping-the-velvet "
        "UPC e30f54cea2aec58f."
    )
    assert record["price"] == 53.74
    assert record["currency"] == "USD"
    assert record["rating"] == 1
    assert record["availability"] == "Out of stock"
    assert record["stock_count"] == 0
    assert record["upc"] == "E30F54CEA2AEC58F"


def test_fallback_never_raises_and_keeps_schema():
    record = parse_fallback("nothing parseable here at all")
    assert set(record) == {
        "title", "price", "currency", "rating", "availability",
        "stock_count", "product_url", "upc",
    }
    assert record["price"] is None and record["rating"] is None


def test_llm_fenced_json_overrides_and_fills_gaps():
    def fake_llm(prompt):
        assert "A Light in the Attic" in prompt  # page text reaches the model
        return (
            "Here is the record:\n```json\n"
            '{"title": "A Light in the Attic (Illustrated)", "price": 51.77, '
            '"currency": "GBP", "rating": 3, "availability": "In stock", '
            '"stock_count": 22, "product_url": null, "upc": null}\n```'
        )

    record, meta = extract_product(PAGE, llm_client=fake_llm)
    assert meta["source"] == "llm+fallback"
    assert record["title"] == "A Light in the Attic (Illustrated)"
    # Null model fields keep the fallback values instead of wiping them.
    assert record["product_url"].endswith("a-light-in-the-attic_1000/index.html")
    assert record["upc"] == "A897FE39B1053632"


def test_llm_invalid_rating_is_rejected_not_propagated():
    def fake_llm(prompt):
        return json.dumps({"title": "X", "rating": 9, "price": "£12.34"})

    record, meta = extract_product(PAGE, llm_client=fake_llm)
    assert meta["source"] == "llm+fallback"
    assert record["rating"] == 3  # fallback survives the out-of-range 9
    assert record["price"] == 12.34  # string price with symbol still coerces


def test_llm_garbage_output_degrades_to_fallback():
    record, meta = extract_product(PAGE, llm_client=lambda p: "no json here")
    assert meta["source"] == "fallback"
    assert "llm_error" in meta
    assert record["price"] == 51.77 and record["title"] == "A Light in the Attic"


def test_llm_exception_degrades_to_fallback():
    def broken_llm(prompt):
        raise RuntimeError("network down")

    record, meta = extract_product(PAGE, llm_client=broken_llm)
    assert meta["source"] == "fallback"
    assert meta["llm_error"] == "network down"
    assert record["upc"] == "A897FE39B1053632"


def test_no_llm_client_means_plain_fallback():
    record, meta = extract_product(PAGE)
    assert meta == {"source": "fallback"}
    assert record["title"] == "A Light in the Attic"


def test_cli_reads_file_and_writes_json(tmp_path, capsys):
    src = tmp_path / "page.txt"
    src.write_text(PAGE, encoding="utf-8")
    out = tmp_path / "product.json"
    assert main(["--input", str(src), "--output", str(out)]) == 0
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["price"] == 51.77
    assert record["stock_count"] == 22
    assert "llm+fallback" not in capsys.readouterr().err  # fallback run
