#!/usr/bin/env python3
"""LLM structured extraction for scraped product pages.

Turns raw product-page text into one unified JSON record::

    {
      "title": "A Light in the Attic",
      "price": 51.77,
      "currency": "GBP",
      "rating": 3,
      "availability": "In stock",
      "stock_count": 22,
      "product_url": "https://books.toscrape.com/catalogue/...",
      "upc": "A897FE39B1053632"
    }

Two paths, in the spirit of the existing pipeline (``pipelines.py``):

* **With an LLM** (``llm_client`` given, or ``--llm`` with an
  ``OPENAI_API_KEY`` in the environment): the page text is sent to the
  model with a fixed JSON schema prompt, the returned JSON is validated
  and coerced, and any field the model missed or got wrong is filled in
  from the offline parser below. A model failure never loses the record
  -- it just degrades to the offline path.
* **Without a key** (the default): the offline parser runs on its own.
  It reuses the same rules as ``pipelines.py`` (price symbols, rating
  words, ``In stock (N available)``), so results stay consistent with
  the Scrapy pipeline. It works best on semi-structured page text
  (``Title: ...`` / ``Price: ...`` lines or the raw strings the spider
  already collects); on free-form prose it still finds price, rating,
  availability, URL and UPC, but the title falls back to the first
  plausible line.

No third-party dependency: the optional OpenAI-compatible client uses
only :mod:`urllib` from the standard library. No API key is ever read
from, or written to, this repository -- it comes from the environment.

Run::

    python llm_extract.py --input page.txt
    cat page.txt | python llm_extract.py
    python llm_extract.py --input page.txt --llm --output product.json
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Unified record schema
# ---------------------------------------------------------------------------

FIELDS = (
    "title",
    "price",
    "currency",
    "rating",
    "availability",
    "stock_count",
    "product_url",
    "upc",
)

CURRENCY_SYMBOLS = {
    "£": "GBP",
    "$": "USD",
    "€": "EUR",
    "¥": "JPY",
}

CURRENCIES = set(CURRENCY_SYMBOLS.values())

RATING_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
}

_PRICE_RE = re.compile(r"([£$€¥])\s*([0-9][0-9,]*\.?[0-9]*)")
_RATING_WORD_RE = re.compile(
    r"\b(zero|one|two|three|four|five)\b(?:\s+out\s+of\s+five)?"
    r"(?:\s+stars?)?",
    re.IGNORECASE,
)
_RATING_DIGIT_RE = re.compile(
    r"(?:rated?|rating|stars?)\s*[:=]?\s*([0-5])(?:\s*/\s*5|\s+out\s+of\s+5)?",
    re.IGNORECASE,
)
_STOCK_RE = re.compile(r"\((\d+)\s+available\)", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_UPC_RE = re.compile(r"\b([A-Fa-f0-9]{16})\b")
_WHITESPACE_RE = re.compile(r"\s+")
_KEY_VALUE_RE = re.compile(r"^\s*([A-Za-z_ ]+)\s*[:=]\s*(.+?)\s*$")


def normalize_text(value):
    """Collapse whitespace runs to single spaces and strip the ends."""
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value)).strip()


# ---------------------------------------------------------------------------
# Offline parser (no key needed; mirrors pipelines.py rules)
# ---------------------------------------------------------------------------


def _key_value_map(text):
    """Parse ``Key: value`` lines into a lowercase-key dict."""
    mapping = {}
    for line in text.splitlines():
        match = _KEY_VALUE_RE.match(line)
        if match:
            mapping[normalize_text(match.group(1)).lower()] = normalize_text(
                match.group(2)
            )
    return mapping


def _parse_price(text):
    match = _PRICE_RE.search(text)
    if not match:
        return None, None
    symbol, amount = match.groups()
    try:
        price = float(amount.replace(",", ""))
    except ValueError:
        return None, None
    return price, CURRENCY_SYMBOLS.get(symbol, symbol)


def _parse_rating(text):
    match = _RATING_DIGIT_RE.search(text)
    if match:
        return int(match.group(1))
    match = _RATING_WORD_RE.search(text)
    if match:
        return RATING_WORDS[match.group(1).lower()]
    return None


def _parse_availability(text):
    lowered = normalize_text(text).lower()
    if "out of stock" in lowered:
        return "Out of stock", 0
    if "in stock" in lowered:
        match = _STOCK_RE.search(text)
        return "In stock", int(match.group(1)) if match else None
    return "", None


def _guess_title(text, fields):
    """Best-effort title: an explicit ``Title:`` line, else the first
    line that is not itself a price / rating / stock / URL / UPC line."""
    title = fields.get("title", "")
    if title:
        return title
    for line in text.splitlines():
        line = normalize_text(line)
        if not line:
            continue
        if _PRICE_RE.search(line) and len(line) < 30:
            continue
        if _URL_RE.search(line) and len(line) < 120 and line.startswith("http"):
            continue
        if _UPC_RE.fullmatch(line):
            continue
        if _RATING_WORD_RE.search(line) and len(line) < 40:
            continue
        if "stock" in line.lower() and len(line) < 40:
            continue
        return line
    return ""


def parse_fallback(text):
    """Extract a record from *text* with regex rules only.

    Returns a dict with every field in :data:`FIELDS`; unparseable
    fields are ``None`` (``""`` for title/availability) rather than
    raising, so a partial record is still usable downstream.
    """
    fields = _key_value_map(text)
    price, currency = _parse_price(text)
    availability, stock_count = _parse_availability(text)
    url_match = _URL_RE.search(text)
    upc_match = _UPC_RE.search(text)
    return {
        "title": _guess_title(text, fields),
        "price": price,
        "currency": currency,
        "rating": _parse_rating(text),
        "availability": availability,
        "stock_count": stock_count,
        "product_url": url_match.group(0).rstrip(".,)") if url_match else "",
        "upc": upc_match.group(1).upper() if upc_match else "",
    }


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "Extract the product described in the page text below into ONE JSON "
    "object with exactly these fields: title (string), price (number or "
    "null), currency (3-letter code or null), rating (integer 0-5 or "
    "null), availability (\"In stock\" or \"Out of stock\" or null), "
    "stock_count (integer or null), product_url (string or null), "
    "upc (string or null). Reply with JSON only, no explanation."
)


def build_prompt(text):
    return f"{SYSTEM_PROMPT}\n\n--- page text ---\n{text}"


def _extract_json(text):
    """Return the first valid JSON object in *text*.

    Tolerates ```json fenced blocks and surrounding prose, and skips
    ``{`` characters that do not start a parseable object.
    """
    cleaned = normalize_text(text)
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    start = 0
    while True:
        open_idx = cleaned.find("{", start)
        if open_idx == -1:
            raise ValueError("no JSON object found in model output")
        depth, in_string, escaped = 0, False, False
        for idx in range(open_idx, len(cleaned)):
            char = cleaned[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(cleaned[open_idx : idx + 1])
                        except json.JSONDecodeError:
                            break
        start = open_idx + 1


def _coerce_price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _PRICE_RE.search(str(value))
    if match:
        try:
            return float(match.group(2).replace(",", ""))
        except ValueError:
            return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _coerce_rating(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and 0 <= value <= 5:
        return int(value)
    if isinstance(value, str):
        word = normalize_text(value).lower()
        if word in RATING_WORDS:
            return RATING_WORDS[word]
        if word.isdigit() and 0 <= int(word) <= 5:
            return int(word)
    return None


def _coerce_stock_count(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _apply_llm_record(record, llm_obj):
    """Overlay validated LLM fields onto *record* (in place).

    A field is only overwritten when the model value survives coercion
    and validation; anything missing, mistyped or out of range keeps
    the offline parser's value, so a sloppy model reply can never make
    the record worse than the fallback.
    """
    if not isinstance(llm_obj, dict):
        raise ValueError("model output is not a JSON object")

    title = normalize_text(llm_obj.get("title"))
    if title:
        record["title"] = title

    price = _coerce_price(llm_obj.get("price"))
    if price is not None:
        record["price"] = price

    currency = llm_obj.get("currency")
    if isinstance(currency, str):
        currency = normalize_text(currency).upper()
        if currency in CURRENCIES:
            record["currency"] = currency

    rating = _coerce_rating(llm_obj.get("rating"))
    if rating is not None:
        record["rating"] = rating

    availability = normalize_text(llm_obj.get("availability"))
    if availability in ("In stock", "Out of stock"):
        record["availability"] = availability

    stock_count = _coerce_stock_count(llm_obj.get("stock_count"))
    if stock_count is not None:
        record["stock_count"] = stock_count

    url = normalize_text(llm_obj.get("product_url"))
    if url.startswith("http"):
        record["product_url"] = url

    upc = normalize_text(llm_obj.get("upc"))
    if upc:
        record["upc"] = upc.upper()


def _call_llm(llm_client, prompt):
    """Call *llm_client* (callable, or an object with .complete/.generate)."""
    if callable(llm_client):
        return llm_client(prompt)
    for method in ("complete", "generate", "chat"):
        fn = getattr(llm_client, method, None)
        if callable(fn):
            return fn(prompt)
    raise TypeError("llm_client must be callable or provide complete/generate")


class OpenAICompatibleClient:
    """Minimal OpenAI-compatible chat client (stdlib only).

    Reads ``OPENAI_API_KEY`` (required), ``OPENAI_BASE_URL`` (default
    ``https://api.openai.com/v1``) and ``OPENAI_MODEL`` (default
    ``gpt-4o-mini``) from the environment.
    """

    def __init__(self, api_key=None, base_url=None, model=None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not set in the environment")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL",
                                                     "https://api.openai.com/v1")).rstrip("/")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    def __call__(self, prompt):
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"LLM request failed: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc.reason}") from exc
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("unexpected LLM response shape") from exc


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def extract_product(text, llm_client=None):
    """Extract a product record from *text*.

    Returns ``(record, meta)`` where ``meta`` is ``{"source": ...}``:
    ``"fallback"`` when no model was used or the model path failed
    (with ``"llm_error"`` explaining why), else ``"llm+fallback"``.
    """
    record = parse_fallback(text)
    if llm_client is None:
        return record, {"source": "fallback"}
    try:
        raw = _call_llm(llm_client, build_prompt(text))
        _apply_llm_record(record, _extract_json(raw))
    except Exception as exc:  # model failure degrades, never loses data
        return record, {"source": "fallback", "llm_error": str(exc)}
    return record, {"source": "llm+fallback"}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract a unified product JSON record from page text.")
    parser.add_argument("--input", help="input text file (default: stdin)")
    parser.add_argument("--output", help="output JSON file (default: stdout)")
    parser.add_argument("--llm", action="store_true",
                        help="use the LLM (needs OPENAI_API_KEY)")
    parser.add_argument("--model", help="override OPENAI_MODEL for this run")
    args = parser.parse_args(argv)

    if args.input:
        with open(args.input, encoding="utf-8") as handle:
            text = handle.read()
    else:
        text = sys.stdin.read()

    llm_client = None
    if args.llm:
        llm_client = OpenAICompatibleClient(model=args.model)
    record, meta = extract_product(text, llm_client)
    output = json.dumps(record, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(output + "\n")
    else:
        print(output)
    print(f"# extraction source: {meta['source']}"
          + (f" (llm_error: {meta['llm_error']})" if "llm_error" in meta else ""),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
