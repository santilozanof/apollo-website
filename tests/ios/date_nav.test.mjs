import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import test from "node:test";

const source = readFileSync(new URL("../../apollo_date_nav.js", import.meta.url), "utf8");

class Element {
  constructor(tagName = "DIV") {
    this.tagName = tagName;
    this.attributes = new Map();
    this.nodes = new Map();
    this.children = [];
    this.hidden = true;
    this.disabled = true;
    this.textContent = "";
  }
  querySelector(selector) { return this.nodes.get(selector) ?? null; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
}

test("Calendar and Routines share enabled Today behavior for both date states", () => {
  const pages = new Map();
  for (const [view, toolbar, context, add, today, previous, next] of [
    ["calendar", ".apollo-week-controls", "#apolloWeekMonth", "#apolloWeekAdd", "#apolloWeekToday", "#apolloWeekPrev", "#apolloWeekNext"],
    ["routines", ".routine-toolbar", "#routineDateLabel", "#routineCreate", "#routineToday", '[data-date-move="-1"]', '[data-date-move="1"]'],
  ]) {
    const page = new Element();
    const controls = new Element();
    controls.parentElement = { tagName: "HEADER", after() {} };
    page.nodes.set(toolbar, controls);
    for (const selector of [context, add, today, previous, next]) page.nodes.set(selector, new Element("BUTTON"));
    pages.set(`#${view}View`, page);
    pages.set(today, page.nodes.get(today));
  }
  const window = { ApolloDateNav: { version: 1 } };
  const document = {
    querySelector(selector) { return pages.get(selector) ?? null; },
    createElement(tag) { return new Element(tag.toUpperCase()); },
  };
  runInNewContext(source, { window, document });
  assert.equal(window.ApolloDateNav.version, 2, "bundled v2 must upgrade deployed v1");
  assert.equal(window.ApolloDateNav.mountCalendar(), true);
  assert.equal(window.ApolloDateNav.mountRoutines(), true);

  for (const [view, selector] of [["calendar", "#apolloWeekToday"], ["routines", "#routineToday"]]) {
    const button = pages.get(selector);
    for (const [selected, expected] of [[true, "date"], [false, "false"]]) {
      assert.equal(window.ApolloDateNav.setToday(view, selected), true);
      assert.equal(button.getAttribute("aria-current"), expected);
      assert.equal(button.disabled, false);
      assert.equal(button.hidden, false);
    }
  }
});
