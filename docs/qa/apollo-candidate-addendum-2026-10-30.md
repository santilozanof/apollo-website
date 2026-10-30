# Apollo candidate QA — 30 October 2026

This report covers the candidate built on production revision
`af3bd5d088e6d0e53a991a4bc29fe25859950105`. Production remains at that
revision until the documented fresh backup, restore, exact-SHA readiness and
GitHub Actions gates pass. The test-only credentials and restored databases
used below were never committed or written to production.

## Implemented

- One compact, progressive unlock component serves Private Response and
  Private History. It retains passkey, passphrase, one-time recovery, relock
  and server-side authorization.
- Home uses a compact Quick Access card without querying or displaying private
  History. Registered routes open New Chat, protected History, University
  assignments in Tasks, and Music Insights. Structural colors use neutral
  grayscale tokens, with a single rounded outer focus treatment for embedded
  Home and Chat inputs.
- Chat renders server-derived Music Insights rankings as a strict `apollo-ui`
  MediaRanking block. The server owns period, metric, rank, links and artwork;
  the model cannot forge this block. Existing free-form Chat behavior handles
  compound requests.
- Music Insights defaults to verified milliseconds from imported Extended
  Streaming History. Recent-play events without `ms_played` remain recorded
  events with unknown duration. Playback observations appear separately as
  estimates, with verified overlap removed. Charts, rankings, recaps and Chat
  rankings use the same verified-time basis. Spotify art enrichment uses the
  current single-track metadata endpoint and exact-ID official oEmbed
  fallback, accepting only known Spotify image hosts.
- Spotify recent-play sync pages back to its stored cursor, records uncovered
  windows instead of silently claiming complete coverage, and commits cursor
  and events together. Artwork enrichment gives priority to recent and
  frequent missing covers.
- The production Amy Winehouse regression was a locked Private Chat request
  answered in public-only mode. The prior answer existed, but the deployed
  public-only path sent no preceding turns. Public-only replies now carry only
  explicitly marked public turns. Completed legacy public jobs are recovered
  only when their saved answer uniquely matches an adjacent user/assistant
  pair; private turns are never tagged. The Hermes adapter also no longer
  sends a random `X-Hermes-Session-Id` on stateless internal requests, because
  that header makes Hermes replace the submitted history with stored history.

## Real-record music reconciliation

Read-only restored production snapshot from 30 October 2026, 14:30 local:
246,391 listening events, including 246,100 Extended History events and 291
recent-API events. Of the API events, 270 lack playback duration. The snapshot
passed `PRAGMA quick_check`. On 29 October, it held 76 recent-API events,
0 verified minutes and 136.9 minutes of observed, incomplete progress.

For 26 October–1 November the snapshot covers only through 30 October:
680 events, 513.4 verified minutes, 290.5 observed estimate minutes and 270
unknown-duration events. The user's official Spotify figure of 1,241 minutes
is for the *complete* reporting week and cannot be equated to this partial
snapshot. No value was hardcoded to match it. Direct read-only SQL agreed with
the daily, weekly, monthly and lifetime verified totals and chart bin sums.
The lifetime snapshot had 391,644.1 verified minutes and 290.5 observed
estimate minutes; the all-time summary ran in about 2.9 seconds after a
measured 20.5-second baseline. Original import rows were not changed.

Spotify's recently-played API exposes `played_at` and catalog `duration_ms`,
but not actual played milliseconds. Spotify Extended History does carry
actual played milliseconds. Stats.fm's documented default import filtering
excludes short or skipped streams, so its totals can differ from Apollo's
all-recorded-events view even with identical source data. No connected
stats.fm dataset was available for account-level numerical comparison.
References: [Spotify recent plays](https://developer.spotify.com/documentation/web-api/reference/get-recently-played),
[Spotify export fields](https://support.spotify.com/am/article/understanding-your-data/),
[stats.fm import rules](https://support.stats.fm/docs/import/),
[stats.fm sync behavior](https://support.stats.fm/docs/streams/sync/).

## Conversational evaluation

Production metadata for the exact reported turn shows the previous assistant
message was saved, not hidden by memory filtering, and both turns had
`public_only=1`. The privacy policy has protected Chat and History enabled.
The old public-only request therefore omitted the previous answer by design.

Twenty newly written synthetic conversations covered slang, sarcasm,
corrections, vague references, factual follow-ups and clear topic changes.
Answers from deployed public-only Luna, candidate public-only Terra, and a Sol
reference were shuffled before human qualitative scoring (0 = lost/wrong
context, 1 = partial, 2 = coherent and grounded). Scores were 18/40,
36/40 and 36/40 respectively; the old route lost context on 9 of 20 cases,
and the candidate on 1. Median model completion times were 1.87, 4.22 and
2.45 seconds. The exact Amy reaction was misread by the old path and
interpreted correctly by the candidate. One public-only case about missing
personal listening minutes remained unresolved, appropriately requiring
private verification.

A separate 20-case ordinary-Chat comparison *with* history showed 36/40 for
deployed Luna, 35/40 for proposed Terra and 36/40 for Sol; changing every short
follow-up to Terra had no demonstrated quality benefit and doubled median
completion latency. The candidate retains normal Chat's fast model route and
fixes the proven public-only and internal-request context failures instead.
These are synthetic model observations, not a claim that all live production
Chat conversations now work.

## Verification

- Python suite: 449 tests passed, 2 skipped. macOS system Python lacks
  `hashlib.scrypt`; tests used an isolated test-only compatibility layer that
  calls the real `cryptography` Scrypt KDF. Production crypto code was not
  changed.
- iOS configuration tests: 17 passed. Production asset build passed.
- Python compile, JavaScript syntax and `git diff --check` passed.
- On a restored 294 MB Apollo database copy, candidate migration ran twice;
  the previous backend migration then ran, `PRAGMA integrity_check` returned
  `ok`, and original `chats`, `messages` and `app_state` row hashes matched.
  The previous backend served `/api/chats` and `/api/memory` with HTTP 200
  from the migrated isolated copy. This is a local rollback compatibility
  rehearsal, not a fresh production-backup restore test.
- Browser fixtures exercise MediaRanking streaming, persistence, links,
  artwork failure and mobile/themes; Home Quick Access, no protected History
  fetch, navigation and neutral focus styling; and shared privacy unlock
  passkey/passphrase/recovery/cancellation/relock flows. These use synthetic
  local data and a test-only setup token.

## Release gates still required

The old `af3bd5d` server backup and its independent Mac restore remain
preserved. They cannot serve as the fresh backup or exact-SHA readiness
manifest for this candidate. Production has only about 400 MB free on its
38 GB root filesystem; the existing verified backup must remain intact.
A separate inactive October 21 restore-test copy is being archived privately
to the Mac before any server-space recovery. After the archive is verified,
the operator must obtain a fresh consistent private production backup,
verify an independent off-server restore, rehearse this exact candidate's
migration and previous-backend rollback on that restored backup, record the
model fingerprint, create `/root/apollo-deployment-ready.json` for the final
commit SHA, and pass the deploy script preflight. Only then may `main` be
updated and the GitHub Actions production workflow run.
