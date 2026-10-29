# Apollo step-up privacy and tab locks

Apollo remains private behind Tailscale Serve. Optional locks add a second, server-checked proof of possession. Every lock is **off by default**. The browser never stores a passphrase, recovery code, passkey private key, or unlock grant in localStorage. The server stores scrypt hashes, WebAuthn public credentials, one-use challenges, and SHA-256 hashes of short-lived grant cookies in additive SQLite tables.

## Enrollment

The deployment operator creates a random one-time token in `/root/apollo-security-setup-token` with mode `0600` after the release is healthy. The file is outside Git and must never be copied into QA reports or logs. The owner opens **Settings → Privacy & Security → Tab Locks**, enters that token and a passphrase of at least 16 characters, and saves the eight one-use recovery codes offline. The operator removes the setup-token file after successful enrollment. Enrollment cannot be restarted through the web UI. A lost passphrase with no passkey or recovery code requires a separately reviewed server-side recovery procedure; do not reset the database.

The owner can then add passkeys, choose locks independently for Chat, Music, Calendar, Tasks, Routines, Daily Debrief/Home, and Studio, and choose relock on leave, after five minutes, or after fifteen minutes. The settings grant is required for changing policies, registering or removing passkeys, changing the passphrase, or regenerating recovery codes. Passphrase changes and recovery-code regeneration also require the current passphrase. Recovery codes are shown only when created and become invalid when regenerated.

The HTTPS web app uses WebAuthn with required user verification, RP ID and origin validation, 120-second one-use challenges, and signature-counter checks. On compatible Apple devices, the **system passkey prompt** may use Face ID or Touch ID. Apollo never receives biometric data. The existing Capacitor/WKWebView wrapper has no LocalAuthentication bridge; native biometric unlock and its server-bound cryptographic proof have not been added or verified on a physical iPhone. The passphrase and offline recovery codes remain the supported fallback. Do not advertise native Face ID or Touch ID support in that wrapper until a device test confirms WebAuthn there or a server-bound native credential is implemented.

## Enforcement

`apollo_security.handle` runs before the normal GET, POST, PATCH, and DELETE handlers. It gates chat history, attachments and generated media, connected-source APIs, notifications, and file routes at the backend. Protected chat generations carry a resource grant; each emitted chunk checks that it is still valid. When a grant expires or is revoked, the browser conceals the route and removes rendered chat messages and history titles. Private media responses use `Cache-Control: no-store`. Push notifications use a generic title, body, route, and category whenever privacy or tab locks are enabled.

Enhanced Privacy requires verification for Chat, Calendar, Home/Debrief, WHOOP, connections, notifications, and other connected personal records; Spotify history is included if separately selected. Maximum Privacy requires verification for all mapped connected resources. While Chat is locked, a separate public-only question field can answer without chat history, connected tools, or saved account context; its answer is not saved to private chat. OAuth callbacks retain their independent one-time state validation and are not blocked by a tab grant.

These locks protect Apollo's server responses from someone who merely opens an already signed-in browser. They cannot protect information already copied to a clipboard, retained in an operating-system notification issued before privacy was enabled, captured in a screenshot, or obtained by someone who controls the Mac/iPhone account, browser process, or server. The passphrase fallback is only as strong as the secret the owner chooses and the security of the device where it is entered. Do not treat a person's writing style, IP address, or Tailscale login alone as step-up verification.

## Release checks

Install pinned `webauthn==3.0.1` into `/opt/apollo/venv` before release preflight and run `pip check`. Rehearse additive schema creation twice against the isolated restored backup; the previous backend must still serve that migrated copy. The setup token is **not** a substitute for the normal backup, rollback, model-fingerprint, and exact-SHA readiness manifest gates in `production-deployment.md`.
