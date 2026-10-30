# Apollo candidate QA — 30 October 2026

## Candidate state

- Worktree: /private/tmp/apollo-overhaul-release-601f671, branch codex/apollo-design-system.
- Base revision: c231f0c78348923fa208c0a8810323ce5257d9f4. The final candidate SHA is the committed branch HEAD, recorded separately after commit.
- Production was updated by GitHub Actions run #108 to b2185248d037f0d75512a0ca0f806ad78824587b after exact-SHA gates passed. The subsequent measured-minutes Chat hotfix requires a new SHA and a new release gate.
- The original /Users/Santi/Documents/apollo-website checkout was not changed by this candidate.

## Verification

- Python: 434 tests passed, 2 skipped, on isolated local SQLite after the application-awareness, music-scope, prompt-routing, migration-preservation, and measured-minutes changes. This macOS Python lacks hashlib.scrypt; the test runner used a test-only PBKDF2 shim. Production hashing was not substituted.
- iOS configuration: 17 passed.
- JavaScript syntax (modified external modules), Python compilation, and git diff --check passed.
- iOS production asset build passed.
- Mobile Chrome fixture: private Chat displayed an inline verification card. Cancel left a locked response with a working retry control. History cancel stayed locked. No page errors or horizontal overflow. Fixture authentication used a synthetic token and isolated database.
- Existing desktop and iPhone browser fixtures: Home artwork, queue overlay, response actions, Settings disclosures, connection controls, History and themes passed. A separate iPhone fixture confirmed registered Music navigation, History open/close and bounded UI state; Music Insights reported its active section, period and anchor.
- Additional browser fixtures: desktop/iPhone Memory Settings, Copy and Retry, Home health and reconnect fallbacks, hydration, upload and MIME repair, image viewer, Markdown, chat switching and refresh passed. Synthetic generation continued after switching chats; Stop and UI recovery passed. The native iPhone passkey acceptance test remains blocked by Personal Team Associated Domains signing and cannot be replaced by a browser fixture.
- Real connected Spotify read-only lookup: #TETAS by CA7RIEL & Paco Amoroso was found; exact-title candidates had i.scdn.co artwork and the allowlisted URL passed image validation. This was a provider metadata check, not a production Chat image-gallery test.
- Real existing image provider: with a supported host model, it generated a PNG for the exact Spanish regression prompt. The installed Hermes plugin still pins an unsupported host model; the candidate adapter and Chat persistence path have local tests, but production end-to-end generation has not been verified.

## Release gates

The first fresh backup and server-side restore passed for the preceding commit; its migration rehearsal detected that sensitivity backfill cleared 148 stored memory embeddings. The narrower update trigger fixed that regression. For b218524, a new private snapshot, server restore, independent Mac artifact verification and SQLite/config restore, twice-run migration, previous-backend HTTP/rollback compatibility, runtime/ancestry/model checks and root-owned exact-SHA readiness manifest all passed. Run #108 succeeded. The measured-minutes Chat hotfix below must repeat fresh exact-SHA release checks before another push.

Post-deployment production check: /root/Apollo and /root/apollo-active-release both reported b2185248d037f0d75512a0ca0f806ad78824587b. Apollo backend, web and Hermes were active; SQLite integrity was ok; original 941 chats, 5,638 messages and 148 memory embeddings remained. The private HTTPS Home and critical read-only APIs returned HTTP 200. The protected diagnostics endpoint returned HTTP 423 without verification. The live static index hash matched the candidate.

## Additional scope

The 30 October general-intelligence/application-awareness directive arrived after the original tests. The candidate now has a code-checked capability registry, a bounded client-reported UI snapshot, registered local navigation actions, and a read-only diagnostics endpoint requiring a recent Settings grant. The existing AgentRuntime already runs independent read-only tools in parallel; its status classifier now distinguishes empty results and authentication failures. The quiz, personal memory, protected Chat and protected History work remains in this candidate.

The reproducible deterministic evaluation in scripts/evaluate-intelligence.py compares six identical routing/continuity cases against the deployed base revision: baseline 1/6, candidate 6/6. It includes the prior #TETAS failure, an unseen #marea follow-up, and a named-month Spotify stats question. Median local function times are in the evaluator output; they are microsecond-scale and do not measure end-to-end response latency. No equivalent candidate production-model runtime is available yet, so general answer quality, hallucination rate and live cross-feature reasoning are not claimed improved.

The prompt audit measured a 16,156-character rich-component schema sent on every Chat turn. The candidate keeps it for visual, narrative and interactive questions and omits it for simple turns. Three controlled public-question calls per variant through the production answer gateway used the same fast model: the current prompt had median first token 1.07 s and total 1.76 s; the shorter candidate-selected prompt had median first token 1.12 s and total 1.49 s. All six produced nonempty answers. This small gateway-only sample does not establish a statistically reliable speed or quality gain and is not an end-to-end candidate deployment test.

The broad intelligence directive is not yet fully verified. In particular, candidate model-level before/after evaluation, image generation through production Chat, and independent real-account privacy QA remain open. The measured-minutes hotfix release gates remain unsatisfied.

## Post-deployment observations and measured-minutes correction

Live Chrome on the private HTTPS origin showed Home, Calendar events, Canvas tasks, Routines/hydration, WHOOP measurements, Music Insights, Recaps, and connected statuses for Gmail, Google Calendar, Canvas, Spotify and WHOOP. The October monthly recap exported a readable 1080×1920 PNG with artist imagery and 7,712 measured minutes. At 390×844, Home and Chat fit without horizontal overflow and the mobile navigation and composer remained accessible. Studio showed its verification gate; physical native iPhone passkeys were not tested.

A read-only Chat test answered the current screen correctly and opened Music Insights through the registered navigation action. It then failed the cross-feature question “How many measured Spotify minutes did I listen to in October 2026, and how many were verified?” despite the Music Insights panel showing 7,712 measured and 7,429 verified minutes. The intent predicate did not recognize duration terms, so it sent the request down a current-playback path. The hotfix routes measured, verified, estimated, minutes, hours and duration questions to recorded history and keeps the immediately preceding Music Insights question as the scope of a verified-minutes follow-up. The deterministic comparison against deployed b218524 is 6/7 versus 7/7 for this hotfix candidate. End-to-end live Chat must be repeated after hotfix deployment; no answer-quality claim is based solely on this routing test.
