# Music history and recap local QA — 2026-10-27

The Music history implementation is local and undeployed. The development fixture uses five synthetic September listens in a temporary SQLite database; no personal Spotify account or export was used. The [Insights screenshot](music-insights-local-2026-10-27.png) shows the populated desktop view with provider attribution and search links for records without IDs. The [attributed Square recap screenshot](music-recap-attributed-square-local-2026-10-27.png) shows the official Spotify logo and source URL in the graphic. Story and Square previews for all three slides were inspected in the browser.

Verification after the last source change:

- `DEVELOPER_DIR=/Library/Developer/CommandLineTools PYTHONPYCACHEPREFIX=/private/tmp/apollo-pycache PYTHONPATH=/private/tmp/apollo-test-deps:. python3 -m unittest discover -s tests -p 'test_*.py' -q`: 333 run, 331 passed, 2 skipped. Pillow was installed in temporary test dependencies because the baseline environment lacked it.
- `npm run test:ios-config`: 15 passed, including ZIP integrity and extracted PNG bytes for three slide entries.
- `npm run build`: passed; iOS web assets prepared.
- `node --check apollo_music_insights.js` and `git diff --check`: passed.
- Local HTTP checks: import, re-import idempotency, invalid-file rollback, monthly summary, missing write header, and empty-recap rejection passed.
- In the in-app browser on the local fixture, verified light and dark Music Insights, empty and populated months, recent-listening rows, recap story and square previews, second slide, Chat logo, and web deep links. A downloaded Story PNG was verified as 1080 × 1920. The ZIP writer was verified by the Node test, but a browser ZIP download was not independently captured.

The fixture is not a live-provider acceptance test. Spotify OAuth refresh, actual playback and queue behavior, metadata endpoint access, real artwork CORS, Google Calendar, Canvas, WHOOP, a physical iPhone, and production health still need environment-specific checks. The iOS simulator could not be run because this machine's Xcode license has not been accepted. The recent Music UI was not inspected at a narrow mobile viewport. Deployment requires an exact prepared release, verified backup/rollback rehearsal, and production SSH access as described in `../architecture/production-deployment.md`.
