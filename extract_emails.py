#!/usr/bin/env python3
"""Extract and deduplicate email addresses from a text or HTML file.

Usage:
    python extract_emails.py input.html [-o output.txt]
    python extract_emails.py input.txt --stdout

Notes:
  * Matching is regex-based (practical RFC-5322-lite pattern), lowercases
    addresses, strips trailing punctuation, and unwraps simple
    "name [at] domain [dot] com" obfuscation.
  * Output order is first-seen order; duplicates are removed.
"""

import argparse
import re
import sys
from pathlib import Path

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)

# Common obfuscation used on web pages: john [at] example [dot] com
# Bracketed markers are required on purpose: bare " at " / " dot " also
# occur in ordinary prose ("the founder at jane.doe ...") and would
# produce false positives.
_OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9._%+-]+)\s*(?:\[\s*at\s*\]|\(\s*at\s*\))\s*"
    r"([A-Za-z0-9-]+(?:\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\))\s*[A-Za-z0-9-]+"
    r"|\.[A-Za-z0-9-]+)+)",
    re.IGNORECASE,
)
_DOT_MARKER_RE = re.compile(r"\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\))\s*",
                            re.IGNORECASE)

_TRAILING_JUNK = ".,;:!?'\")>]"


def deobfuscate(text: str) -> str:
    """Turn 'name [at] example [dot] com' into 'name@example.com'."""

    def _sub(match):
        local, domain = match.groups()
        domain = _DOT_MARKER_RE.sub(".", domain)
        return f"{local}@{domain}"

    return _OBFUSCATED_RE.sub(_sub, text)


def extract_emails(text: str) -> list[str]:
    """Return deduplicated, lowercased emails in first-seen order."""
    text = deobfuscate(text)
    seen = set()
    emails = []
    for match in EMAIL_RE.finditer(text):
        email = match.group(0).strip(_TRAILING_JUNK).lower()
        if email not in seen:
            seen.add(email)
            emails.append(email)
    return emails


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract and deduplicate email addresses from a file."
    )
    parser.add_argument("input", help="Text or HTML file to scan")
    parser.add_argument(
        "-o", "--output",
        help="Write results here (one per line). Default: <input>.emails.txt",
    )
    parser.add_argument(
        "--stdout", action="store_true",
        help="Print results to stdout instead of writing a file",
    )
    args = parser.parse_args(argv)

    source = Path(args.input)
    if not source.is_file():
        print(f"error: no such file: {source}", file=sys.stderr)
        return 2

    text = source.read_text(encoding="utf-8", errors="ignore")
    emails = extract_emails(text)

    if args.stdout:
        print("\n".join(emails))
    else:
        target = Path(args.output) if args.output else source.with_suffix(
            source.suffix + ".emails.txt"
        )
        target.write_text("\n".join(emails) + ("\n" if emails else ""),
                          encoding="utf-8")
        print(f"{len(emails)} unique email(s) written to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
