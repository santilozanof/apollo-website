# Apollo Chat presentation and Music 1.8 release QA — 2026-10-27

## Root cause of the reported Chat answer

The production message for the reported House of Balloons question was inspected read-only. Its stored assistant content contained approximately 1,558 words in 31 paragraphs and had no Markdown headings, image, timeline, source links, or `apollo-ui` blocks. The browser did not strip those elements: they were never generated. The generic "whole story" phrasing also selected the FAST model and no read-only web research toolset. Jarvis mode then applied a monospace font to all response descendants, which compounded the weak hierarchy.

The candidate routes substantial public histories to SMART plus read-only web research, instructs verified citations and structured Markdown, and adds bounded final-response safeguards. The safeguards can add section headings without editing paragraph text, and a timeline only when every event is copied from an existing sentence. An image is included only after a public subject has been identified and a matching Wikimedia Commons thumbnail has passed an HTTPS image check. Personal-history queries do not trigger this public-story path. The final streamed `done` event carries the prepared content; the normal incremental Markdown renderer remains unchanged.

## Local validation

- Python: 349 tests passed, two skipped, in the complete `tests/test_*.py` discovery run. The previous baseline was 335 passing tests.
- iOS configuration: 15 of 15 Node tests passed.
- `npm run build`, JavaScript syntax checks, and `git diff --check` passed.
- The synthetic Chat browser fixture rendered three semantic headings and a timeline. At iPhone width, paragraph text computed to 16px, headings to 21px, timeline items to 14px, and the page had no horizontal overflow. At desktop width, paragraph text computed to 16.5px.
- The Music browser fixture showed populated September rankings, entity detail, recent history, and month navigation. The 390px layout had no horizontal overflow. Fixture records are invented test data, not a live account.
- A read-only production Spotify API probe returned an artist with three official image sizes; a CDN HEAD check returned HTTP 200, `image/jpeg`, and permissive image CORS. This proves API image availability for that account, not completion of every Music screen with live data.

## Verification boundaries

No personal Spotify export was imported, no live Chat response was generated with a connected account, and no external Calendar, Canvas, WHOOP, or iPhone device flow was exercised in this refinement. Production deployment and live smoke results must be recorded separately after the exact candidate passes the prepared-release gate.
