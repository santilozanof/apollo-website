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

test("uses the private HTTPS Tailscale origin without cleartext fallback", () => {
  assert.match(config, /https:\/\/ubuntu-2gb-hel1-1\.tailc5eaaa\.ts\.net/);
  assert.match(config, /cleartext:\s*false/);
  assert.doesNotMatch(config, /allowNavigation/);
});

test("keeps native integration optional for the production website", () => {
  assert.match(index, /apollo_capacitor\.css/);
  assert.match(index, /apollo_capacitor\.js/);
  assert.match(bridge, /if \(!capacitor\?\.isNativePlatform\?\.\(\)\) return/);
  assert.match(bridge, /__apolloCapacitorReady/);
  assert.match(bridge, /__apolloCapacitorVersion = "1\.2"/);
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

test("uses one icon dock with all eight top-level destinations and the Apollo sun", () => {
  for (const route of ["home", "apollo", "music", "calendar", "tasks", "studio", "routines", "settings"]) {
    assert.match(nativeController, new RegExp(`Destination\\(route: "${route}"`));
    assert.match(bridge, new RegExp(`"${route}"`));
  }
  assert.match(nativeController, /route: "apollo", title: "Apollo", symbol: "sun\.max"/);
  assert.doesNotMatch(nativeController, /symbol: "sparkles"/);
  assert.match(bridge, /\.apollo-message-mark svg/);
  assert.doesNotMatch(index, /M5 25 L14\.5 6 L27 25/);
  assert.match(nativeController, /private let dock = UIView/);
  assert.match(nativeController, /accessibilityLabel = destination\.title/);
  assert.match(nativeCSS, /html\.apollo-capacitor-ios \.sidebar/);
  assert.match(nativeCSS, /display: none !important/);
  assert.match(nativeCSS, /--apollo-native-tabbar-height: 58px/);
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
  assert.match(nativeController, /keyboardWillShowNotification/);
  assert.match(nativeController, /UIAccessibility\.isReduceMotionEnabled/);
  assert.match(bridge, /appStateChange/);
  assert.match(bridge, /apollo:native-resume/);
  assert.match(bridge, /badgeChanged/);
  assert.match(nativeCSS, /apollo-reduce-motion/);
});
