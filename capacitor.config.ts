import type { CapacitorConfig } from "@capacitor/cli";

const APOLLO_ORIGIN = "https://ubuntu-2gb-hel1-1.tailc5eaaa.ts.net";

const config: CapacitorConfig = {
  appId: "com.santilozano.apollo",
  appName: "Apollo",
  webDir: "www",
  backgroundColor: "#090909",
  appendUserAgent: " Apollo-iOS/1.3",
  loggingBehavior: "debug",
  ios: {
    backgroundColor: "#090909",
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
      resize: "native",
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
