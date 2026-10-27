/* Browser deep links for iPhone Shortcuts. A link prepares an action; only an
   intentional tap in Apollo can write personal data. No token enters a URL. */
(() => {
  "use strict";
  const query = new URLSearchParams(location.search);
  const fragment = new URLSearchParams(location.hash.replace(/^#/, ""));
  const tab = query.get("tab");
  if (!["tasks", "apollo", "routines"].includes(tab)) return;
  if (!Object.keys(Object.fromEntries(fragment)).length && tab !== "routines") return;
  // Remove private shortcut text from browser history before any navigation.
  history.replaceState(history.state, "", location.pathname + location.search);
  if (tab === "tasks") {
    window.openTasks?.();
    const title = String(fragment.get("title") || "").trim().slice(0, 240);
    const input = document.getElementById("apolloTaskTitle");
    if (input && title) {
      input.value = title;
      input.dispatchEvent(new Event("input", {bubbles: true}));
    }
    input?.focus({preventScroll: true});
  } else if (tab === "apollo") {
    window.openApollo?.();
    const prompt = String(fragment.get("prompt") || "").trim().slice(0, 4000);
    const input = document.getElementById("apolloInput");
    if (input && prompt) {
      input.value = prompt;
      input.dispatchEvent(new Event("input", {bubbles: true}));
    }
  } else if (query.get("view") === "water") {
    const amount = Number(query.get("amount"));
    if (![150, 250, 500, 710].includes(amount)) return;
    window.apolloShortcutWaterTarget = () => {
      const button = document.querySelector(`#routineHydration [data-water="${amount}"]`);
      if (!button) return false;
      button.classList.add("apollo-shortcut-target");
      button.scrollIntoView({block: "center", behavior: "smooth"});
      button.focus({preventScroll: true});
      window.apolloShortcutWaterTarget = null;
      return true;
    };
    window.openRoutines?.();
    window.apolloShortcutWaterTarget();
  }
})();
