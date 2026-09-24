# Brand Registry

One CSV lists every brand we protect. The registry turns it into the profile
JSONs the watchlist sweep reads, so adding or removing a brand is a one-line
edit, and a thousand brands cost the same effort as three. A row can be just
the brand name: `sync --enrich` finds the official domain, publishers and apps.

```
data/brands.csv --check--> validated rows --sync--> data/watchlist/<id>.json --> hunt --watchlist
                             (--enrich: official domain from Google + Play, then official apps from Play)
```

## Daily use

```powershell
python -m brandguard.registry check            # validate + show what would change, writes nothing
python -m brandguard.registry sync             # apply: create / update / remove profiles
python -m brandguard.registry sync --enrich    # look up domains, publishers and apps online
python -m brandguard.hunt --watchlist data/watchlist --source play,serper
```

- Add a brand: type its name on a new line, run `sync --enrich`.
- Pause a brand: set `active` to `no`, run `sync` (its profile is removed, the row stays).
- Remove a brand: delete the row, run `sync`.
- Work on a few brands only: `--only isbank,btcturk` (never removes anything).

## Columns

Only `brand_name` is required. Anything you do fill in always wins over what is
looked up online. Cells that hold several values separate them with `|`, so
the file works with both `,` and `;`.

| Column | Example | Notes |
|---|---|---|
| id | `isbank` | Profile file name. Default: slug of the brand name. |
| brand_name | `Turkiye Is Bankasi` | Real spelling, Turkish letters welcome. |
| official_domains | `isbank.com.tr` | Discovered when empty. Pasted URLs are reduced to the host. |
| sector | `banking` | Optional; default `unknown`. `banking`, `logistics`, `crypto` have a permission baseline (`kargo`, `banka`, `kripto` accepted); for other sectors permission drift abstains and `check` says so. |
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

## Domain discovery

For a row without `official_domains`, `--enrich` finds the official domain from
two independent sources: one Google search (Serper, `SERPER_API_KEY` in `.env`)
and one Google Play search. Accepted, strongest first:

| Method | When | Review note |
|---|---|---|
| `google+play` | Google's knowledge panel matches the developer site of the brand's Play app, or a top result about the brand does and that Play app has 100k+ installs | no |
| `google_knowledge_panel` | only Google's knowledge panel has a website | yes |
| `play_popular_app` | only Play: developer site of an app with 1M+ installs that carries the full brand name | yes |

Otherwise the brand is skipped (`? skip-no-domain`) and nothing is guessed: a
wrong official domain would make the veto trust an impersonator. Social
networks, stores, encyclopedias and free mail providers never count as a brand
site. The proof is stored under `_registry.discovery` in the profile; a
review note is printed once, when the domain is first found. Typing the domain
into the CSV confirms it and replaces the discovered one. Without a Serper key
only the Play rule is available.

## Enrichment

`--enrich` searches Google Play for the brand. A publisher is accepted only when
both hold:

1. its developer website or e-mail is under one of the brand's official domains, and
2. one of its apps in the results has at least 100,000 installs (`--min-installs`).

Play's website and e-mail fields are typed in by the developer, so the first
condition is only a claim; an impersonator can copy it. Organic install volume
is what an impersonator cannot produce, so the claim counts only with it
(K-055). All apps of an accepted publisher then become official package ids and
titles, including its small ones. A publisher that claims the domain without an
established app, or merely resembles the brand by name, is listed under
`review` with the reason and never written. If it is genuine, type it into
`official_publishers` in the CSV.

Discovery and enrichment share one Play search per brand and are cached in the
profile. A brand is queried again only with `--refresh`, when its official
domains change (the old proof is then dropped), or while its domain is still
unresolved. CSV values always come first; lookups only add. After three
consecutive failures (a source down or rate-limiting) online lookup stops for
that run; the remaining brands use the CSV and the cache, and a brand that was
resolved before keeps its profile.
