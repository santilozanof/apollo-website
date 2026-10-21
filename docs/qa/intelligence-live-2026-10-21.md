# Apollo live intelligence validation — 2026-10-21

The candidate works substantially better after real failures were fixed, but **the intelligence upgrade is not deployed**. Production still runs commit `b59cd77ffbbb334eedc56601abe53c59bd335db4`, with no memory tables or memory API. Full-page web extraction and complete semantic backfill are not operational in production.

## Scope and evidence

- **57 recorded real HTTP conversations:** 56 against the isolated candidate on the deployment host, plus one against the deployed HTTPS chat endpoint. These include initial failures, corrected replays, follow-ups, and one intentionally interrupted stream. **56 completed and persisted; the interrupted response correctly did neither. This is a transport/persistence count, not a claim that 56 answers were correct.**
- [Request ledger](intelligence-live-2026-10-21/requests.json): prompts, timing, completion, persistence, and redacted tool traces. Answers and private account contents are omitted.
- [Manifest](intelligence-live-2026-10-21/manifest.json): final tested source hashes, model fingerprint, and index counts. All six runtime source hashes matched the final local files.
- Raw answers, coordinator outputs, public research tool evidence, the snapshot, and validation scripts remain private under `/root/apollo-validation-20261021` on the deployment host. The directory is separate from `/root/Apollo`.

The existing Hermes gateway at `127.0.0.1:8642` served every candidate model request. No second Hermes instance was started. Candidate HTTP used private loopback port `18765`, a SQLite backup of the real database, and the real account adapters. Network writes were blocked except model inference and OAuth token refresh; Spotify subprocess commands were restricted to reads. No automation or calendar polling worker was started. The actual memory-worker function was explicitly started and stopped for consolidation checks.

Production code and service configuration were not replaced or deployed, and neither service was restarted. Their PIDs remained `2358144` and `1047776`. The production smoke check created one harmless validation chat, ID `1000`, which was retained. No external calendar, task, or Spotify mutation was tested or performed. A WHOOP credential-rotation side effect required the narrow repair documented below. The temporary candidate HTTP process was stopped after testing; model/runtime assets were retained.

## What works with real evidence

| Capability | Observed result |
|---|---|
| Existing gateway pipeline | Real planner/coordinator calls, tool reads, adaptive answer generation and SSE completion worked. The gateway honored the candidate's request-level model options; ordinary inference disabled tools, research enabled only the web toolset. |
| Production HTTP chat | Actual HTTPS arithmetic request returned `391`, streamed, and was persisted in **1.657 s**. Production `/api/memory` returned 404, confirming the upgrade is absent. |
| Google Calendar | Authenticated reads succeeded; production returned 31 events over seven days. Corrected candidate planning included all of tomorrow's classes and avoided suggesting study during those classes. |
| Tasks and Canvas | Read 63 actual task rows. The private Canvas feed was freshly fetched in **2.43 s**, with `last_error=null`; its refresh updated only the test snapshot. Corrected chat answers identified the unfinished assignments and prioritized them. |
| Spotify | The real helper returned a paused track and playback position, and an artist follow-up resolved correctly. Device availability later changed; connected-account state and playback-device availability are distinct. No playback control was issued. |
| Connection discovery | A true empty-cache probe followed by a real chat returned the four connected external services and supported reads. Account-management buttons are now distinguished from data capabilities. |
| Explicit persistent memory | A synthetic focus preference was saved with provenance, the candidate was stopped/restarted, the rows remained identical, and a new chat recalled it. |
| Automatic persistent memory | A durable learning preference was consolidated by the actual worker/model with its source message and exact quote. It survived another process restart and was recalled in new chats. A temporary “for this exercise” preference was appropriately not consolidated. |
| Older conversations | Apollo automatically searched an actual August conversation and recovered a music-project discussion with dated chat evidence. It also recovered the packaging decision and breakfast drink from labelled January fixtures without pre-saving them as personal memories. |
| Semantic model | Real CPU embeddings on the deployment host recovered a breakfast-drink paraphrase. Cold load plus two-message indexing: **6.239 s**; warm retrieval: **29 ms**; peak smoke-process RSS: **491.7 MiB**. |
| Multi-service reasoning | Calendar + assignments and Calendar + assignments + Spotify ran real adapters. Corrected follow-ups retained source provenance and explained priorities. |
| Web research | Actual `web_search` calls returned source snippets. Corrected weather output cited the source containing its temperature figures. A fresh sourced release answer and follow-up succeeded; the follow-up reused persisted evidence in **3.595 s**. |
| Read retry | A deliberately injected first calendar `TimeoutError` produced a retry trace, then a successful real Calendar read. This is controlled fault injection, not evidence of a naturally occurring provider outage. |
| Interrupted response/retry | After the first chunk from a real model stream, an injected interruption produced an error without `done` and saved no assistant answer. HTTP retry completed and left exactly one user and one assistant message. |

## Failures found and corrected locally

1. **Implicit tool requests were classified as general questions.** “Which unfinished tasks are due soon?” skipped Tasks. Vague “months ago” and “did I say…” references skipped history. The fast gate now defers these and multi-source requests to semantic planning.
2. **Connection discovery had no planner field, then returned an empty first health snapshot.** Added the source, waited for the health probe, distinguished processing/unavailable from an empty account list, and clarified that recovery buttons are not capability declarations.
3. **A rolling 24-hour Calendar window omitted tomorrow afternoon.** Context now covers complete local days, uses the device zone, and applies the existing Canvas-import filtering. Partial retrieval is reported as an error rather than free time.
4. **Verbose task metadata exceeded the evidence limit.** Compact task records preserve all 63 rows. Local weekday/time strings now prevent the observed Saturday/Sunday and daylight-saving conversion errors.
5. **Legacy list handlers swallowed read-only reasoning.** Read requests now reach synthesis; existing explicit-action handlers remain in place.
6. **Source evidence disappeared between turns.** Source provenance and bounded web excerpts now persist with the assistant message and enter subsequent working context. Deletion/exclusion/forget filtering applies to these records. This fixed the observed false retraction of a previously sourced answer.
7. **The real coordinator occasionally emitted prose instead of JSON.** Added fenced-JSON handling and one bounded correction request without repeating tools. Partial evidence survives a failed coordinator.
8. **A new preference statement spent 59.7 s attempting unauthorized memory writes.** Declarative preferences now use background consolidation; a new preference replay completed in **6.348 s**, with **2 ms** memory-path overhead and no coordinator loop.
9. **Complex retrieval was silent until the final model call.** SSE now reports source-check progress after planning. Direct-answer completion no longer waits for optional title generation.
10. **HTTP retry lost the original user message ID.** It now retains the original source ID and rejects nonexistent retry targets, preserving attachment and memory provenance.
11. **Hermes wraps tool JSON, and URL presence alone did not establish weather support.** Wrapped results are parsed, the reproduced temperature/citation mismatch is rejected, and search-only answers disclose that full pages could not be retrieved.
12. **HTTP clients without `local_time` supplied an empty authoritative date.** The backend now supplies the current time in the requested zone.

Representative initial requests covered greeting, arithmetic, music explanation and follow-up, tomorrow's schedule, unfinished tasks, Canvas assignments, current Spotify and artist, connected services, study planning and priorities, three-service overview, explicit memory save/recall, a months-old project decision, semantic breakfast recall, real music-project history, nonexistent history, current release research and follow-up, weather, calendar + weather, and a constrained 90-minute plan. The ledger contains all requests and subsequent replays.

## Remaining failures, limitations, and blocked work

- **Full-page extraction is unavailable.** The live gateway returned: “DuckDuckGo (ddgs) is a search-only backend and cannot extract URL content.” Search succeeds, but results can be stale or inconsistent. One mixed Calendar/weather replay correctly returned usable calendar windows while declining to assert an unverified forecast. Configuring a supported extraction backend is deployment work; it was not silently changed.
- **Search grounding is improved, not proven universally.** The temperature check addresses the observed mismatch; it is not a general factual-verification guarantee. Search snippets alone do not justify claiming full-page verification.
- **The archive is not fully semantically indexed.** Final snapshot: 5,273 messages, 14 distinct indexed messages / 16 chunks, 5,259 pending consolidation jobs. Full-text history covered the snapshot; semantic evidence was tested on a small labelled subset. The full backfill was intentionally not run against 5,000+ historical messages during live validation. Production still has none of the upgrade's indexes.
- **Latency has a provider-dependent tail.** Nine simple candidate requests had a median of **1.865 s**, range **1.21–14.559 s** (the slowest was the post-interruption retry). Final simple checks were **1.21 s** and **1.865 s**. This is a small sample, not a latency SLO or load test.
- **Complex calls cost real time.** Corrected Calendar/task planning took **20.008 s**, first progress at **5.465 s**; its follow-up took **7.831 s**. Cold memory recall after restart took **27.208 s**; later recall took **6.776 s**. Research ranged from **8.494 s** to **61.505 s** across initial and corrected runs. The agent deadline remains a check between synchronous calls, not hard cancellation of an in-flight adapter.
- **External mutations and prolonged operation remain unverified here.** Calendar create/update/delete, task edits, Spotify playback/queue writes, notifications, automatic token-expiry recovery under concurrency, real 429/5xx outages, mid-job crash recovery, and concurrent sustained load were not exercised against live accounts. The manual WHOOP credential repair below is separate evidence, not proof of automatic recovery. Existing regression checks passed, but they are not live integration proof.

## Validation incident: WHOOP token rotation

The final production health check reported WHOOP `temporary_error` even though earlier reads succeeded. Investigation established that a read probe in the copied database refreshed WHOOP's **rotating** credentials: the candidate held a newer valid pair while production retained the expired pair. This was a validation side effect, not an unrelated outage.

The newer access token was verified with a real read-only WHOOP recovery request (**HTTP 200**, one record). The original three credential/expiry values were backed up privately with mode `0600`; only those three production `app_state` fields were then updated in one transaction, after checking they had not changed concurrently. No token values were printed or included in this repository. Neither service was restarted. A subsequent production connection check verified recovery; see [post-repair health](intelligence-live-2026-10-21/post-repair-health.json), alongside the retained [pre-repair final check](intelligence-live-2026-10-21/final-service-check.json).

The retained validation harness now reads the production-owned WHOOP access token without refreshing it and blocks WHOOP token POSTs. If that token expires, the owning production backend must refresh it. Future isolated validation must use a single credential owner or proxy authenticated reads; cloning rotating refresh tokens is unsafe even when business operations are read-only.

## Provisioned assets and required deployment

On the actual host:

- Runtime: `/root/apollo-validation-20261021/venv`, Python **3.11.15**, Torch **2.14.1+cpu**, Sentence Transformers **5.7.0**, Transformers **5.20.2**; approximately **1.5 GiB** installed.
- Model: `/root/apollo-validation-20261021/model`, **88 MiB**, `sentence-transformers/all-MiniLM-L6-v2`, pinned revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. Model fingerprint is in the manifest.
- Candidate RSS with embeddings loaded was approximately **521 MiB**. The host has about **1.9 GiB RAM plus 2 GiB swap**. Validation used `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, and `TOKENIZERS_PARALLELISM=false`.

An approved deployment must back up the real database, install the complete candidate modules/assets together, select the tested runtime (production currently uses Python 3.14), set `APOLLO_EMBEDDING_MODEL`, apply the additive schema migrations, and restart **Apollo only** against the existing Hermes service. Then run and monitor the real archive backfill and repeat the live read checks through HTTPS. Configure a supported Hermes extraction backend separately before claiming full-page research. No production deployment was performed.

Regression validation: **311 tests discovered, 309 passed, 2 optional skips** (local-model fixture and HEIC dependency). The actual Linux embedding smoke was executed separately and passed. `git diff --check` passed. Existing user changes were retained; no commit or push was made.
