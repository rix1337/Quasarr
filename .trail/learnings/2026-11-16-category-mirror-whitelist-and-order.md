---
title: The category whitelist decides which mirrors are used, its order which comes first
author: Quasarr
date: 2026-11-16
touches:
  - quasarr/search/sources/templates/wx/download.py
  - quasarr/search/sources/templates/sf/download.py
  - quasarr/search/sources/templates/sf/search.py
  - quasarr/downloads/__init__.py
  - quasarr/downloads/mirror_filters.py
  - quasarr/api/captcha/__init__.py
  - quasarr/api/sponsors_helper/__init__.py
  - quasarr/search/sources/helpers/custom_source.py
  - quasarr/search/sources/templates/hs.py
  - quasarr/search/sources/templates/fx.py
  - quasarr/search/sources/templates/dl/download.py
---

## Decided

Prefer source-provided green container signals, pass the chosen link set to JDownloader, and let JDownloader own premium hoster verification.

Why: Direct probing cannot reliably distinguish a live premium link from a deleted file that still answers successfully. A green container signal remains the strongest available source evidence, even when resolving it may require CAPTCHA. Dead selections are deliberately reported through JDownloader failure so the *arr client can blacklist and retry. When source signals provide no usable recency or liveness evidence, the fallback may choose the first eligible option without pretending it was verified.

The download category's mirror whitelist decides which mirrors are used, and its order only decides which comes first. Every whitelisted mirror a release offers is passed on, for redundancy, in priority order: CAPTCHA pages and SponsorsHelper open the top mirror first, and final links reach JDownloader sorted by priority. A user who does not want a secondary mirror leaves it off the whitelist. Ranking goes through one shared helper that understands mirror labels, hoster aliases, and URLs, so CAPTCHA ordering, SponsorsHelper, per-source selection, and the final check agree.

Why: Multiple mirrors let JDownloader fall back when one hoster fails. Sending only the top-priority mirror was tried and rejected for that reason.

## Watch out

WX selection never merges unrelated mirror uploads or invents direct-link liveness; it preserves source evidence and hands terminal failures back to the *arr retry path. Among uploads in the same tier, one carrying a higher-priority hoster wins before online-hoster count.

Search must not pin one mirror's link into the download payload when the source lists several mirrors per release; pass the release page so the download step can apply the whitelist and order. Pinning the first listed mirror bypassed the whitelist and caused a 1fichier pick despite a rapidgator-only category.

Some sites label crypter links only generically, as "filecrypt" or link text. Where labels are generic (HS, DL, SF's unlabelled fallback, the template engine), a link that names no known hoster passes the source-side whitelist and the final check filters its decrypted links; dropping it early lost valid releases. Sites that name hosters explicitly (WX, DD, DW, WD, BY) keep the strict check, since an unknown name there is a real hoster outside the whitelist. A site that always uses one hoster declares it as `only_mirror` in its download settings (FX: rapidgator): its generic links carry that name, and a category that excludes it fails before any CAPTCHA, as the per-source supported-mirror lists did before categories owned mirrors.
