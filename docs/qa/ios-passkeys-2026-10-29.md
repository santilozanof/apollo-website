# Native iOS passkeys: signing and domain audit (2026-10-29)

## Proven cause

- The Capacitor shell uses the same HTTPS Tailscale origin as Safari. `apollo_security.py` sets WebAuthn RP ID to that hostname and verifies that exact origin. No origin mismatch was found in repository configuration.
- The installed-build development profile for `9XP7Z4T89D.com.santilozano.apollo` expires 2026-11-05 and contains **no Associated Domains entitlement**. The Xcode target also had no entitlement file. Apple requires `webcredentials` association for WKWebView and for a direct AuthenticationServices passkey provider.
- The live private Tailscale association URL returned 404. The existing static server would return `application/octet-stream` for an extensionless AASA file.
- A signed build with the new entitlement failed with the existing profile. `xcodebuild -allowProvisioningUpdates` gave the decisive error: `Personal development teams ... do not support the Associated Domains capability.` This is an Apple provisioning gate, not a WebAuthn server validation bug.
- The old frontend mapped every WebAuthn `NotAllowedError` to “Device verification was canceled.” That DOM error also covers permission/policy denials and timeouts. It was therefore a false diagnosis of the user's native failure.

## Prepared changes and checks

- Added a Release-only `webcredentials` entitlement with Apple's `?mode=developer` alternate mode for this private domain. Debug remains signable under the existing Personal Team. The bundle ID is unchanged; build number moves from 1 to 2 for an association refresh.
- Added a `webcredentials` association document for the exact Team ID and bundle ID. Added a static-server wrapper that serves this extensionless path as `application/json` while preserving the current static site routes.
- WebAuthn's `NotAllowedError`, `SecurityError`, unsupported context, duplicate credential, interruption, and backend verification failures now have distinct, non-deceptive messages. `NotAllowedError` is explicitly ambiguous rather than labeled definite cancellation. No biometric data is handled by Apollo.
- Local AASA test: HTTP 200, `application/json`, no redirect; `/` remained HTTP 200. Production AASA remains 404 until release and reviewed static-service switch.
- Xcode's signed Personal Team **Debug** build succeeded after isolating the entitlement to Release. The Release entitlement build failed at provisioning, as expected. No app was installed.
- iOS configuration tests: 17 passed. The isolated localhost browser fixture passed enrollment, virtual WebAuthn registration/authentication, passphrase, recovery, relock, and the new ambiguous `NotAllowedError` message. Full Python/security results are recorded in `security-locks-2026-10-29.md`. Browser virtual WebAuthn confirms the existing server challenge/verification flow, **not** physical Face ID.

## Remaining external acceptance gate

The current Personal Team cannot sign the required entitlement. A paid Apple Developer Program team with Associated Domains enabled, a successful development-profile build, the live AASA response, Developer Mode/Associated Domains Development enabled on the iPhone 16, and an active Tailscale connection are required for the prepared WKWebView route. Install the updated build over the existing bundle ID to preserve local data. Then perform the physical registration, Studio unlock/relock, Mac/Safari regression, and separate cancellation/failure checks in `docs/ios/README.md`. Until those succeed, native Face ID/passkey support is **not verified or complete**. The passphrase and recovery codes remain the supported app fallback.
