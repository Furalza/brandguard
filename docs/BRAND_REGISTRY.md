# Brand Registry

One CSV lists every brand we protect. The registry turns it into the profile
JSONs the watchlist sweep reads, so adding or removing a brand is a one-line
edit, and a thousand brands cost the same effort as three.

```
data/brands.csv --check--> validated rows --sync--> data/watchlist/<id>.json --> hunt --watchlist
                                           (--enrich: official apps from Google Play, domain-verified)
```

## Daily use

```powershell
python -m brandguard.registry check            # validate + show what would change, writes nothing
python -m brandguard.registry sync             # apply: create / update / remove profiles
python -m brandguard.registry sync --enrich    # also fill official publishers and apps from Play
python -m brandguard.hunt --watchlist data/watchlist --source play,serper
```

- Add a brand: add a row, run `sync`.
- Pause a brand: set `active` to `no`, run `sync` (its profile is removed, the row stays).
- Remove a brand: delete the row, run `sync`.
- Work on a few brands only: `--only isbank,btcturk` (never removes anything).

## Columns

Only `brand_name` and `official_domains` are required. Cells that hold several
values separate them with `|`, so the file works with both `,` and `;`.

| Column | Example | Notes |
|---|---|---|
| id | `isbank` | Profile file name. Default: slug of the brand name. |
| brand_name | `Turkiye Is Bankasi` | Real spelling, Turkish letters welcome. |
| official_domains | `isbank.com.tr` | Pasted URLs are reduced to the host. |
| sector | `banking` | `banking`, `logistics`, `crypto` have a permission baseline; `kargo`, `banka`, `kripto` are accepted aliases. Other sectors work, permission drift abstains and `check` says so. |
| official_publishers | `Turkiye Is Bankasi A.S.` | Exact store publisher string. |
| official_package_ids | `com.pozitron.iscep` | Checked for package-id shape. |
| known_official_apps | `Isbank|Maximum Mobil` | |
| known_affiliates | `isbank.de` | Vetted related domains (K-049). |
| active | `yes` / `no` | Also `evet` / `hayir`. Empty means yes. |
| notes | free text | Ignored by the tool. |

Excel is fine: the file is read whether Excel saved it as UTF-8 or as the
Turkish Windows default (cp1254, `;` separated). A `brand_name` starting with
`#` comments the row out.

## Safety rules

1. **Only generated files are touched.** A profile written by the registry
   carries a `_registry` block. A profile without it (for example a
   hand-tuned `ziraat.json`) is never updated or removed.
2. **No double scanning.** A row whose id or official domain is already covered
   by a hand-maintained profile is skipped and reported.
3. **All or nothing.** Any validation error stops the sync before a file is
   written, so a typo cannot prune the watchlist. A CSV with no active brands
   refuses to remove anything.
4. **Idempotent.** Re-running with the same CSV changes nothing; files are only
   rewritten when their content changes, and each write is atomic.

To take a generated profile under manual control, delete its `_registry` block.

## Enrichment

`--enrich` searches Google Play for the brand and accepts a publisher only when
its developer website or e-mail is under one of the brand's official domains.
Apps from an accepted publisher become official package ids and titles. A
publisher that merely resembles the brand by name is listed under `review` and
never written: the name is attacker-controlled, the domain is not (K-014).

Enrichment is incremental and cached in the profile. A brand is queried again
only with `--refresh` or when its official domains change (the old proof is
then dropped). CSV values always come first; enrichment only adds. After three
consecutive failures (Play down or rate-limiting) enrichment stops for that
run and the remaining profiles are written from the CSV.
