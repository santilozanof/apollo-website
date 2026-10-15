import { access, copyFile, readFile } from "node:fs/promises";
import { constants } from "node:fs";

const requiredFiles = [
  "www/index.html",
  "www/offline.html",
  "capacitor.config.ts",
  "apollo_capacitor.js",
  "apollo_capacitor.css",
  "apollo_date_nav.js",
  "apollo_date_nav.css",
  "apollo_oled.css"
];

for (const path of requiredFiles) {
  await access(path, constants.R_OK);
}

const config = await readFile("capacitor.config.ts", "utf8");
if (!config.includes("https://ubuntu-2gb-hel1-1.tailc5eaaa.ts.net")) {
  throw new Error("The private Apollo HTTPS origin is missing from capacitor.config.ts");
}
if (config.includes("cleartext: true")) {
  throw new Error("Cleartext traffic must stay disabled for the iOS app");
}

await copyFile("apollo_capacitor.js", "www/apollo_capacitor.js");
await copyFile("apollo_capacitor.css", "www/apollo_capacitor.css");
await copyFile("apollo_date_nav.js", "www/apollo_date_nav.js");
await copyFile("apollo_date_nav.css", "www/apollo_date_nav.css");
await copyFile("apollo_oled.css", "www/apollo_oled.css");

console.log("Apollo iOS assets are ready.");
