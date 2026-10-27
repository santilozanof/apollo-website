# Apollo iOS 1.6

## Current iOS 1.6 architecture and QA

- `ApolloDockController` is a custom UIKit container, not a system-managed tab bar. It keeps one persistent Capacitor WebView and offers seven direct 44pt-or-larger icon-only destinations; Settings remains a separate top-right native button. On iOS 26 the dock uses `UIGlassEffect(style: .regular)` in `UIVisualEffectView`; older supported systems use `systemChromeMaterial`. The material is native, but UIKit does not manage the custom dock's navigation behavior.
- The WebView and root are transparent, with the page extending behind the dock and status bar. Content owns its end-of-scroll padding; UIKit owns the dock and keyboard geometry. Chat's composer reserves the dock height while idle, then sits above the keyboard when focused; UIKit's keyboard layout guide is the sole WebView resizer.
- Accent customization is removed. The dock and Settings affordance use dynamic monochrome system colors; old accent storage is cleared/ignored. Dark mode uses a black canvas with restrained raised surfaces, while light mode retains its previous tokens.
- Calendar and Routines use one `apollo_date_nav.js`/`.css` layout, moving their existing buttons without changing handlers. The signed bundle injects the same component over an older private web deployment.
- iOS 1.6 validation: an unsigned Xcode simulator build passed; iPhone 16 passed all five existing UI tests plus a new Calendar/Routines button-geometry test; iPhone 13 mini and iPhone 17 Pro Max passed the seven-destination/Settings test. The iPhone 16 captures were visually checked for the glass dock, Calendar, Routines, and multiline chat above the software keyboard. Browser QA at 393px found matching Calendar/Routines horizontal button positions and 42pt controls; 375px and 440px had no horizontal overflow. Desktop dark and light palettes were checked. `npm run test:ios-config` passed 12 tests and the Python regression suite passed 232. Tests did not send chat messages or alter personal data.
- These checks do not establish physical-device haptic/keyboard feel or prove live integrations beyond their existing read-only UI surfaces. The web/desktop changes on this branch are not deployed; the signed iOS bundle carries its own date-navigation and OLED styles while the private page remains on the older release. The iOS 1.5 notes below are historical.
- Physical iPhone checks remain necessary for haptic feel, signing/Tailscale installation, exact keyboard animation, and OAuth/background behavior. See the prior acceptance checklist below. The 1.4 notes that follow are historical and describe the superseded system tab bar.

Apollo iOS is a private, iPhone-only Capacitor 8 application with a native iOS navigation and presentation layer. It is not configured for App Store distribution and does not contain credentials or integration tokens.

## Architecture decision

Apollo's frontend is not a separately built SPA. It is a single server-coupled `index.html` with extensive inline behavior, root-relative `/api` requests, streamed `fetch()` responses, and server-hosted assets. The production deployment also separates the static web service from a Python `ThreadingHTTPServer` on `127.0.0.1:8765`; Tailscale Serve/proxy routing restores the public `/api` prefix before dispatching backend routes.

Authentication is currently the private Tailscale network boundary. There is no independent Apollo username/password or cookie-session middleware in this repository. Google and WHOOP OAuth state and tokens, Spotify credentials/cache, Canvas subscriptions, conversation history, and all personal data remain on the VPS.

A locally bundled copy of the current frontend would change its origin to `capacitor://localhost`. That would require a new CORS policy, a real application authentication scheme, cross-origin streaming validation, asset URL rewriting, OAuth callback changes, and special handling for attachments and media. Capacitor's native HTTP bridge is also not a drop-in replacement for the current streamed `ReadableStream` chat path.

For Apollo 1.4, the least disruptive architecture remains a native Capacitor container that loads the existing private HTTPS Tailscale origin:

`https://ubuntu-2gb-hel1-1.tailc5eaaa.ts.net`

This preserves same-origin APIs, SSE-style streaming over `fetch()`, OAuth callbacks, cookies if they are introduced later, Generative UI assets, KaTeX, and server-rendered behavior. It is a deliberate private-device exception to Capacitor's general guidance that `server.url` is intended for live reload. A future locally bundled app should begin with a dedicated authenticated API and an extracted frontend build, not a mechanical copy of the present document.

The app never falls back to a public endpoint or cleartext HTTP. When the private origin cannot load, a bundled error page asks the user to connect Tailscale and retry.

## Historical iOS 1.4 implementation

- `ApolloTabBarController` owns a stock `UITabBar` and its selection. Built with the iOS 26 SDK, this is UIKit's system-managed Liquid Glass tab bar, not a custom blur capsule. Four destinations are direct tabs; the system More interface contains Tasks, Studio, and Routines. Settings is a separate native `UIButton.Configuration.glass()` action in the top-right on iOS 26 (native gray configuration on older iOS).
- One `ApolloViewController`, one Capacitor bridge, and one `WKWebView` remain alive above the tab controller's empty route controllers. Selecting a route calls the existing web navigation function and does not load another page. A selection made before the bridge is ready is replayed once it loads. The shared WebView is hidden only while UIKit's More list is visible, then restored when an overflow destination appears. Web-to-native route synchronization does not cancel an open More list.
- The app icon and launch artwork are generated from Apollo's verified original stylized-A favicon, now checked in under `ios/Artwork`. The sun remains the Apollo Chat glyph. The seven tab images are rasterized as native template assets from the exact inline desktop navigation SVGs in `index.html` and `routines.js`; no unrelated SF Symbols replace them.
- The keyboard layout has one geometry owner: UIKit's `UIKeyboardLayoutGuide`. The WebView is a subview of a native container, constrained below the safe top and above the keyboard guide. Capacitor Keyboard resize mode is `none`. The chat composer has a constant 8px viewport-bottom anchor; the old native notification-to-JS timing callback and CSS bottom animation are gone. The system tab bar remains at the device bottom and is covered by the software keyboard, as in other native tab-bar apps. Tap outside to dismiss before switching tabs. The draft stays in the same live DOM node.
- Music Queue moves out of the now-playing content/transport row to a secondary top-right card action with a 44pt touch target and icon-only visual treatment; Previous / Play-Pause / Next remain independently centered. The existing Spotify queue handler remains unchanged. Its fixed sheet is moved outside the card's isolated stacking context so it can appear above the existing scrim.
- Native shell interactions include tab selection, Settings, alerts, prompts, action sheets, the system keyboard, WebKit date/time/select pickers, status bar, and haptics. Chat streaming, Generative UI, KaTeX, Spotify content, Calendar, Tasks, Routines, Studio, and charts remain web-powered. No production backend or desktop UI was changed or deployed.

### iOS 1.4 verification

- Xcode iOS 26.2 SDK simulator build succeeded without signing. The final iPhone 16 (iOS 26.3.1) XCUITest suite passed 3/3: three focus/dismiss/reopen cycles with a three-line unsent chat draft, draft retained across Apollo → Music → Calendar → Apollo, Studio through native More, Settings, and the Queue sheet opening above its scrim. Early tests exposed a More-list reset, a pre-bridge tab-selection race, and Queue sheet stacking; each was fixed and retested.
- Simulator hardware-keyboard connection was temporarily disabled for the strict keyboard pass, which asserts that the software keyboard is actually hittable on each reopen. It passed and the capture shows the composer directly above the keyboard. The setting is restored after QA.
- A separate iPhone 16 simulator screen recording of the keyboard test was captured and inspected at 30-fps frame spacing around presentation. The composer stayed directly above the moving keyboard and the unsent draft survived; no second CSS-driven jump or blank bottom gap was observed in that recording. This is simulator evidence, not a physical-device guarantee.
- iPhone 13 mini dark-mode and iPhone 17 Pro Max light-mode simulator captures showed the native bar, original icons, Settings placement, and safe areas without clipping. The iPhone 13 mini More/Studio UI test passed. The installed A icon was visible on the simulator home screen.
- With the iPhone 16 simulator's Reduce Motion preference enabled, both navigation/keyboard UI tests passed; the preference was restored afterward. This checks operation under that setting, not physical-device animation or haptic quality.
- `npm run test:ios-config`: 10 passed; `python3 -m unittest discover -s tests -q`: 227 passed; `node --check apollo_capacitor.js` and `git diff --check` passed.
- No chat message was sent, Spotify playback was commanded, calendar/task/routine data was changed, or production deployment was performed. Active streaming, a long conversation, live Spotify Queue behavior, OAuth, haptics, and the exact keyboard transition on the owner's physical iPhone remain acceptance checks.

### Physical iPhone acceptance checks

After signing and installing with Tailscale connected, use an iPhone 16 to open Apollo Chat, type a multiline draft, tap outside, reopen immediately, repeat rapidly, then switch away and back. Verify no composer jump, flash, safe-area gap, or lost draft. Repeat in a long existing conversation and during a safely initiated streaming reply. Check Queue while Spotify is playing, Studio through More, dark/light/Reduce Motion, haptics, native dialogs, background/resume, and private-network reconnect. Do not treat simulator-only results as proof of physical keyboard or haptic behavior.

## Historical iOS 1.3 architecture audit

The following 1.3 notes are retained as implementation history; the current 1.4 tab bar and keyboard layout above supersede the dock and timing model described below.

Apollo keeps one persistent `WKWebView` and does not create a second copy of route, conversation, form, streaming, OAuth, or backend state. A floating UIKit icon dock is layered over the Capacitor view controller and exchanges only validated route, theme, badge, and presentation messages with JavaScript. Switching destinations calls Apollo's existing route functions; it does not reload the WebView. Seven primary destinations fit the dock; Settings has its own persistent top-right control. All eight destinations remain one tap away with full VoiceOver labels and restrained selected states.

UIKit is used because `CAPBridgeViewController`, `WKWebView`, the custom dock, alerts, and action sheets are already UIKit components. This keeps ownership and lifecycle direct and avoids wrapping the existing controller in a second navigation hierarchy. SwiftUI becomes worthwhile if a future version introduces a native screen with native-owned state.

The bridge accepts only known route names, bounded dialog text, validated request identifiers, and at most eight action-sheet choices. Native results are JSON-encoded before returning to JavaScript. No backend endpoints or credentials were added.

## Native behavior included in iOS 1.3 (historical)

- iPhone-only Xcode target with automatic signing and bundle ID `com.santilozano.apollo`.
- Capacitor 8 with Swift Package Manager; CocoaPods is not required.
- App lifecycle, Browser, Haptics, Keyboard, and Status Bar plugins only.
- Native bridge code injected into the remote document from the signed app bundle, so native behavior does not depend on a web deployment.
- Floating capsule dock with `UIGlassEffect` on iOS 26 and system material fallback on older iOS versions. It holds Home, Apollo, Music, Calendar, Tasks, Studio, and Routines; a separate glass Settings button occupies the consistent top-right slot. Its Apollo icon is a sun, and the duplicate web tab bar is hidden only inside the iOS app.
- Bidirectional native/web route synchronization, route reselection scroll-to-top, and Apollo response-ready badge support without WebView reloads.
- System confirmation alerts, text-entry prompts, and native action sheets for routine and chat-history overflow menus. Existing JavaScript handlers still perform validation and backend actions.
- Native WebKit date, time, and selection pickers remain attached to the original HTML controls, preserving form state and validation.
- Theme-aware status bar and dock, safe-area-aware mobile content, native keyboard resizing, interactive keyboard dismissal, and UIKit-timed dock/composer motion.
- Restrained selection/impact haptics on navigation and meaningful controls, with a bridge preference to disable them.
- Reduced-motion behavior in both UIKit presentation and the native-only CSS layer.
- External HTTP(S) destinations opened outside the trusted Apollo WebView.
- Foreground connectivity check, nonblocking Tailscale banner, lifecycle events, and settings refresh after returning from OAuth.
- Apollo sun artwork in the app icon, launch screen, web branding, chat header, loading/empty states, and dynamic assistant message states. The signed native bridge updates branding even before a web deployment.
- Native-only mobile layout refinements for Home, Music, Calendar, Tasks, Studio, Routines, Settings, and chat. The floating dock has a consistent 66-point content reserve; Music, Calendar, and task entry have targeted layout corrections.
- Compact Apollo composer with New Chat and History moved beside the title to make room for Settings. The Music transport group is centered independently of the queue control; Routines and Calendar share the same Add / centered Today / previous / next date-control geometry.
- Recent Notifications is collapsed by default inside the iOS shell. The count, disclosure state, existing notification rows, Clear action, and deep links remain intact; this changes presentation only and does not delete notifications.

## iOS 1.3 keyboard fix (superseded by 1.4)

The previous implementation had several clocks acting on the same layout: Capacitor resized `WKWebView`, the older mobile page reacted separately to focus and `visualViewport`, the bridge toggled another keyboard class, and UIKit animated the dock from its own show/hide notifications. The chat composer also switched its fixed `bottom` value without a transition. That combination could move the composer before the WebView resized and create a visible jump on dismissal.

iOS 1.3 uses UIKit `keyboardWillChangeFrame` as the single native timing source. It sends visibility, duration, and curve to native-only CSS while animating the floating dock with the same notification. Capacitor remains the sole WebView resizer. Legacy mobile focus/viewport classes can still exist for browser behavior, but they no longer own native composer or dock positioning. Tab changes end editing without replacing the WebView or clearing the chat draft. Reduce Motion removes the transition.
- A location usage description because the existing web app optionally reports device location for local weather/context. Apollo continues to work if permission is denied.

## Preserved features

Because the app keeps Apollo's production origin, it preserves the existing implementation of Chat, streamed responses, Generative UI, KaTeX, calculators, quizzes, history, Spotify controls, WHOOP, Google Calendar, Canvas, tasks, routines, settings, Studio, and server-side data persistence. Spotify playback still controls the active Spotify device through the existing backend; the WebView is not a replacement Spotify playback SDK.

## Not implemented or not yet verified on a physical iPhone

- Native push notifications. The website's Service Worker/Web Push UI may report unsupported in WKWebView. APNs requires an Apple signing team, entitlement, physical device, and server-side device-token delivery work.
- Face ID/app lock. No biometric permission or third-party plugin was added without a defined lock/recovery policy and real-device verification.
- App Store, TestFlight, ad hoc, or enterprise distribution.
- Settings toggles and complex editing forms remain web-owned. Replacing them would duplicate working state and validation; their date/time/select controls already receive system-native iOS presentations through WebKit.
- Broad swipe-to-change-tab gestures were intentionally not added because they conflict with charts, sliders, carousels, text selection, and horizontal web content.
- Physical-device haptic feel, keyboard layout, text selection/copying, location choice, OAuth round trips, notification delivery, and Tailscale disconnect/reconnect behavior.
- Production chat sends and write actions were intentionally not used during testing because they would modify personal data.

## Build commands

From the repository root:

```sh
npm install
npm run ios:sync
npm run ios:build
```

Regenerate the checked-in icon and launch artwork after changing the Apollo mark:

```sh
npm run ios:artwork
```

Open the native project:

```sh
npm run ios:open
```

## Install on the private iPhone

These are the only remaining steps that require the owner's Apple Account and physical iPhone:

1. On the iPhone, install Tailscale, sign in to the same tailnet as the Apollo VPS, and leave Tailscale connected.
2. Connect the unlocked iPhone to this Mac with USB. Tap **Trust** on the iPhone if asked.
3. Open `ios/App/App.xcodeproj` in Xcode (or run `npm run ios:open`).
4. In Xcode, choose **Xcode > Settings > Accounts**, click **+**, and sign in with the Apple Account. Enter credentials only in Apple's Xcode window; never put them in this repository.
5. In the project navigator, select the blue **App** project, select the **App** target, then open **Signing & Capabilities**.
6. Keep **Automatically manage signing** enabled and choose the Apple Account's **Personal Team** (or paid development team) from **Team**.
7. If Xcode says the bundle identifier is unavailable, replace `com.santilozano.apollo` with a unique reverse-domain identifier in both Xcode and `capacitor.config.ts`, then run `npm run ios:sync` again.
8. In Xcode's top toolbar, choose the connected iPhone as the run destination and click the triangular **Run** button.
9. If the iPhone requests Developer Mode, open **Settings > Privacy & Security > Developer Mode**, enable it, restart the iPhone, confirm after restart, and click **Run** in Xcode again.
10. Launch Tailscale first, then Apollo. On first launch, choose whether to allow the optional location request. Apollo works without location.

A free Personal Team is sufficient for private testing, but Apple requires its development provisioning to be refreshed periodically; current Personal Team profiles expire after seven days. A paid Apple Developer Program team has longer-lived development provisioning but is not required for this private installation.

## iOS 1.3 simulator verification on 2026-10-15

- Unsigned iOS Simulator build succeeded with Xcode's iOS 26.2 SDK; the simulator runtime was iOS 26.3.1. No signing or physical iPhone was needed.
- The final bridge ran against Apollo's private Tailscale HTTPS origin without a production web deployment. All seven dock buttons and the top-right Settings button were exposed with accessibility names. An accessibility-driven simulator pass opened every dock destination, then Settings from each one; all 14 selections succeeded without a WebView reload.
- iPhone 16 visual captures checked the floating glass capsule, sun icon, top-right Settings, compact chat composer, New Chat/History placement, Music empty-state queue access, Calendar date controls, and Routines date controls/cards. The Calendar and Routines rows were adjusted after comparing the captures so Today is truly centered. The Routines Today control stays visible but disabled for the current date.
- On iPhone 16, a synthetic unsent draft was typed with the software keyboard. Captures before focus, with the keyboard open, and after tapping outside showed the composer above the keyboard, the dock hidden while typing and restored after dismissal, no persistent blank gap, and the draft retained. The bridge has no timeout-based keyboard choreography.
- iPhone 13 mini and iPhone 17 Pro Max simulator captures checked the seven-icon dock, floating safe-area placement, and top-right Settings control. Light and dark appearance were checked on the larger simulator and dark mode restored afterward.
- `npm run test:ios-config`: 9 tests passed. `python3 -m unittest discover -s tests -q`: 227 tests passed. `node --check apollo_capacitor.js` and `git diff --check` passed.
- Native dynamic notification disclosure, active Spotify transport/queue, and rapid keyboard focus-distract cycles were not exercised end-to-end against live account data. The Simulator computer-control surface stopped accepting coordinate interactions after the initial keyboard cycle, so those interactions remain explicit manual QA items. Code paths and layout rules were inspected; do not interpret this as visual verification of those states.
- No production deployment, chat send, Spotify playback command, notification Clear action, or destructive account mutation was performed.

## Previous iOS 1.2 verification baseline

- `python3 -m unittest discover -s tests -v`: 227 tests passed.
- `npm run test:ios-config`: 8 tests passed.
- `npm run ios:build`: unsigned iOS Simulator build succeeded with Xcode 26.3 and the iOS 26.3 SDK.
- Installed and launched Apollo on an **iPhone 16**, **iPhone 13 mini**, and **iPhone 17 Pro Max** simulator running iOS 26.3.1.
- Private Tailscale HTTPS origin loaded successfully; observed HTTP 200 responses for Apollo assets and data APIs without exercising user-facing write actions.
- Native navigation was exercised across Home, Apollo, Music, Calendar, Tasks, Studio, Routines, and Settings with no duplicate web navigation and no WebView reload. Studio loaded its projects on the iPhone 16 and 13 mini; the icon dock remained legible and tappable at the mini width. A Home Music card also selected the Music dock item through web-to-native route synchronization.
- Native routine action sheet, destructive confirmation alert, and text-entry prompt were presented; every destructive path was canceled before a write.
- System WebKit date, time, and selection pickers were opened without changing values.
- Chat composer keyboard opening/dismissal was exercised; the dock hides while typing, the composer stays visible, and the dock returns after dismissal.
- Light and dark system appearance, status-bar contrast, Dynamic Island/notch spacing, dock safe area, and the corrected Routines top safe area were visually verified.
- Screen-by-screen visual QA on iPhone 16 covered the dashboard cards, chat header/composer, Spotify now-playing card, focused Calendar day, compact Tasks entry and sections, Studio projects, full-width Routines cards/hydration/heatmap, and Settings controls. Music's title and playback status no longer overlap; Calendar's date chevron renders correctly; Tasks no longer spends a third row on the Add button.
- Smaller and larger simulator QA confirmed all eight dock icons fit without truncation or selected-state overlap. The larger screen also verified light-to-dark theme synchronization.
- Background/home and resume preserved the active Apollo route and existing WebView state.
- Terminate/reinstall/relaunch succeeded. The simulator's location permission was denied so it could not block the remaining tests; Apollo continued to work.
- No production web deployment or live account mutation was performed. Local `index.html` and `apollo_os_v1.js` branding updates will reach the website only through the normal separate deployment; the native iOS bridge applies the sun immediately inside the installed app.
- Runtime npm dependencies: zero known vulnerabilities. The development-only Capacitor CLI tree currently reports a moderate advisory in its `xcode -> uuid` dependency; it is not shipped as JavaScript in the iOS app and is awaiting an upstream-compatible dependency update.

## Safe test gaps

The following require the physical device or would alter live personal data, so they remain explicit acceptance tests:

- Send and stream a new chat message, then confirm progressive rendering and history persistence on the physical device.
- Exercise a generated calculator/quiz and KaTeX inside a real response.
- Perform Spotify playback controls against the intended active device.
- Complete Google/WHOOP OAuth or reconnect flows.
- Create/update/delete calendar items, tasks, routines, or Canvas subscriptions.
- Accept or deny location on the owner's device.
- Disconnect Tailscale and confirm the bundled retry screen, then reconnect and retry.
- Verify haptic strength, long-press/text-copy behavior, external-link presentation, OAuth return, background/resume, and keyboard animation on the physical iPhone 16.
