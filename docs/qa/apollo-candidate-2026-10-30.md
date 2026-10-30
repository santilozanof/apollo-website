# Apollo candidate QA — 30 October 2026

## Candidate state

- Worktree: /private/tmp/apollo-overhaul-release-601f671, branch codex/apollo-design-system.
- Base revision: c231f0c78348923fa208c0a8810323ce5257d9f4. The final candidate SHA is the committed branch HEAD, recorded separately after commit.
- Production was checked read-only and remains at the base SHA.
- The original /Users/Santi/Documents/apollo-website checkout was not changed by this candidate.

## Verification

- Python: 432 tests passed, 2 skipped, on isolated local SQLite after the application-awareness, music-scope, and prompt-routing changes. This macOS Python lacks hashlib.scrypt; the test runner used a test-only PBKDF2 shim. Production hashing was not substituted.
- iOS configuration: 17 passed.
- JavaScript syntax (modified external modules), Python compilation, and git diff --check passed.
- iOS production asset build passed.
- Mobile Chrome fixture: private Chat displayed an inline verification card. Cancel left a locked response with a working retry control. History cancel stayed locked. No page errors or horizontal overflow. Fixture authentication used a synthetic token and isolated database.
- Existing desktop and iPhone browser fixtures: Home artwork, queue overlay, response actions, Settings disclosures, connection controls, History and themes passed. A separate iPhone fixture confirmed registered Music navigation, History open/close and bounded UI state; Music Insights reported its active section, period and anchor.
- Additional browser fixtures: desktop/iPhone Memory Settings, Copy and Retry, Home health and reconnect fallbacks, hydration, upload and MIME repair, image viewer, Markdown, chat switching and refresh passed. Synthetic generation continued after switching chats; Stop and UI recovery passed. The native iPhone passkey acceptance test remains blocked by Personal Team Associated Domains signing and cannot be replaced by a browser fixture.
- Real connected Spotify read-only lookup: #TETAS by CA7RIEL & Paco Amoroso was found; exact-title candidates had i.scdn.co artwork and the allowlisted URL passed image validation. This was a provider metadata check, not a production Chat image-gallery test.
- Real existing image provider: with a supported host model, it generated a PNG for the exact Spanish regression prompt. The installed Hermes plugin still pins an unsupported host model; the candidate adapter and Chat persistence path have local tests, but production end-to-end generation has not been verified.

## Release gates

At QA capture, staging, fresh independent backup, restored-backup migration rehearsal, previous-backend compatibility rehearsal, rollback rehearsal, model fingerprint, and exact readiness manifest were still pending for this candidate. Do not push main or deploy until those gates pass. Existing backups and manifests belong to earlier revisions and must not be reused.

Read-only production check: /root/Apollo remains at c231f0c78348923fa208c0a8810323ce5257d9f4. The actual apollo-backend.service and apollo-web.service were active; localhost /api/memory returned HTTP 200. An older /root/apollo-deployment-ready.json exists, but it does not prepare an uncommitted candidate.

## Additional scope

The 30 October general-intelligence/application-awareness directive arrived after the original tests. The candidate now has a code-checked capability registry, a bounded client-reported UI snapshot, registered local navigation actions, and a read-only diagnostics endpoint requiring a recent Settings grant. The existing AgentRuntime already runs independent read-only tools in parallel; its status classifier now distinguishes empty results and authentication failures. The quiz, personal memory, protected Chat and protected History work remains in this candidate.

The reproducible deterministic evaluation in scripts/evaluate-intelligence.py compares six identical routing/continuity cases against the deployed base revision: baseline 1/6, candidate 6/6. It includes the prior #TETAS failure, an unseen #marea follow-up, and a named-month Spotify stats question. Median local function times are in the evaluator output; they are microsecond-scale and do not measure end-to-end response latency. No equivalent candidate production-model runtime is available yet, so general answer quality, hallucination rate and live cross-feature reasoning are not claimed improved.

The prompt audit measured a 16,156-character rich-component schema sent on every Chat turn. The candidate keeps it for visual, narrative and interactive questions and omits it for simple turns. Three controlled public-question calls per variant through the production answer gateway used the same fast model: the current prompt had median first token 1.07 s and total 1.76 s; the shorter candidate-selected prompt had median first token 1.12 s and total 1.49 s. All six produced nonempty answers. This small gateway-only sample does not establish a statistically reliable speed or quality gain and is not an end-to-end candidate deployment test.

The broad intelligence directive is not yet fully verified. In particular, candidate model-level before/after evaluation, live connected cross-feature conversations, image generation through production Chat, and independent real-account privacy QA remain open. Production release gates below are still unsatisfied.
