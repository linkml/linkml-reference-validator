"""Time repeated matching against a local UTF-8 document, without network access.

Run the same script and input with each checkout's package on PYTHONPATH:
    uv run python benchmarks/repeated_quotes.py /path/to/cached/publication.md

Only successful matching is timed; this is a CPU microbenchmark, not end-to-end
CLI validation. It includes each validator's first normalization of the body.
"""

import argparse
import json
import re
from pathlib import Path
from statistics import median
from time import perf_counter

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import SupportingTextValidator


def main() -> None:
    """Report median time to match evenly spaced literal excerpts from a document."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--quotes", type=int, default=100)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    content = args.document.read_text(encoding="utf-8")
    # Each query is taken verbatim from the source; avoid editorial-bracket and
    # ellipsis syntax, which would change what the matching API searches for.
    candidates = [m.group() for m in re.finditer(r"[\w ,;:-]{30,100}", content)]
    if args.quotes < 1 or args.rounds < 1 or not candidates:
        parser.error("positive --quotes/--rounds and a document with prose are required")
    quotes = [candidates[i * len(candidates) // args.quotes] for i in range(args.quotes)]
    reference = ReferenceContent(reference_id="TEST:benchmark", content=content)
    elapsed = []
    for _ in range(args.rounds):
        validator = SupportingTextValidator(ReferenceValidationConfig())
        start = perf_counter()
        for quote in quotes:
            if not validator.find_text_in_reference(quote, reference).found:
                raise SystemExit(f"Excerpt unexpectedly failed validation: {quote!r}")
        elapsed.append(perf_counter() - start)
    print(json.dumps({"characters": len(content), "quotes": len(quotes),
                      "rounds_seconds": elapsed, "median_seconds": median(elapsed)}))


if __name__ == "__main__":
    main()
