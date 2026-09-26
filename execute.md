# ============================================================
# 0) SETUP (once)
# ============================================================
pip install -e ".[dev,live,serper,whois,icons,llm]"   # install project + all optional extras
# .env file in repo root:
#   SERPER_API_KEY=...        # needed for serper / website sources and registry --enrich
#   ANTHROPIC_API_KEY=...     # optional: real LLM adjudicator (otherwise rule-based)

# ============================================================
# 1) BRAND REGISTRY  (data/brands.csv -> data/watchlist/*.json)
# ============================================================
python -m brandguard.registry check                        # validate CSV, show plan, write nothing
python -m brandguard.registry sync                         # CSV -> profiles, offline (no internet)
python -m brandguard.registry sync --enrich                # find missing domains + fill publishers/packages from Play
python -m brandguard.registry sync --enrich --refresh      # re-query brands already resolved before
python -m brandguard.registry sync --enrich --only papara,trendyol   # only these brand ids
python -m brandguard.registry sync --enrich --min-installs 500000    # stricter publisher acceptance
python -m brandguard.registry sync --no-prune              # never delete profiles removed from CSV
python -m brandguard.registry check -v                     # also list unchanged profiles

# ============================================================
# 2) HUNT  (scan sources, saves to results/*.json + results/run_log.csv)
# ============================================================
python -m brandguard.hunt --profile data/watchlist/papara.json --source play          # one brand, Google Play
python -m brandguard.hunt --profile data/watchlist/papara.json --source serper        # one brand, APK sites via Google
python -m brandguard.hunt --profile data/watchlist/ziraat.json --source website       # fake domains via Google dorks
python -m brandguard.hunt --profile data/watchlist/ziraat.json --source crtsh         # fake domains via certificate logs
python -m brandguard.hunt --watchlist data/watchlist --source play,serper             # ALL brands, several sources
python -m brandguard.hunt --brand "Papara" --official-domain papara.com --source serper   # quick test without a profile

# tuning (cost vs coverage)
python -m brandguard.hunt --profile data/watchlist/papara.json --source play --max-queries 20     # more name variants
python -m brandguard.hunt --profile data/watchlist/papara.json --source serper --max-queries 8    # run more APK dorks
python -m brandguard.hunt --profile data/watchlist/ziraat.json --source website --num 20          # more results per query
python -m brandguard.hunt --brand Binance --official-domain binance.com --source crtsh --cap 500 # classify more CT domains

# ============================================================
# 3) RUN.PY  (evaluate a given list of records - THE DEMO COMMAND)
# ============================================================
python run.py --profile data/profiles/ornek_bank.json --records data/demo/cto_records.json --pretty   # readable table
python run.py --profile data/profiles/ornek_bank.json --records data/demo/cto_records.json --pretty --only impersonation  # only takedown candidates
python run.py --profile data/profiles/ornek_bank.json --records data/demo/cto_records.json > results/cto_sonuc.json      # save JSON output
python run.py --profile data/profiles/ornek_bank.json --records data/demo/cto_records.json --official-icon data/mock_icons/official.png --pretty  # enable T1 icon check

# ============================================================
# 4) EVALUATION & CHECKS
# ============================================================
python scripts/evaluate.py                                   # metrics on test set (FP, recall, calibration, tier cost)
python scripts/run_cascade.py data/profiles/ornek_bank.json  # gold vs system label, uses real LLM if key is set
python scripts/run_cascade.py data/profiles/ornek_bank.json --json   # same, JSON output
python scripts/inspect_brand.py "Papara"                     # live Play check: first line should be com.mobillium.papara
python scripts/inspect_brand.py "Papara" --hits 20           # show more Play results

# before/after comparison for any code change
git stash; python scripts/evaluate.py > eval_before.txt; git stash pop
python scripts/evaluate.py > eval_after.txt
git diff --no-index eval_before.txt eval_after.txt           # empty = metrics unchanged

# ============================================================
# 5) TESTS & LINT
# ============================================================
pytest -q                          # run all tests (expect 237 passed)
pytest tests/test_registry.py -q   # only registry tests
pytest -k veto -q                  # only tests with "veto" in the name
ruff check .                       # lint
ruff check . --fix                 # auto-fix lint issues

# ============================================================
# 6) TEST DATA GENERATORS (rarely used)
# ============================================================
python scripts/generate_redteam.py data/profiles/ornek_bank.json --count 25   # LLM plays attacker -> data/testset/redteam/
python scripts/make_test_icons.py                                            # synthetic icons -> data/mock_icons/

# ============================================================
# 7) LEGACY single-source scripts (replaced by hunt, kept for history)
# ============================================================
python scripts/watchlist_scan.py                       # old Play-only watchlist scan (-> hunt --source play)
python scripts/watchlist_diff.py old.json new.json     # compare two watchlist_scan results
python scripts/scrape_and_triage.py --brand Papara     # old one-brand Play scan
python scripts/serper_hunt.py --profile data/watchlist/papara.json   # -> hunt --source serper
python scripts/website_hunt.py --profile data/watchlist/ziraat.json  # -> hunt --source website
python scripts/crtsh_hunt.py --profile data/watchlist/ziraat.json    # -> hunt --source crtsh

# ============================================================
# 8) GIT (usual flow)
# ============================================================
git checkout -b feat/my-change
git add -A
git commit -m "feat: short description"
git checkout main; git merge feat/my-change; git push


# 1. In Explorer: overwrite the src\ and web\src folders from the zip.
#    Never touch .env (keys, password) or data\ (database, profiles).

# 2. Rebuild the image and replace the running container.
#    The old container stops automatically; the database is kept.
docker compose up --build -d

# 3. Check: STATUS must say "Up", log must end with "Application startup complete".
docker compose ps
docker compose logs --tail 20


# One-time: make sure .env has a login line, e.g.
#   BRANDGUARD_BASIC_AUTH=demo:StrongPassword
# If you just added it, run step A2 again so the container picks it up.

# Open the tunnel in a SEPARATE PowerShell window and keep it open.
# The output prints an address like https://xxxx-xxxx.trycloudflare.com — send that.
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8000

# Stop sharing: press Ctrl+C in that window. The address dies immediately;
# the next run gets a new address.


docker compose down      # stop the app completely
docker compose up -d     # start again without rebuilding (no code change)
docker compose logs -f   # live log; Ctrl+C to leave