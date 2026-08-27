"""Generate red-team variants for a brand profile.

Usage:
    python scripts/generate_redteam.py data/profiles/ornek_bank.json --count 25

Output goes to data/testset/redteam/<brand>.json for manual review.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brandguard.eval.redteam import generate, save
from brandguard.schema import BrandProfile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("--count", type=int, default=25)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    with args.profile.open(encoding="utf-8") as fh:
        profile = BrandProfile(**json.load(fh))

    kwargs = {"model": args.model} if args.model else {}
    variants = generate(profile, count=args.count, **kwargs)
    out = Path("data/testset/redteam") / f"{args.profile.stem}.json"
    save(variants, out)
    print(f"wrote {len(variants)} variants to {out}")


if __name__ == "__main__":
    main()
