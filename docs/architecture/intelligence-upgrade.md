# Apollo intelligence and memory upgrade — 2026-10-21

Implemented in the existing Python/SQLite application and **deployed as `ad2f5da8390e251a311656692f8ad3ebaa05700f`**. The [October 21 live readiness report](../qa/intelligence-live-2026-10-21.md) and investigation below document previous stages; the running revision and release gate must be checked separately for a later deployment. Existing UI, media, research, connection-health and Daily Debrief work was retained.

## Diagnosed causes and audit evidence

| Area | Verified in the checkout | Change / disposition |
|---|---|---|
| HTTP / streaming lifecycle | `/api/chats/{id}/messages` persists user turns, reconstructs recent history, routes domain actions, then streams a response. Direct handlers also persist replies. | Kept both paths. Added memory before domain dispatch/final generation and schema-triggered indexing for every persisted message. |
| Context loss | `MAX_HISTORY_MESSAGES=30` / `MAX_HISTORY_CHARS=100000` discards older model context. Original messages remain in SQLite. No general persistent personal-memory or hybrid history retrieval existed. A separate Spotify helper read the last 120 messages indiscriminately. | Keep bounded working context; retrieve original history and relevant durable facts. Spotify alias lookup now uses the same privacy-aware history store. |
| Tool availability / authority | `_apollo_choose_hermes_toolsets` uses keywords; a vague contextual follow-up can return `None`, enabling the full platform toolbox. Internal classifiers use the same request builder. | Model classifiers and final prose writers have no implicit gateway tools. Explicit research callers may enable only the web toolset. New local tool registry validates calls and enforces independent mutation approval. |
| Orchestration | Specialized task/calendar/music/routine handlers work independently. There was no local general tool-result/continuation loop. Hermes' deployed internal loop is unavailable for inspection here. | Added a bounded local coordinator for recall, recovery, research and multi-source reads. It inspects results, can reformulate searches and request further tools, and records partial failures. Existing external action handlers remain authoritative. |
| Model routing | Existing FAST/SMART/MAX defaults are Luna/Terra/Sol, with low/medium/high reasoning. Internal JSON envelopes could be classified as difficult user work merely because they were long. | Internal structured reasoning explicitly uses SMART/medium. Answer routing remains adaptive; deployment can override model IDs with `APOLLO_MODEL_FAST`, `APOLLO_MODEL_SMART`, `APOLLO_MODEL_MAX`. No undocumented Hermes token or iteration options were invented. |
| Premature completion | The SSE reader accepted EOF without a completion marker, empty completion, and `finish_reason=length`. | Incomplete, cancelled, length-limited and unexpected function-call responses raise an error instead of being saved as completed answers. Already streamed partial text is followed by an error; there is no silent success. |
| Authorization fallback | The “conservative” fallback granted action authority when an action verb and domain keyword appeared anywhere, including hypothetical questions. | General fallback writes fail closed. The narrow existing numeric hydration command remains a reversible deterministic fast path. |
| Calendar approval | A bulk shift could derive `approved` from arbitrary older conversation text; model output could supply an approval flag. | Old text can resolve facts, never approve a new batch. Preapproval now requires a separate server-owned argument and an explicit current approval phrase. Persisted pending actions still support scoped follow-up confirmation. Deletes retain existing confirmation. |
| Calendar / timezones | Backend-owned OAuth, refresh and real Google API reads/writes; 30-second transport limits; calendar scope includes reads and writes. Existing recurrence, batch, idempotency and timezone/DST tests cover these paths. | Preserved. New context carries actual timezone-bearing event values. Scope possession is not treated as proof of every future API call's success. |
| Tasks / Canvas | Canvas integration is iCal subscription ingestion and external task materialization, not the complete Canvas LMS API. Background sync records errors and timestamps. | Expose saved tasks with Canvas sync status. Missing/stale Canvas data is distinguishable from an empty task list. |
| Spotify / WHOOP | Spotify depends on an external helper and credentials at production paths; WHOOP uses its authenticated adapters and cached measurements. | Preserve adapters and playback actions. Registry includes read/discovery tools and exposes structured unavailable/disconnected/processing states. No fake OAuth or replacement account data. |
| Web research / extraction | Existing uncommitted `apollo_live_research.py` uses structured `/v1/responses`, checks tool evidence/citations, retries bounded failures, distinguishes unavailable/auth errors, and preserves successful search when optional extraction fails. | Preserve that implementation; expose it to the coordinator. Daily Debrief explicitly enables web tools so classifier isolation does not break its research. Production extraction cannot be declared working without the gateway. |
| Notifications / automation | Existing in-process engine validates structured triggers, persists schedules and sends push notifications with retries. It is not a general arbitrary-action scheduler. | Preserved; no new cron, message-sending or financial capability. |
| Connection health | First probe depended on monotonic time exceeding TTL when `at=0`, which can skip the first check on a fresh clock. | Explicitly permit the first probe. Existing single-flight, outage/reconnection distinction and persisted health remain. |
| Authentication | Backend listens on loopback; deployment uses its private authenticated Tailscale/proxy boundary. The repository has no general multi-user login/ACL system. | Preserve that boundary. Memory owner is server-controlled (`local`), never taken from requests or model arguments. Store-level isolation is tested, but this is still a single-user application, not a multi-tenant service. |
| Observability | Existing stage timings/logging; semantic planner logging could expose newly introduced memory queries. | Redact planner output, add metadata-only coordinator traces with model/effort, tools, statuses, retry/continuation counts and latency. Retain at most 1,000 traces for seven days. |

These are code-path observations and reproduced regressions. They explain concrete capability gaps; no before/after production quality or latency measurement is claimed. Local ports 8642/8765 were not serving Apollo/Hermes and production configuration/database/helper files were absent.

## Architecture and behavior

The layers are:

1. **Working context:** the existing bounded active conversation, current device time, and attachment facts. Explicitly forgotten historical messages are filtered before rebuilding model context.
2. **Durable facts:** preferences, background, goals, projects, routines, relationships and decisions. Each automatic fact requires an exact user-message quote, source ID, timestamps, category, confidence and a stable topic key. Assistant claims are never automatically promoted to user facts.
3. **Episodic history:** SQLite FTS5 keyword and exact-phrase search across all permitted historical messages; local semantic embeddings of overlapping message chunks; reciprocal-rank fusion, modest recency/source-reliability weighting, date filters and neighboring messages. Older results are not excluded just because they are old. Long matching messages return a labeled excerpt around relevant text.
4. **Live application context:** existing authenticated Calendar, tasks/Canvas, Spotify, WHOOP and web adapters. Old conversation statements are not a substitute for live account state.

The semantic planner may request memory, history or research by concise query. Saved facts are checked cheaply. Relevant explicit recall, missing durable facts, research needs or multi-source work enters `AgentRuntime`. Its model sees tool schemas and structured results, then proposes further calls or stops. Unknown tools, malformed arguments, repeated identical calls and unauthorized mutations are rejected. Read timeouts can retry once; writes never retry blindly. The final answer receives source-backed evidence and explicit failure/partial states.

The coordinator allows at most five decision rounds and twelve calls. A 90-second elapsed budget is checked **between** calls; it is not hard cancellation of an in-flight synchronous adapter. The coordinator model timeout is 45 seconds; existing provider adapters retain their timeouts. This distinction matters for worst-case latency.

Automatic consolidation runs on a durable message queue in a single daemon worker, starting only with the production server. Recent messages take priority over backfill. The worker processes four messages per tick, with three attempts per failed job. Optional embedding failures do not prevent fact extraction. Source existence, current content, exclusions and settings are rechecked around writes. Disabling automatic memory does not delete already saved facts.

Corrections sharing a stable topic key supersede older facts. Source timestamps, not import order, decide whether backfill can replace a newer correction. Explicit user edits take priority over automatic extraction. Separate contradictory facts retain their original provenance; the response instruction requires acknowledging unresolved ambiguity. Confidence is a model estimate, not a calibrated probability or proof of truth.

Deletion triggers remove conversation search rows, derived facts, embedding chunks, pending jobs and attachment metadata/factual notes. Retention deletes expired source messages and their derivatives. Existing orphaned upload bytes on disk are not physically shredded by these database changes; uploaded-file cleanup is a separate remaining lifecycle task.

Forgetting a fact removes all stored versions of its key, suppresses its original source messages and excludes their literal quotes/content. Topic exclusions are **literal phrase filters**, not a guarantee of detecting every paraphrase in unrelated old conversations. Excluding an entire chat is available for stronger control. Deleted source chats cannot be recovered through the new index. User-visible original conversations remain until deleted or expired by retention.

Simple general chat does not invoke the coordinator or historical search. It incurs only local settings/relevant-fact reads. Embedding inference is used for relevant semantic retrieval and background indexing, not every ordinary turn.

## User controls and API

Settings → **Memory & conversation history** provides:

- automatic-memory and history-search switches;
- review, correction and forgetting with source dates/IDs;
- literal topic exclusions and allowing topics again;
- conversation exclusions through the actual chat list;
- searchable originals;
- retention in days (`0` means unlimited), with explicit destructive confirmation.

These endpoints use the same private application boundary as the rest of Apollo:

| Endpoint | Purpose |
|---|---|
| `GET /api/memory` | Settings, active facts, exclusions and index configuration |
| `POST /api/memory` | Explicit fact/correction (`content`, `category`, stable `key`) |
| `DELETE /api/memory/{id}` | Forget all versions of a fact and suppress its source |
| `POST /api/memory/settings` | Validated booleans and retention period |
| `POST /api/memory/forget` | Exclude a literal `phrase` |
| `POST /api/memory/allow-topic` | Remove a literal topic exclusion; does not resurrect individually forgotten sources |
| `POST /api/memory/exclude-chat` | Set `chat_id`, `excluded` |
| `GET /api/memory/search?q=...&after=...&before=...&exact=true` | Date-filtered keyword/semantic originals; `after` inclusive, `before` exclusive |
| `POST /api/memory/reindex` | Retry/rebuild the optional message-vector index |
| `GET /api/agent/traces/{id}` | Metadata-only coordinator trace; ID is returned in chat timings |

Prefix-stripped proxy routes remain supported. Client-supplied owner/account IDs never select an identity.

## Files added or changed by this upgrade

- `apollo_memory.py`: schema, FTS migration/triggers, privacy, provenance, durable jobs, semantic embeddings and hybrid retrieval.
- `apollo_agent.py`: tool schemas/validation, approval checks, iteration, retry limits, structured evidence and redacted trace objects.
- `apollo_intelligence.py`: production wiring, adapter registry, structured coordinator/extractor prompts, background worker and HTTP controls.
- `server.py`: initializes schemas, mounts APIs, retrieves memory in the real chat handler, isolates gateway tools, tightens fallback/calendar approval, filters forgotten working/attachment context, detects incomplete streams and starts consolidation.
- `apollo_memory_controls.js`, `apollo_memory_controls.css`, `index.html`: a scoped Settings panel, safe text rendering and accessible controls; no UI redesign.
- `generate_debrief.py`: one explicit read-only web permission on its research call, preserving existing briefing behavior.
- `connection_health.py`: first-probe correctness.
- `requirements-memory.txt`, `scripts/provision-memory-model.py`: optional local model installation/provisioning, pinned to the tested public MiniLM revision. No user history is sent to an embedding service.
- `tests/test_memory_intelligence.py`, `tests/test_agent_runtime.py`, `tests/test_intelligence_pipeline.py`, `tests/test_real_semantic_memory.py`, `tests/browser/memory.cjs`: new regression and smoke coverage.
- `tests/test_calendar_bulk.py`: updated fixtures distinguish current scoped approval from old conversational text.
- `tests/test_routines_api.py`: AST fixture supplies the new API-routing dependency.
- `tests/test_live_research_pipeline.py`: freezes its date to the existing fixed October 19 evidence, removing the pre-existing date-dependent failure.

Other pre-existing modified/untracked files were left in place.

## Validation and benchmark

The deterministic suite exercises the actual HTTP handlers and SQLite persistence, substituting only provider/model responses. It does not grade a live model by checking mocked prose.

| Scenario | Evidence |
|---|---|
| Simple stable questions, minimal overhead | Real message handler; asserts no coordinator/history call |
| Explicitly saved preference | Reopened store and real chat prompt contains saved evidence |
| Unsaved months-old fact | Original January message appears with provenance in a completely new chat |
| Vague / paraphrased recall | Deterministic hybrid tests plus real MiniLM offline smoke test |
| New-chat project continuation | Project decisions/next step recovered from another chat |
| Corrections / conflicts | Newer source wins, late import cannot reverse it, ambiguous separate facts retain sources |
| Deleted / forgotten / excluded history | FTS, vectors, source facts, neighbors and queued extraction cannot recover deleted/suppressed sources |
| Privacy races / sensitivity | Exact quote validation; automatic sensitivity and do-not-remember gates; source-deleted-during-extraction check; owner isolation |
| Current information | Existing real HTTP research matrix with structured mocked web evidence, extraction failures, citations and timezone/DST checks |
| Calendar / tasks / Canvas | Real adapter invocation paths, both sources read once, timestamps preserved, Canvas sync status included |
| Multi-step / failure recovery | Coordinator inspects prior results, reformulates empty queries, retries transient reads, retains partial evidence and stops within budgets |
| Sensitive actions | Unknown tools rejected; unapproved writes blocked; model flags/history cannot approve a new calendar batch; existing delete-confirmation tests retained |
| Stream completion | EOF, empty response, length finish and unexpected tool calls cannot become saved completed answers |
| User controls | Desktop 1440×1000 and mobile 390×844 Chrome: toggle history, search-disabled behavior, correction, forgetting, literal exclusions, safe HTML-like text |

Latest standard suite: **302 tests discovered; 300 passed, 2 optional tests skipped** (the local-model smoke test and the existing HEIC-dependent check). A separate offline run of the real semantic smoke test **passed** using Sentence Transformers 5.7.0 and `all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. It recovered “Le Comptoir” from “Where did we enjoy French dining?” and a mountain-walking preference from “Favorite hiking hobby?”

Measured on this machine: first real model import/load plus indexing two synthetic conversations and one fact took **37.166 seconds**; the two warm retrievals together took **8 ms**. This is a small local smoke measurement, not a production corpus benchmark. Model-free HTTP fixture traces generally measured a few milliseconds of memory/coordinator overhead; model/network time was mocked.

JavaScript syntax checks and `git diff --check` passed. Browser screenshots were inspected. No authenticated external writes were performed.

Repeat:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
node --check apollo_memory_controls.js
# Start the existing isolated fixture, then:
node tests/browser/memory.cjs
```

Install normal image/notification requirements for the full suite. The browser test needs Playwright and Chrome. Its fixture is `tests/browser/reliability_fixture.py` and defaults to loopback port 8876.

## Deployment and remaining limits

1. Back up the existing SQLite database. Deploy the Python modules, Settings assets and changed existing files together, then restart the existing backend. Schema migration is additive; original messages are indexed. No deployment or push was performed here.
2. Keyword/exact search works immediately. The pinned semantic model and a tested CPU runtime are now provisioned on the deployment host under `/root/apollo-validation-20261021/model` and `/root/apollo-validation-20261021/venv`. Production still uses its original Python 3.14 interpreter and has no embedding environment configured. An approved deployment must select the tested runtime and set `APOLLO_EMBEDDING_MODEL` in the backend service environment. The app itself uses local-only model loading. See the live report for exact versions and resource measurements.
3. The restarted worker backfills vectors and consolidates durable facts. Initial model loading is expensive, and large archives need time. Inspect Settings and semantic retrieval status; do not equate “configured” with “fully indexed.” Retry failed indexing with the reindex endpoint. Inspect real source accounts and the Hermes `/v1/responses` endpoint before claiming production readiness.
4. The local runtime handles multi-step retrieval/research and explicitly requested memory actions. **Arbitrary cross-service write workflows, durable resumable action plans, financial actions and automatic compensating transactions are not implemented.** Existing Calendar/tasks/routines/Spotify/automation handlers retain their supported actions and confirmations. Unsupported actions must not be reported as completed. Unrestricted `/tools` gateway access is intentionally no longer granted through ordinary chat.
5. Real Hermes model requests, search, Calendar/Tasks/Canvas/Spotify reads, Canvas feed freshness, and HTTP latency have now been tested. Full-page web extraction is unavailable with the gateway's configured DuckDuckGo backend. External mutations, notifications, and prolonged production-load behavior remain unverified in this read-only campaign. Detailed evidence is in the live report.
6. Semantic vector scoring currently scans the account's cached vectors. FTS is indexed; vector search should move to an indexed local vector store for a large archive after measurement. Durable-fact keyword lookup currently scans active facts. No artificial historical date cutoff is applied.
7. Automatic consolidation is model-dependent and can miss facts or choose inconsistent topic keys. Original searchable messages remain the recovery path. Add production evaluations for multilingual descriptions, subjective relevance, conflict resolution and sensitive-information classification before claiming ChatGPT-level reliability.
8. Single-user proxy isolation is preserved. Multi-user deployment requires authentication and authorization across **all** existing endpoints, not merely an owner column in memory tables. Do not expose this backend directly to the public internet.
9. Trace coverage is richest for the new coordinator. Legacy specialized action routes retain their existing logs/timings; a unified durable action journal and per-adapter cancellation remain next work.

Recommended next work: staging account smoke checks; real-model benchmark prompts against a synthetic long-lived user corpus; durable scoped action plans with idempotent verification and resumable progress; then measured vector-index and consolidation improvements. The system is materially more capable and auditable, but this implementation is not a claim of complete agent parity.

Embedding adapter API checked against the [Sentence Transformers documentation](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html), including local-only loading and normalized embeddings.
