# BrandGuard console — user guide

BrandGuard finds mobile apps and APK downloads that impersonate, repackage or
ride on a brand, and sorts every finding into a category with its reasons.
This guide is for the person using the console; setup and operations are in
`RUNBOOK.md` (local Docker) and `DEPLOY.md` (server).

## 1. Signing in

Open the address you were given (locally `http://127.0.0.1:8000`, or a
`https://….trycloudflare.com` link). The browser asks for a user name and
password once per session; they come from whoever runs the console.

The header shows what is running: the **Reader** chip (which language model
reads listing text, or "rules only"), **APK sites** (whether web search is
configured), a **running** badge while scans are in progress, and, when the
console is shared through a tunnel, its **public link** with a copy button.
The moon/sun button switches light and dark theme.

## 2. Starting a scan

**New scan** is the first page. Choose **One brand** or **Several brands**
at the top of the form.

### One brand

Three fields; any one is enough, all three give the most exact result:

| Field | What it does |
|---|---|
| **Brand name** | What the brand is called. Alone, the system resolves the identity from two independent sources and marks the profile "needs review". |
| **Official domain** | The trust anchor. Apps whose publisher site is on this domain are the brand's; lookalike domains are measured against it. |
| **Google Play link** (or package id) | Marks that app as the brand's own; its publisher name and Play developer account join the profile, so the brand's other apps are recognised too. |

Typed facts are merged into an existing brand profile, so re-scanning with
more detail improves the profile rather than creating a duplicate.

**Sources**: Google Play (store listings), APK sites (Google search across
third-party APK mirrors and mod sites; needs a Serper key), Websites
(lookalike domains) and Certificate logs. Play + APK sites is the usual
choice.

**Depth**: Quick (a preview in about a minute, few queries), Normal (the
daily scan), Deep (priority brands; more queries, more credits).

### Several brands

One brand per line. A line may be a name, a domain, a Play link, or all
three separated by `|`:

```
Papara | papara.com | com.mobillium.papara
Trendyol | trendyol.com | trendyol.com
tiktok | tiktok.com | com.zhiliaoapp.musically
```

Every line becomes its own scan; a **batch page** follows them together
with a progress bar, totals, per-brand rows, **Export all (ZIP)** and
**Cancel remaining**. A line that cannot be scanned (for example a store
field that is neither a Play link nor a package id) is listed under "inputs
not scanned" and stays there after a reload.

## 3. Reading a scan

The scan page has four parts, top to bottom.

**Source cards** — one per source with candidates found, threats, duration,
and a "notes" fold with anything worth knowing: a throttled query, how many
listings the reader read, whether the brand word turned out to be shared
with other products. A failed source can be retried alone.

**Counters** — one tile per category. Click a tile or a tab to filter.

**Tabs and table** — *Needs action* (open malicious and suspicious rows),
*New* (keys first seen in this scan, when a previous scan exists), the six
categories, and *All*. Filter by source, search by name or package, and
tick **Hide mirror copies** to set aside unauthorised copies of the brand's
own app on mirror sites.

Every row has **Why?** (the explanation opens under the row) and
**Details** (the same in a side panel, with a store link).

**Since the previous scan** — what appeared, disappeared or changed
category compared with the last scan of the same brand.

### Categories

| Category | Meaning | What to do |
|---|---|---|
| **Malicious** | Takedown candidate: an impersonation backed by evidence outside the attacker's control (a very young publisher account, permission drift), or a modified/cracked build of the brand's app. | Confirm, then send the takedown; mark **Takedown sent**. |
| **Suspicious** | Something is wrong but not proven: a brand-shaped name, a claim of officialness, or a copy of the brand's app on a mirror site that cannot be verified without a signature check. | A person decides. Mirror copies can be hidden with the toggle. |
| **Official** | The brand's own listing: an official package id on Play or the App Store, a verified publisher, or the same developer account as a verified app. | Nothing. |
| **Affiliate?** | Probably the brand's own regional or subsidiary app (publisher name or site carries the brand, identity not yet verified). | If it is the brand's, **Add to profile**: the next scan verifies it as official. |
| **Related** | A third-party tool about the brand (downloader, calculator, guide, fan app) that does not pose as the brand. | Usually nothing; a review if it oversteps. |
| **Noise** | Unrelated: a namesake, a page that is not an app listing, the brand's own website. | Nothing. |

The system never calls an app malicious on words alone: the rule is written
under every suspicious row. A wrong takedown request costs more than a
missed one.

### Why this decision?

The explanation has: **In short** (one paragraph), the listing's facts
(publisher, installs, developer site, dates), the evidence grouped into
*Decided on its own* / *Points to a threat* / *Points to legitimacy* /
*What the listing text says (read by the model)* / *Context*, the listing
text itself (marked untrusted), and the **Decision path** (which tier
decided and why). "Show engine text" reveals the raw evidence lines.

The model's lines describe what the listing text says (the brand's own app,
a companion tool, a namesake, whether it claims to be official or asks for
credentials, a quote). The model never decides the category; the rules do.

### Your decisions

Under the explanation, **Review** records what you decided: *Confirmed*,
*Takedown sent*, *Resolved*, *False positive*, with a note. Decisions are
kept per brand and per app, so the same package id in tomorrow's scan
carries yesterday's decision and leaves *Needs action*.

### Buttons on the scan page

*Cancel scan* (while running; collected results are kept), *Export JSON*
(the whole scan for sharing), *Scan again* (the same input, prefilled),
*Delete* (the scan and its findings; the brand and your reviews stay),
*Retry failed sources*.

## 4. Scans list

All scans, 50 per page, newest first. Filter *All / Running / Needs
attention / In a batch*, search by brand or input. Each row opens the scan;
running scans can be cancelled here, finished ones deleted. A batch id
links to the batch page.

## 5. Brands

One row per brand profile: official domains, publishers, number of
official packages, where the profile came from (typed, CSV, resolved
automatically), status (*ready* or *needs review*), schedule and last scan.
**Scan now** runs the brand with its saved profile; **Delete** removes the
brand with all its scans.

The brand page shows and edits the profile: domains, publishers, package
ids, known apps, affiliates. A profile resolved automatically from a name
is marked *needs review* with the notes that say why; **Save as reviewed**
makes it authoritative. **Scheduled re-scan** runs the brand daily or
weekly with the chosen sources and depth while the server is up; scheduled
scans are marked in the list.

## 6. A working routine

1. Scan with all three fields for each brand you protect.
2. On the brand page, add regional apps from *Affiliate?* to the profile
   once; confirm the profile.
3. Work *Needs action*: confirm real threats, mark false positives, hide
   mirror copies unless mirror distribution is what you chase.
4. Turn on a weekly schedule; check *New* and *Since the previous scan*.
5. Export JSON when someone outside the console needs the evidence.

## 7. Limits worth knowing

- A copy of the brand's app on a mirror site stays *Suspicious*: without a
  signature check nobody can say the APK is untouched.
- A dictionary-word brand (Wise, Getir) produces more *Suspicious* rows;
  the console measures how shared the word is and reads the listings, but
  a person still closes the ambiguous ones.
- Google Play is read through an unofficial interface; a throttled query
  shows as a note on the source card and can be retried.
- Scheduled scans run only while the server runs.
