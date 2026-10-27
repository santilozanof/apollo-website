import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import test from "node:test";

const index = readFileSync(new URL("../../index.html", import.meta.url), "utf8");
const source = index.match(/<script>\s*\/\* APOLLO CALENDAR NAVIGATION V6 \*\/([\s\S]*?)<\/script>/)?.[1];
assert.ok(source, "Calendar jump picker script must exist");

class Element {
  constructor() {
    this.events = new Map();
    this.attributes = new Map();
    this.classes = new Set();
    this.classList = {
      add: name => this.classes.add(name),
      remove: name => this.classes.delete(name),
      contains: name => this.classes.has(name),
      toggle: name => this.classes.has(name) ? (this.classes.delete(name), false) : (this.classes.add(name), true),
    };
    this.style = {};
  }
  addEventListener(name, callback) { this.events.set(name, callback); }
  fire(name, event = {}) { return this.events.get(name)?.(event); }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name); }
  getBoundingClientRect() { return { left: 20, bottom: 120 }; }
  contains(target) { return target === this; }
  focus() { this.focused = true; }
}

test("Jump to Date survives viewport resize and submits the selected day once", async () => {
  const ids = new Map([
    "apolloWeekMonth", "apolloJumpMonth", "apolloJumpDay", "apolloJumpYear",
    "apolloJumpCancel", "apolloJumpGo",
  ].map(id => [id, new Element()]));
  let picker;
  let jumped;
  let jumpCount = 0;
  const windowEvents = new Map();
  const document = {
    body: { appendChild(element) { picker = element; } },
    createElement() { return new Element(); },
    getElementById(id) { return ids.get(id); },
    querySelectorAll() { return []; },
    addEventListener() {},
  };
  const window = {
    innerWidth: 393,
    apolloCalendarSelectedDate() { return new Date(2026, 9, 15); },
    async apolloCalendarJumpToDate(...date) { jumped = date; jumpCount += 1; },
    addEventListener(name, callback) { windowEvents.set(name, callback); },
  };
  runInNewContext(source, { document, window, console });

  ids.get("apolloWeekMonth").fire("click", { stopPropagation() {} });
  assert.equal(picker.classList.contains("active"), true);
  assert.equal(ids.get("apolloWeekMonth").getAttribute("aria-expanded"), "true");
  assert.equal(ids.get("apolloJumpDay").value, 15);
  windowEvents.get("resize")();
  assert.equal(picker.classList.contains("active"), true, "keyboard-sized resize must not dismiss picker");

  ids.get("apolloJumpDay").value = "20";
  await ids.get("apolloJumpGo").fire("click");
  assert.deepEqual(jumped, [2026, 9, 20]);
  assert.equal(jumpCount, 1);
  assert.equal(picker.classList.contains("active"), false);
  assert.equal(ids.get("apolloWeekMonth").getAttribute("aria-expanded"), "false");
});
