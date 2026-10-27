import type { CapacitorConfig } from "@capacitor/cli";

const APOLLO_ORIGIN = "https://ubuntu-2gb-hel1-1.tailc5eaaa.ts.net";

const config: CapacitorConfig = {
  appId: "com.santilozano.apollo",
  appName: "Apollo",
  webDir: "www",
  backgroundColor: "#000000",
  appendUserAgent: " Apollo-iOS/1.6",
  loggingBehavior: "debug",
  ios: {
    backgroundColor: "#000000",
    preferredContentMode: "mobile",
    allowsLinkPreview: false,
    scrollEnabled: true,
    webContentsDebuggingEnabled: false
  },
  server: {
    url: APOLLO_ORIGIN,
    cleartext: false,
    errorPath: "offline.html"
  },
  plugins: {
    Keyboard: {
      resize: "none",
      style: "DEFAULT",
      autoBackdropColor: "dom"
    },
    StatusBar: {
      overlaysWebView: true,
      style: "DARK"
    }
  }
};

export default config;
