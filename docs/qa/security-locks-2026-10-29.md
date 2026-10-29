# Security locks and Studio session QA — 29 October 2026

Candidate is based on production `8d6eabc380c6091b9057b9ae3131ace13b2695d9`. The original `/Users/Santi/Documents/apollo-website` checkout and its untracked QA files are untouched.

## Root cause and correction

The server issued a 30-second grant for the `leave` policy. The browser polled `/api/security/state` every five seconds but never renewed that grant. As soon as 30 seconds elapsed, the poll received `unlocked.studio=false` and concealed the active Studio route. Browser visibility changes also revoked the grant even though the route had not changed; every state poll rebuilt the Settings form. No Studio data fetch or React remount was required to trigger the failure.

The leave policy now has a renewable server lease. The active route renews it every ten seconds. Explicit navigation away revokes the grant; another actively open Apollo tab can retain the shared browser-session grant. A tab that left requires a new UI verification on return. Visibility changes and refreshes of the same route do not revoke. A one-hour server lease is the crash/offline fallback, not a user-facing timer. The 5- and 15-minute policies continue to expire at precisely 300 and 900 seconds from authentication, without renewal. A short status-network interruption does not immediately cover an already visible route; protected API requests continue to enforce the server grant. Security diagnostics log only resource names and renewal/revocation outcomes, never credentials or grant values.

## Security and presentation

Settings & Security can be independently locked with the existing passkey, passphrase, or one-use recovery-code methods. The entire Settings route is concealed while locked; management APIs remain server-gated and require a fresh in-memory tab identifier in addition to the HttpOnly cookie, so a second tab or bare API request cannot reuse a Settings grant. Refreshing Settings requires reauthentication. Policy changes and credential/recovery mutations require a settings verification no older than 90 seconds. Failed freshness does not replay a mutation after reauthentication. The unlock screen gives passkeys prominence and puts passphrase and recovery behind smaller progressive controls. Privacy & Security is grouped into Security overview, Tab Locks, Chat Privacy, and Credentials & Recovery; timing appears only for enabled locks. Reduced-motion, keyboard, dark/light, desktop, and mobile behavior were exercised in isolated browser fixtures.

## Verification

- Synthetic Python security tests cover ten minutes of renewed leave-policy time, exact 300/900-second boundaries, revocation, settings API locks, recovery authentication, and 90-second mutation freshness.
- Isolated browser fixtures cover enrollment, passphrase, virtual passkey, one-use recovery code, Studio route persistence, multi-tab behavior, refresh, visibility, temporary network loss, Settings direct navigation/API denial, keyboard access, and responsive dark/light layouts. No real production passphrase or recovery code was entered by tests.
- A separate browser run waited **600 actual seconds** while repeatedly reading the Studio API and checking the visible route. Studio stayed unlocked throughout; afterward, navigation, a sibling tab, refresh, visibility, and locked Settings checks passed. The expanded fixture also passed a six-second status-network failure and recovery in a short run.
- Full Python suite: **409 tests run, 407 passed, 2 optional skips**. iOS configuration: **17 passed**. Production asset build, changed JavaScript syntax, Git whitespace and connectivity checks passed. Production acceptance must use read-only state/API checks; do not unlock the owner's real account with synthetic credentials.

Visual fixture captures: [desktop unlock, dark](security-locks-2026-10-29/apollo-security-unlock-desktop-dark.png), [desktop unlock, light](security-locks-2026-10-29/apollo-security-unlock-desktop-light.png), [iPhone-size unlock, dark](security-locks-2026-10-29/apollo-security-unlock-iphone-dark.png), [iPhone-size unlock, light](security-locks-2026-10-29/apollo-security-unlock-iphone-light.png), [desktop Settings, dark](security-locks-2026-10-29/apollo-security-settings-desktop-dark.png), [desktop Settings, light](security-locks-2026-10-29/apollo-security-settings-desktop-light.png), [iPhone-size Settings, dark](security-locks-2026-10-29/apollo-security-settings-iphone-dark.png), [iPhone-size Settings, light](security-locks-2026-10-29/apollo-security-settings-iphone-light.png).

## Limits

Tabs in the same browser profile share the HttpOnly grant cookie. They coordinate route presence to avoid one tab unexpectedly revoking an active sibling. If browser communication is unavailable, leaving a route revokes the shared grant for safety. A suspended or crashed page cannot renew forever; its lease expires after at most one hour. A physically installed iPhone and actual owner passkey prompt are outside synthetic browser coverage. The native passkey signing blocker and required on-device checks are recorded in [ios-passkeys-2026-10-29.md](ios-passkeys-2026-10-29.md).
