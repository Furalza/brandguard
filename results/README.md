# Scan results

Timestamped output of `scripts/watchlist_scan.py`. One JSON file per brand per
scan, named `<UTC timestamp>__<brand>__<platform>.json`.

Raw result files are git-ignored: they contain real publisher data and grow with
every scan. Only `run_log.csv` (a non-sensitive summary: when, which brand, which
platform, how many candidates) is committed, so the scanning history is visible
without exposing the raw data. A hand-picked representative run for the demo
lives under `docs/sample_runs/`.

To compare two scans of the same brand:

    python scripts/watchlist_diff.py results/<older>.json results/<newer>.json
