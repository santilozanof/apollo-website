# Gmail in Apollo

Gmail uses the existing `google_oauth.json` client and the already deployed
`/api/google/callback` redirect URI. The Gmail Connect action requests only
`gmail.readonly` and `gmail.send`, with Google's incremental authorization
(`include_granted_scopes=true`) and offline access. It does not request the
Calendar scope again. Gmail OAuth state and token keys are separate from
Calendar's keys; a Gmail disconnect deletes Apollo's Gmail grant and pending
mail drafts without touching Calendar or revoking Google's combined grant.
Revoking the combined Google grant would also invalidate Calendar.

The callback validates a one-use, 15-minute state, checks both returned scopes,
verifies Gmail access through `/profile`, and checks a reused Calendar refresh
token against Gmail before accepting it. Refreshes keep a transiently failing
offline credential and require reconnect after `invalid_grant`. Tokens stay on
the backend in Apollo's existing root-owned database; no OAuth token reaches
the browser. Startup tightens the database file mode to `0600` for older
installations. Gmail request bodies and credentials are never logged or returned
in connection status. Gmail API calls have bounded timeouts and response sizes.

Apollo chat searches a bounded first 8 matching messages, or up to 15 results
over three pages for a broad university-admissions query. Admissions results
are ranked by visible school/application evidence and unrelated promotions are
excluded. These are bounded search results, never a claim that the whole mailbox
was examined. Apollo reads Gmail's structured message payload, extracts plain
text (or text from HTML), and provides concise summaries plus message rows with
verified Gmail thread links and dates in Apollo's configured timezone. Attachments
are not opened. Authentication and recovery messages are redacted from ordinary
lists, summaries, and drafting evidence; codes are not revealed through chat. Email
text is explicitly marked as untrusted evidence in a tool-disabled model call.
The model cannot trigger a send: a new message or reply is drafted first, the
exact recipient, subject, and body are shown on a second confirmation turn,
and only `yes, send` (or an
equivalent explicit confirmation) invokes `users.messages.send`. The pending
confirmation is consumed before the outbound request to prevent duplicate
sends. If a network failure occurs after Google accepts a send, Apollo will
report uncertainty rather than retry automatically; check Gmail Sent before
redrafting.

Standalone drafts to "myself" resolve the recipient from Gmail's verified
`/profile` response. Otherwise Apollo requires an explicit recipient. Drafts
remain in the chat's short-lived context; Apollo does **not** save drafts to
Gmail, because that operation needs `gmail.compose` (outside the two authorized
scopes). An explicit save request explains this limitation without changing
OAuth permissions.

For real-account activation after deployment, open Settings → Connections →
Gmail → Connect, consent to the two Gmail scopes using the existing Google
client, and confirm the status changes to Connected. Google Cloud must list the
existing production callback URL as an authorized redirect URI and allow the
account as a test user if the OAuth consent screen is in Testing. No separate
Cloud project is needed. A live read, draft, and confirmed send require the
owner's authorization and are not covered by synthetic tests.
