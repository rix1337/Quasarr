# Mirror Selection

How Quasarr decides which mirror / link set to hand to JDownloader when a
release exposes more than one. This is a product-wide policy; per-source
specifics live in the matching `sources/*.md` file.

## The flow

Quasarr makes the best possible decision from the signals a source provides,
hands the result to JDownloader, and stops there:

```
Quasarr picks the best link set from the source's own signals
  (never by inspecting the direct links themselves)
    -> JDownloader resolves and downloads
      -> if it fails, Quasarr reports the failure
        -> Radarr/Sonarr decide, usually blacklist + next release
```

Resolving and verifying a hoster link is JDownloader's job, not Quasarr's.

## Scope boundary (hard rule)

Quasarr does **not** verify whether a direct hoster link is online. File
availability is JDownloader's responsibility, a dedicated and paid operation
with hoster-specific handling Quasarr cannot and should not replicate. Quasarr
only *selects* links from the metadata a source already provides; it never
fetches a hoster URL to probe its liveness.

A link that turns out to be dead is therefore not a selection bug. It is
absorbed by the flow above: JDownloader marks it offline, Quasarr surfaces the
failure, and Radarr/Sonarr blacklist the release and pick the next one.

## Selection priority

Rank by the link set whose online status the source actually certifies. A
source's status signal (for example WX's badges in `options.check`) describes
the crypted **container**, not the separately uploaded direct links, so a
certified-online container outranks a direct link the signal does not describe.
General order:

1. **Online-certified crypted container, cheapest crypter first.** hide resolves
   automatically without a CAPTCHA; filecrypt is handed to JDownloader and may
   cost a CAPTCHA. So: green hide container, then green filecrypt container.
2. **Direct links carrying a green signal.** Best effort only: the green signal
   really measures the container, so for direct links it is a guess.
3. **First offline-flagged mirror, as a last resort,** so the release is still
   attempted and fails cleanly into the blacklist-and-retry path.

If a source exposes no online signal at all, fall back to newest mirror first
(when recency is known), then the first/arbitrary mirror.

Never add a tier that fetches a direct hoster URL to test it. That is out of
scope at every level of this list.

## Why containers rank above direct links

The status signal certifies the container, not the direct links. Measured on WX,
the direct links agree with their container about 95% of the time, but roughly
5% are dead under a green badge because the direct file is a separate upload
that rotted independently of the still-online container (see
[WX](sources/WX.md)).

Choosing the certified container instead trades CAPTCHA-free convenience on
filecrypt mirrors for links that are actually online. That trade is deliberate:
an online download that costs a CAPTCHA beats a fast download that is dead. hide
containers cost nothing because they auto-resolve, so they always come first.

The remaining all-offline case is left to the flow above. Manually clicking a
still-online link in a browser will always beat any automated choice for a
single release; that is not a signal Quasarr can generalize from, and it is not
a reason to start probing links.
