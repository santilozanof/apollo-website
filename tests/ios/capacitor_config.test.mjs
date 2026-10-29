import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const config = await readFile(new URL("../../capacitor.config.ts", import.meta.url), "utf8");
const index = await readFile(new URL("../../index.html", import.meta.url), "utf8");
const bridge = await readFile(new URL("../../apollo_capacitor.js", import.meta.url), "utf8");
const offline = await readFile(new URL("../../www/offline.html", import.meta.url), "utf8");
const info = await readFile(new URL("../../ios/App/App/Info.plist", import.meta.url), "utf8");
const nativeController = await readFile(new URL("../../ios/App/App/ApolloViewController.swift", import.meta.url), "utf8");
const nativeCSS = await readFile(new URL("../../apollo_capacitor.css", import.meta.url), "utf8");
const dateNavigation = await readFile(new URL("../../apollo_date_nav.js", import.meta.url), "utf8");
const dateCSS = await readFile(new URL("../../apollo_date_nav.css", import.meta.url), "utf8");
const oledCSS = await readFile(new URL("../../apollo_oled.css", import.meta.url), "utf8");
const originalA = await readFile(new URL("../../ios/Artwork/apollo-original-a.svg", import.meta.url), "utf8");
const artworkGenerator = await readFile(new URL("../../scripts/generate-ios-artwork.swift", import.meta.url), "utf8");
const sceneDelegate = await readFile(new URL("../../ios/App/App/SceneDelegate.swift", import.meta.url), "utf8");
const entitlements = await readFile(new URL("../../ios/App/App/App.entitlements", import.meta.url), "utf8");
const project = await readFile(new URL("../../ios/App/App.xcodeproj/project.pbxproj", import.meta.url), "utf8");
const association = JSON.parse(await readFile(new URL("../../.well-known/apple-app-site-association", import.meta.url), "utf8"));

test("uses the private HTTPS Tailscale origin without cleartext fallback", () => {
  assert.match(config, /https:\/\/ubuntu-2gb-hel1-1\.tailc5eaaa\.ts\.net/);
  assert.match(config, /cleartext:\s*false/);
  assert.doesNotMatch(config, /allowNavigation/);
});

test("binds native passkeys to Apollo's exact private origin and existing app ID", () => {
  assert.match(entitlements, /webcredentials:ubuntu-2gb-hel1-1\.tailc5eaaa\.ts\.net\?mode=developer/);
  assert.deepEqual(association, {webcredentials: {apps: ["9XP7Z4T89D.com.santilozano.apollo"]}});
  assert.equal((project.match(/CODE_SIGN_ENTITLEMENTS = App\/App\.entitlements/g) || []).length, 1);
  assert.match(config, /appId: "com\.santilozano\.apollo"/);
  assert.doesNotMatch(entitlements, /applinks:/);
});

test("keeps native integration optional for the production website", () => {
  assert.match(index, /apollo_capacitor\.css/);
  assert.match(index, /apollo_capacitor\.js/);
  assert.match(bridge, /if \(!capacitor\?\.isNativePlatform\?\.\(\)\) return/);
  assert.match(bridge, /__apolloCapacitorReady/);
  assert.match(bridge, /__apolloCapacitorVersion = "1\.7"/);
  assert.match(bridge, /isLight \? "LIGHT" : "DARK"/);
});

test("has an actionable private-network failure screen", () => {
  assert.match(config, /errorPath:\s*"offline\.html"/);
  assert.match(offline, /Make sure Tailscale is connected/);
  assert.doesNotMatch(offline, /http:\/\//);
});

test("declares only the native permission Apollo currently requests", () => {
  assert.match(info, /NSLocationWhenInUseUsageDescription/);
  assert.doesNotMatch(info, /NSFaceIDUsageDescription/);
  assert.doesNotMatch(info, /NSCameraUsageDescription/);
  assert.doesNotMatch(info, /NSMicrophoneUsageDescription/);
});

test("uses a genuine-glass custom dock with seven direct routes and one persistent WebView", () => {
  for (const route of ["home", "apollo", "music", "calendar", "tasks", "studio", "routines"]) {
    assert.match(nativeController, new RegExp(`Destination\\(route: "${route}"`));
    assert.match(bridge, new RegExp(`"${route}"`));
  }
  assert.doesNotMatch(nativeController, /Destination\(route: "settings"/);
  assert.match(nativeController, /settingsButton\.accessibilityLabel = "Settings"/);
  assert.match(sceneDelegate, /ApolloDockController\(\)/);
  assert.match(nativeController, /ApolloDockController: UIViewController/);
  assert.match(nativeController, /private let apollo = ApolloViewController\(\)/);
  assert.match(nativeController, /button\.accessibilityIdentifier = "apollo\.tab\./);
  assert.match(nativeController, /UIGlassEffect\(style: \.regular\)/);
  assert.match(nativeController, /effect\.isInteractive = true/);
  assert.match(nativeController, /UIImage\(named: "Nav-/);
  assert.match(nativeController, /private let dock = UIView/);
  assert.doesNotMatch(nativeController, /class ApolloTabBarController: UITabBarController/);
  assert.match(nativeCSS, /html\.apollo-capacitor-ios \.sidebar/);
  assert.match(nativeCSS, /display: none !important/);
});

test("restores the original A icon and renders exact desktop glyphs as native templates", () => {
  assert.match(originalA, /M5 25 L14\.5 6 L27 25/);
  assert.match(originalA, /M6\.5 20 C11 15\.5 18 14\.5 27 19/);
  assert.match(artworkGenerator, /index\.html/);
  assert.match(artworkGenerator, /routines\.js/);
  assert.match(artworkGenerator, /Nav-\\\(route\)/);
  assert.doesNotMatch(artworkGenerator, /drawSun/);
});

test("synchronizes routes without replacing or reloading the WebView", () => {
  assert.match(bridge, /window\.apolloNativeNavigate/);
  assert.match(bridge, /window\.apolloNavigate\?\.\(destination\)/);
  assert.match(bridge, /routeChanged/);
  assert.doesNotMatch(nativeController, /reload\(/);
  assert.doesNotMatch(nativeController, /loadHTMLString/);
});

test("provides validated native dialog bridge operations", () => {
  for (const operation of ["confirm", "prompt", "actionSheet"]) {
    assert.match(nativeController, new RegExp(`case "${operation}"`));
  }
  assert.match(nativeController, /validatedRequestID/);
  assert.match(nativeController, /maximumLength/);
  assert.match(bridge, /requestNative\("confirm"/);
  assert.match(bridge, /requestNative\("prompt"/);
  assert.match(bridge, /requestNative\("actionSheet"/);
});

test("handles keyboard, reduced motion, lifecycle, and route badges", () => {
  assert.match(nativeController, /keyboardLayoutGuide\.topAnchor/);
  assert.match(nativeController, /keyboardLayoutGuide\.usesBottomSafeArea = false/);
  assert.doesNotMatch(nativeController, /setChatDockAnchor/);
  assert.match(nativeCSS, /body\.apollo-native-keyboard-open #apolloView\.active \.apollo-composer-wrap/);
  assert.match(nativeCSS, /#apolloPresence\.visible \{/);
  assert.match(nativeCSS, /bottom: calc\(var\(--apollo-native-dock-reserve\) \+ 10px\)/);
  assert.match(nativeCSS, /#musicView \.apollo-play-queue \{/);
  assert.match(config, /resize: "none"/);
  assert.match(bridge, /setResizeMode", \{ mode: "none" \}/);
  assert.match(nativeController, /keyboardWillShowNotification/);
  assert.match(nativeController, /keyboardDidHideNotification/);
  assert.match(nativeController, /apolloNativeKeyboardChanged/);
  assert.match(bridge, /window\.apolloNativeKeyboardChanged/);
  assert.doesNotMatch(nativeCSS, /transition: bottom var\(--apollo-keyboard-duration/);
  assert.doesNotMatch(bridge, /Keyboard\?\.addListener\?\.\("keyboardWillShow"/);
  assert.match(nativeController, /UIAccessibility\.isReduceMotionEnabled/);
  assert.match(bridge, /appStateChange/);
  assert.match(bridge, /apollo:native-resume/);
  assert.match(bridge, /badgeChanged/);
  assert.match(nativeCSS, /apollo-reduce-motion/);
});

test("uses adaptive monochrome and removes obsolete accent settings", () => {
  assert.doesNotMatch(index, /data-apollo-accent="blue"|Accent Color/);
  assert.doesNotMatch(bridge, /postNative\("accentChanged"/);
  assert.doesNotMatch(nativeController, /case "accentChanged"|setAccent\(/);
  assert.match(nativeController, /let selectedColor: UIColor = \.label/);
  assert.match(nativeController, /removeObject\(forKey: "apollo\.setting\.accent"\)/);
  assert.match(index, /localStorage\.removeItem\("apollo\.setting\.accent"\)/);
  assert.match(bridge, /localStorage\.removeItem\("apollo\.setting\.accent"\)/);
});

test("retains native-only chat, music, routines, and notification refinements", () => {
  assert.match(bridge, /apollo-native-queue-action/);
  assert.match(bridge, /ApolloDateNav\?\.mountRoutines/);
  assert.match(bridge, /apollo-native-notification-disclosure/);
  assert.match(nativeCSS, /apollo-native-notification-disclosure/);
  assert.match(nativeCSS, /apollo-now-controls/);
  assert.match(nativeCSS, /apollo-input/);
});

test("shares one date navigation implementation and OLED palette across web and signed shell", () => {
  assert.match(index, /ApolloDateNav\?\.mountCalendar\(\)/);
  assert.match(dateNavigation, /mountCalendar:/);
  assert.match(dateNavigation, /mountRoutines:/);
  assert.match(dateNavigation, /controls\.replaceChildren\(dateLabel, actions\)/);
  assert.match(dateCSS, /#calendarView \.apollo-date-nav-actions,/);
  assert.match(dateCSS, /#routinesView \.apollo-date-nav-actions/);
  assert.match(dateCSS, /scrollbar-gutter: auto/);
  assert.match(nativeController, /apollo_date_nav\.css/);
  assert.match(nativeController, /apollo_date_nav\.js/);
  assert.match(nativeController, /apollo_oled\.css/);
  assert.match(index, /apollo_oled\.css/);
  assert.match(oledCSS, /--bg: #000000/);
  assert.match(oledCSS, /html\[data-theme="light"\]/);
});
