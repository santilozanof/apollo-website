# Apollo pipeline, music, and Pulse release candidate — 2026-10-29

This document records local verification for the candidate based on production `7e836fe74da48ef9de3548cf5e53ceda5faaf1da`. It is not a production acceptance result. The release SHA and fresh backup gate must be recorded after the candidate is committed.

## Root cause and response path

Read-only production timing for the user's “When did Mike Dean start working with The Weeknd and why?” question showed `intent_planning_ms=3069`, `memory_agent_ms=128778`, `model_ttft_ms=3007`, and `backend_to_done_ms=135654`. The sole `web_research` call took 128762 ms. The response then missed the documented 2015 collaboration and implied a later origin. The 2015 credit is supported by the [Recording Academy's Mike Dean credits](https://www.grammy.com/artists/mike-dean/2701/) and contemporary 2015 reporting of Dean's work on “Tell Your Friends.” The available credit establishes a collaboration by 2015, but does not by itself prove why the two first connected.

Apollo's existing models remain `gpt-5.6-luna`/low for fast turns, `gpt-5.6-terra`/medium for analysis and research, and `gpt-5.6-sol`/high for difficult technical turns, with existing environment overrides. Simple public questions bypass the separate context planner. Common acknowledgements avoid an extra silence-classifier call. A single read-only intelligence tool no longer triggers a redundant coordinator decision. Multiple independent initial reads run concurrently. Research uses one focused gateway call, whole-response deadlines, bounded parallel public-page reads, and stage-specific progress messages. The backend emits genuine model chunks as they arrive; a server-owned job lets the browser reconnect without resending the prompt. Optional follow-ups render after the answer completes.

The synthetic deadline test proves that a blocked gateway response returns at its configured deadline; it is not a live post-release latency measurement. A live retest of the exact question, citations, and time to first meaningful content remains required after deployment.

## Music and Pulse

Music Insights rankings and chat history queries now default to measured listening time: verified export milliseconds plus observed, nonoverlapping estimates. Integer minutes with thousands separators are shown in the dashboard, rankings, details, charts, and recap slides; play count remains an explicit option. Artist identities from name-only imports coalesce with a unique matching Spotify identity while ambiguous names stay separate. Observation cadence is 45 seconds while playing and 90 seconds idle. No catalog track length is labeled verified listening. The dashboard chart now allocates measured time across local time bins, including period and daylight-saving boundaries.

The official Spotify reference supplied by the user is 1,241 minutes, Tory Lanez, and “So Drunk I Forgot You — Twitch Tapes” for October 26–November 1, 2026. This week had not ended at the October 29 read-only production inspection. Apollo had 589 recorded events, about 513 verified minutes, and 179 events without verified duration in that partial period. These figures must not be overwritten to match the reference. Final reconciliation needs the completed week and official history export or other authorized source of exact playback duration; Spotify's recent-play API alone does not provide actual listened milliseconds.

Pulse now ranks actual Canvas task deadlines, Apollo tasks, upcoming Google Calendar events, measured Spotify listening, and current WHOOP recovery when those sources return usable data. It uses two visible suggestions on narrow phones and up to three on desktop. Selection and dismissal suppress the same suggestion until its underlying state changes or the feedback window expires. It refreshes after meaningful visits and source changes without randomized churn. The Spotify glyph comes from Apollo's existing Spotify asset; Google Calendar, Canvas, and WHOOP use consistent source-labeled SVG action icons because the official marks were not available locally under verified permission for a compact third-party control. Instructure's published Canvas guide also warns against rendering its logo too small to read. Pulse is positioned outside the composer grid flow, so it cannot move New Chat, History, or the composer.

## Local verification

- Python: 374 tests passed, 2 optional skips, using the bundled Python runtime with Pillow.
- iOS configuration: 16 passed.
- `npm run build`, JavaScript syntax, Git whitespace, and Python compile checks passed.
- Isolated Chromium browser fixtures: desktop and 390px iPhone Pulse source ranking, icon load, refresh, dismissal, repeat visit, click-through, and unchanged control geometry passed. Existing desktop/iPhone reliability fixture passed Home, reconnection, debrief, hydration, chat media, Markdown, image viewer, chat switch, and refresh. A separate fixture passed generation continuation after a chat switch and explicit Stop. These use synthetic provider responses and a temporary SQLite database.
- Real Spotify, Google Calendar, Canvas, WHOOP, physical iPhone, and the updated research model's answer have not been verified with the candidate.

## Release gate

Do not push this candidate to `main` or claim deployment until the new exact SHA has a fresh private server backup, independent off-server copy, verified restore, two migration rehearsals on the restored database, previous-backend compatibility and rollback rehearsal, model SHA256, and an operator-owned `/root/apollo-deployment-ready.json` matching that SHA. The prior `7e836fe` manifest cannot authorize this revision. Keep the existing verified server backup.
