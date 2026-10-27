# Apollo reliability and Daily Debrief 2.0

Implemented in the existing Python/SQLite backend and existing web UI. No navigation tabs were added. Changes have not been deployed.

## Root causes and changes

**Chat images**

- Markdown's inline parser recognized links but not image syntax. It now renders supported HTTP(S) and same-origin image references.
- The media resolver omitted Wikimedia’s standard `upload.wikimedia.org` thumbnail host; it is now included in the narrow source allowlist.
- Structured galleries deleted failed images, hiding the cause. Images now retain a loading/error state and retry control.
- Attachment previews imported Pillow outside their exception handler, although Pillow was not declared in requirements. Preview generation now falls back to the original when appropriate, applies EXIF orientation, writes previews atomically, and supports HEIC through the declared decoder dependency.
- Upload MIME types were trusted. Image signatures now determine the MIME type; reopening a chat also repairs legacy attachment metadata without exposing stored file paths.
- Official Image-Line/Wikimedia assets returned by the existing resolver previously depended on remote URLs. Supported assets are now archived and addressed through private same-origin media URLs. Existing generated local files continue through the durable attachment store.
- Old thumbnail CSS forced crops, and a legacy delegated click handler opened a second lightbox over the new viewer. Both are corrected. Uploads and assistant images share accessible full-screen viewing, keyboard close, focus restoration, and responsive sizing.
- The app continues using its existing private Tailscale network boundary. No new public image proxy or independent authentication mechanism was added. No generative image backend was introduced or claimed.

**Connection health**

- The integration registry previously appeared only in Settings and did not retain a shared health snapshot. Home now shows the latest persisted issues immediately beneath its header, with expandable details and working Settings/OAuth actions.
- Checks use the actual Google Calendar, Canvas, Spotify and WHOOP adapters. Google and WHOOP perform lightweight capability probes, rather than equating an unexpired token with working API access.
- Confirmed authorization problems, unconfigured accounts and transient failures remain distinct. A temporary failure neither creates a reconnect warning nor clears a previously confirmed warning. Successful checks clear resolved issues.
- A persisted backend snapshot, a single-flight lock, 120-second routine checks, and a 10-second forced-check floor bound API work. Browser polling pauses while hidden. OAuth callbacks and Canvas connection changes invalidate the snapshot.
- Definitively revoked Google grants retain a nonsecret reconnect marker after credential cleanup. Spotify permission failures are distinguished from unavailable playback devices. Expired Canvas feeds offer replacement through the existing feed settings flow.
- Spotify has no browser OAuth reconnect endpoint in this repository. Its banner opens Settings and explains that its existing server-managed authorization must be renewed. It does not present a fake OAuth button.

**Water**

- Added 710 mL alongside 150, 250 and 500 mL using the existing hydration API and milliliter storage.
- The previous client generated a new idempotency key for every tap. A pending-operation guard, brief repeat-tap guard, disabled controls and reuse of the key after an uncertain response now prevent duplicate logging.
- The authoritative response refreshes daily intake, progress and history. The four options use a compact two-column layout on iPhone.

**Daily Debrief**

- The research prompt prioritized underground music; the deterministic music weight was 4.5 versus 0.35 for technology/AI. The ranker also rejected most technology stories. Neither calendar nor tasks were supplied to the old generation pipeline. A four-story minimum caused useful partial results to be discarded.
- Generation now builds My Day from actual calendar events and saved tasks, including deadlines, unfinished work, conflicts and busy schedules. Personal observations use those records and, when connected and current, scored WHOOP sleep/recovery records. Stale overnight records are excluded.
- News research emphasizes significant world, economics, business, science, technology, AI, and regional developments. Ranking incorporates significance, evidence-based regional relevance, recency, novelty, source reliability, actionability and persisted feedback.
- Music is limited to one meaningful artist/production update. Actual Spotify artists take priority over the supplied favorite list. Genre-only discovery and music-only fallback packages are excluded, including mislabeled music candidates.
- Articles must pass direct-page checks for a usable HTTPS source, public destination, publication metadata and a matching evidence excerpt. Inaccessible or unverifiable pages are omitted rather than treated as verified because they returned a non-404 status. This is an evidence check, not a guarantee that every model-written sentence is independently fact-checked.
- Duplicate IDs/URLs and near-identical headlines are suppressed. Existing feedback storage was migrated transactionally to retain “More like this,” “Less like this,” and “Not interested”; these affect future selection.
- Stories provide expandable context, dated source links and saved feedback state. Missing/stale data is explicit; unavailable personal integrations link to connection settings.
- The 05:00 local generation gate and original timezone fallback are preserved. A cross-process generation lock, daily upsert, bounded model retries and retry cooldown prevent overlapping jobs, duplicate saved debriefs and tight failure loops. Useful personal sections remain available when news fails; an unsuccessful forced refresh preserves earlier verified news from the same day.

## Verification

- **250 Python tests passed**, including existing regressions and new tests for persistent media, MIME repair, preview fallback, HEIC conversion, health transitions and caching, 710 mL idempotency/history, article date/evidence checks, feedback migration, source failures, generation concurrency, cost throttling and WHOOP freshness.
- **14 iOS configuration/navigation tests passed** with `npm run test:ios-config`.
- JavaScript syntax checks and `git diff --check` passed.
- Browser interactions passed in fresh Chrome profiles at **1440 × 1000** and **390 × 844** with touch/mobile emulation. The fixture runs real Apollo HTTP handlers and SQLite persistence, while external accounts and model responses are controlled test data.
- Browser coverage: banner placement below the header; review navigation; reconnect clearing; transient outages; expandable articles; feedback persisted through the API; rapid water taps producing one 710 mL entry; two file uploads including an incorrect MIME type; inline assistant Markdown images; full-screen viewer and close; conversation switching; page reload; natural image aspect ratios and visible pixels after loading; and useful errors for both remote-style media and missing uploaded attachments.
- Screenshots were inspected for layout and actual image visibility. Test data is deliberately labeled as fixtures.
- HEIC conversion was verified with Pillow 12.3.0 and pillow-heif 1.8.1 installed only in a temporary test directory, within the declared version constraints.

## Files changed

Production:

- `server.py`
- `index.html`
- `apollo_media.py`
- `apollo_genui.js`
- `apollo_genui.css`
- `apollo_health.js` (new)
- `apollo_reliability.css` (new)
- `connection_health.py` (new)
- `routines.js`
- `routines.css`
- `generate_debrief.py`
- `debrief_personalization.py`
- `debrief_context.py` (new)
- `requirements.txt`

Tests and documentation:

- `tests/test_attachment_context.py`
- `tests/test_connections.py`
- `tests/test_debrief_personalization.py`
- `tests/test_debrief_rendering.py`
- `tests/test_genui.py`
- `tests/test_genui_live_pipeline.py`
- `tests/test_debrief_generation_v2.py` (new)
- `tests/test_reliability_v2.py` (new)
- `tests/browser/reliability_fixture.py` (new)
- `tests/browser/reliability.cjs` (new)
- `docs/qa/reliability-v2.md` (this report)

## Deployment and remaining limits

**Ready for staging deployment; not deployed or production-validated.** Install `requirements.txt`, deploy the new Python and frontend assets together, and restart the existing backend. The existing deployment workflow already installs requirements. Feedback migration runs through the existing database initializer. Keep the current scheduler configuration.

Real provider OAuth revocation/reconnection, production reverse-proxy headers/storage permissions, live Hermes web research, and a physical iPhone/Capacitor session still require production-environment verification. Browser tests use fixtures and iPhone dimensions, not a physical iPhone or Safari engine.

Archiving is deliberately limited to sources supported by the existing image resolver. Arbitrary authenticated or expiring third-party image URLs are not mirrored; they retain visible failure states if access expires. Previously deleted upload files cannot be reconstructed. News sites that block fetching, redirect away from the supplied canonical URL, or omit verifiable publication metadata can be excluded; the briefing explicitly reports unavailable news rather than padding it.

To repeat local browser checks, install the Python requirements, make Playwright available to Node, start `python3 tests/browser/reliability_fixture.py`, then run `node tests/browser/reliability.cjs`. Set `CHROME_PATH` for a different Chrome installation, `APOLLO_TEST_URL` for another fixture origin, or `APOLLO_TEST_OUTPUT` for screenshots. The fixture binds only to loopback, uses a temporary database, and never connects to personal accounts.
