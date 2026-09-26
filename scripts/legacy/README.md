# Legacy single-source scripts

These scripts predate the unified hunt engine (K-042) and are kept for history
and for quick one-source experiments. Day-to-day scanning goes through:

    python -m brandguard.hunt --profile data/watchlist/<brand>.json --source play,serper,website,crtsh

or the product API. Notes:

- `watchlist_scan.py` / `watchlist_diff.py` write and read their own result
  shape (`verdicts`, `platform`); they do not read `hunt` output. The product
  database replaces both.
- `serper_hunt.py`, `website_hunt.py`, `crtsh_hunt.py`, `scrape_and_triage.py`
  are the one-source predecessors of the engine runners and do not pass
  `known_affiliates`, so vetted affiliates can show as lookalikes here.
