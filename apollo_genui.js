/* Apollo Generative UI v2 — trusted, schema-driven response composition. */
(() => {
  "use strict";

  const TYPES = new Set([
    "text", "image", "image_gallery", "card", "carousel", "quiz",
    "checklist", "chart", "table", "progress", "form", "button_group",
    "date_picker", "slider", "media", "location", "code", "expandable",
    "status", "timeline", "calculator", "sources"
  ]);
  const ACTIONS = new Set([
    "submit_message", "task_toggle", "routine_action", "open_url", "copy",
    "spotify_open"
  ]);
  const CHART_KINDS = new Set(["line", "bar", "donut"]);
  const DATA_KINDS = new Set([
    "measured", "reported", "retrieved", "calculated", "estimated",
    "illustrative", "hypothetical"
  ]);
  const CALCULATIONS = new Set(["sum", "multiply", "divide", "percentage"]);
  const MAX_BLOCKS = 30;
  const MAX_ITEMS = 60;

  const str = (value, length = 4000) =>
    typeof value === "string" ? value.slice(0, length) : "";
  const finite = value => Number.isFinite(Number(value));
  const num = (value, min = 0, max = 100, fallback = min) =>
    finite(value) ? Math.max(min, Math.min(max, Number(value))) : fallback;
  const list = (value, length = MAX_ITEMS) =>
    Array.isArray(value) ? value.slice(0, length) : [];
  const unique = values => new Set(values).size === values.length;
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const svgEl = (tag, attributes = {}) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attributes).forEach(([name, value]) =>
      node.setAttribute(name, String(value))
    );
    return node;
  };
  const safeUrl = (value, image = false) => {
    try {
      const url = new URL(String(value || ""), location.href);
      if (
        ["https:", "http:"].includes(url.protocol)
        || (image && ["data:", "blob:"].includes(url.protocol))
        || url.origin === location.origin
      ) return url.href;
    } catch (_) {}
    return "";
  };
  function hash(value) {
    let result = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      result ^= value.charCodeAt(index);
      result = Math.imul(result, 16777619);
    }
    return (result >>> 0).toString(36);
  }
  const activeChatId = () => {
    try {
      return String(window.apolloGetActiveChatId?.() || "new");
    } catch (_) {
      return "new";
    }
  };
  const stateSignature = block => block.type === "quiz"
    ? hash(block.questions.map(question => question.id).sort().join("|"))
    : "v2";
  const keyFor = block =>
    `apollo-ui:v2:${activeChatId()}:${block.type}:${block.id}:${stateSignature(block)}`;
  function stateGet(block) {
    try {
      return JSON.parse(localStorage.getItem(keyFor(block)) || "{}") || {};
    } catch (_) {
      return {};
    }
  }
  function stateSet(block, value) {
    try { localStorage.setItem(keyFor(block), JSON.stringify(value)); } catch (_) {}
  }
  function stateClear(block) {
    try { localStorage.removeItem(keyFor(block)); } catch (_) {}
  }

  function validateAction(raw) {
    if (!raw || typeof raw !== "object" || !ACTIONS.has(raw.type)) return null;
    return {
      type: raw.type,
      label: str(raw.label, 80),
      value: str(raw.value, 1200),
      url: safeUrl(raw.url),
      task_id: Number.isInteger(Number(raw.task_id)) ? Number(raw.task_id) : null,
      payload: raw.payload && typeof raw.payload === "object" ? raw.payload : {},
      disabled: Boolean(raw.disabled)
    };
  }

  function validateQuestion(raw, index) {
    if (!raw || typeof raw !== "object") return null;
    const id = str(raw.id, 100) || `question-${index + 1}`;
    const question = str(raw.question, 1000);
    const options = list(raw.options, 12).map((option, optionIndex) => {
      if (!option || typeof option !== "object") return null;
      return {
        id: str(option.id, 100) || `option-${optionIndex + 1}`,
        label: str(option.label, 300),
        explanation: str(option.explanation, 1000),
        legacyCorrect: option.correct === true
      };
    }).filter(option => option && option.label);
    if (!question || options.length < 2 || !unique(options.map(option => option.id))) {
      return null;
    }
    let correctAnswerId = str(raw.correct_answer_id, 100);
    if (!correctAnswerId) {
      const legacy = options.filter(option => option.legacyCorrect);
      if (legacy.length === 1) correctAnswerId = legacy[0].id;
    }
    if (!correctAnswerId || !options.some(option => option.id === correctAnswerId)) {
      return null;
    }
    options.forEach(option => delete option.legacyCorrect);
    return {
      id,
      question,
      options,
      correct_answer_id: correctAnswerId,
      hint: str(raw.hint, 800),
      explanation: str(raw.explanation, 1500)
    };
  }

  function validateSources(rawItems) {
    const seen = new Set();
    return list(rawItems, 30).map((item, index) => {
      if (!item || typeof item !== "object") return null;
      const url = safeUrl(item.url);
      if (!url || seen.has(url)) return null;
      seen.add(url);
      return {
        id: str(item.id, 100) || `source-${index + 1}`,
        title: str(item.title, 300),
        publisher: str(item.publisher, 160),
        url,
        note: str(item.note, 500)
      };
    }).filter(Boolean);
  }

  function validate(raw, index) {
    if (!raw || typeof raw !== "object" || !TYPES.has(raw.type)) return null;
    const block = {
      type: raw.type,
      id: str(raw.id, 100) || `block-${index + 1}`,
      title: str(raw.title, 180),
      subtitle: str(raw.subtitle, 500),
      text: str(raw.text ?? raw.content, 16000),
      label: str(raw.label, 120),
      value: raw.value,
      min: num(raw.min, -100000, 100000, 0),
      max: num(raw.max, -100000, 100000, 100),
      step: num(raw.step, 0.001, 100000, 1),
      language: str(raw.language, 40),
      url: safeUrl(raw.url, true),
      poster: safeUrl(raw.poster, true),
      alt: str(raw.alt, 240),
      caption: str(raw.caption, 500),
      kind: str(raw.kind, 30),
      unit: str(raw.unit, 30),
      persisted: Boolean(raw.persisted),
      multiple: Boolean(raw.multiple),
      actions: list(raw.actions, 12).map(validateAction).filter(Boolean)
    };
    block.items = list(raw.items).map((item, itemIndex) => {
      if (typeof item === "string") return {id: String(itemIndex), label: str(item, 300)};
      if (!item || typeof item !== "object") return null;
      return {
        ...item,
        id: str(item.id, 100) || String(itemIndex),
        label: str(item.label ?? item.title, 300),
        title: str(item.title ?? item.label, 300),
        text: str(item.text ?? item.description, 1000),
        description: str(item.description, 1000),
        url: safeUrl(item.url, true),
        alt: str(item.alt, 240),
        caption: str(item.caption, 500),
        time: str(item.time, 80),
        value: finite(item.value) ? Number(item.value) : 0,
        completed: Boolean(item.completed),
        task_id: Number.isInteger(Number(item.task_id)) ? Number(item.task_id) : null,
        action: validateAction(item.action)
      };
    }).filter(Boolean);
    block.columns = list(raw.columns, 20).map(column =>
      typeof column === "string"
        ? {key: column, label: column}
        : column && typeof column === "object"
          ? {key: str(column.key, 80), label: str(column.label ?? column.key, 120)}
          : null
    ).filter(column => column && column.key);
    block.rows = list(raw.rows).filter(row => row && typeof row === "object");
    block.fields = list(raw.fields, 20).map((field, fieldIndex) => {
      if (!field || typeof field !== "object") return null;
      return {
        ...field,
        id: str(field.id ?? field.name, 80) || `field-${fieldIndex + 1}`,
        name: str(field.name ?? field.id, 80) || `field_${fieldIndex + 1}`,
        label: str(field.label, 120),
        type: str(field.type, 30),
        unit: str(field.unit, 30),
        placeholder: str(field.placeholder, 160),
        value: finite(field.value) ? Number(field.value) : str(field.value, 500),
        min: num(field.min, -100000, 100000, 0),
        max: num(field.max, -100000, 100000, 100000),
        step: num(field.step, 0.001, 100000, 1),
        required: Boolean(field.required),
        options: list(field.options, 30)
      };
    }).filter(Boolean);

    if (block.type === "quiz") {
      const rawQuestions = Array.isArray(raw.questions) && raw.questions.length ? raw.questions : [raw];
      block.questions = rawQuestions.map(validateQuestion);
      if (
        block.questions.some(question => !question)
        || !block.questions.length
        || !unique(block.questions.map(question => question.id))
      ) return null;
      block.allow_retry = raw.single_attempt === true ? false : raw.allow_retry !== false;
      block.single_attempt = !block.allow_retry;
    }
    if (block.type === "chart") {
      block.kind = CHART_KINDS.has(block.kind) ? block.kind : "line";
      block.x_label = str(raw.x_label, 80);
      block.y_label = str(raw.y_label, 80);
      block.data_kind = DATA_KINDS.has(raw.data_kind) ? raw.data_kind : "estimated";
      block.note = str(raw.note, 500);
      block.series = list(raw.series, 6).map((series, seriesIndex) => {
        if (!series || typeof series !== "object") return null;
        const items = list(series.items ?? series.values, 40).map((item, itemIndex) =>
          item && typeof item === "object" && finite(item.value)
            ? {id: str(item.id, 100) || String(itemIndex), label: str(item.label, 120), value: Number(item.value)}
            : null
        ).filter(Boolean);
        return items.length ? {
          id: str(series.id, 100) || `series-${seriesIndex + 1}`,
          label: str(series.label, 120) || `Series ${seriesIndex + 1}`,
          items
        } : null;
      }).filter(Boolean);
      if (!block.series.length && block.items.length) {
        block.series = [{id: "series-1", label: block.label || block.title, items: block.items}];
      }
      if (!block.series.length) return null;
    }
    if (block.type === "sources") {
      block.items = validateSources(raw.items);
      if (!block.items.length) return null;
    }
    if (block.type === "calculator") {
      block.operation = CALCULATIONS.has(raw.operation) ? raw.operation : "divide";
      block.operands = list(raw.operands, 8).map(value => str(value, 80)).filter(Boolean);
      block.output = raw.output && typeof raw.output === "object" ? {
        label: str(raw.output.label, 120) || "Result",
        unit: str(raw.output.unit, 30),
        decimals: Math.round(num(raw.output.decimals, 0, 6, 1))
      } : {label: "Result", unit: "", decimals: 1};
      if (block.fields.length < 1 || block.operands.length < 1) return null;
    }
    block.progress = num(raw.progress, 0, 1, 0);
    block.max = block.max === block.min ? block.min + 1 : block.max;
    return block;
  }

  function parse(content) {
    const source = String(content || "");
    const pattern = /```apollo-ui\s*\n([\s\S]*?)```/gi;
    let cursor = 0;
    let match;
    const parts = [];
    while ((match = pattern.exec(source))) {
      if (match.index > cursor) parts.push({type: "text", text: source.slice(cursor, match.index).trim()});
      try {
        const data = JSON.parse(match[1]);
        const rawBlocks = Array.isArray(data) ? data : data.blocks;
        const ids = new Set();
        list(rawBlocks, MAX_BLOCKS).forEach((raw, index) => {
          const block = validate(raw, index);
          if (!block || ids.has(block.id)) {
            parts.push({type: "invalid"});
            return;
          }
          ids.add(block.id);
          parts.push(block);
        });
      } catch (_) {
        parts.push({type: "invalid"});
      }
      cursor = pattern.lastIndex;
    }
    if (cursor < source.length) parts.push({type: "text", text: source.slice(cursor).trim()});
    return {structured: cursor > 0, parts: parts.filter(part => part.type !== "text" || part.text)};
  }

  function appendInline(parent, value, citations = new Map()) {
    const source = String(value || "");
    const pattern = /(\[[^\]]+\]\(https?:\/\/[^)]+\)|`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\$[^$]+\$|\[(\d+)\])/g;
    let cursor = 0;
    let match;
    while ((match = pattern.exec(source))) {
      if (match.index > cursor) parent.appendChild(document.createTextNode(source.slice(cursor, match.index)));
      const token = match[0];
      let node;
      if (token.startsWith("[")) {
        const link = token.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/);
        const citation = token.match(/^\[(\d+)\]$/);
        if (link) {
          node = el("a", null, link[1]);
          node.href = safeUrl(link[2]);
          node.target = "_blank";
          node.rel = "noopener noreferrer";
        } else if (citation && citations.has(citation[1])) {
          node = el("a", "apollo-citation-ref", `[${citation[1]}]`);
          node.href = `#${citations.get(citation[1])}`;
          node.setAttribute("aria-label", `Source ${citation[1]}`);
        } else node = document.createTextNode(token);
      } else if (token.startsWith("**")) node = el("strong", null, token.slice(2, -2));
      else if (token.startsWith("*")) node = el("em", null, token.slice(1, -1));
      else if (token.startsWith("`")) node = el("code", null, token.slice(1, -1));
      else if (token.startsWith("$")) node = el("span", "apollo-math", token.slice(1, -1));
      else node = document.createTextNode(token);
      parent.appendChild(node);
      cursor = pattern.lastIndex;
    }
    if (cursor < source.length) parent.appendChild(document.createTextNode(source.slice(cursor)));
  }

  function markdownTable(lines, start, citations) {
    if (start + 1 >= lines.length || !/^\s*\|?\s*:?-+/.test(lines[start + 1])) return null;
    const split = line => line.trim().replace(/^\||\|$/g, "").split("|").map(value => value.trim());
    const headers = split(lines[start]);
    const rows = [];
    let index = start + 2;
    while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
      rows.push(split(lines[index]));
      index += 1;
    }
    const wrap = el("div", "apollo-ui-table-wrap apollo-rich-table-wrap");
    const table = el("table", "apollo-ui-table apollo-rich-table");
    const head = el("thead");
    const headRow = el("tr");
    headers.forEach(header => {
      const cell = el("th");
      appendInline(cell, header, citations);
      headRow.appendChild(cell);
    });
    head.appendChild(headRow);
    table.appendChild(head);
    const body = el("tbody");
    rows.forEach(values => {
      const row = el("tr");
      headers.forEach((_, cellIndex) => {
        const cell = el("td");
        appendInline(cell, values[cellIndex] || "", citations);
        row.appendChild(cell);
      });
      body.appendChild(row);
    });
    table.appendChild(body);
    wrap.appendChild(table);
    return {node: wrap, next: index};
  }

  function richText(value, citations = new Map()) {
    const root = el("div", "apollo-rich-text");
    const lines = String(value || "").replace(/\r/g, "").split("\n");
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) { index += 1; continue; }
      if (/^```/.test(line.trim())) {
        const language = line.trim().slice(3).trim();
        const values = [];
        index += 1;
        while (index < lines.length && !/^```/.test(lines[index].trim())) {
          values.push(lines[index]);
          index += 1;
        }
        index += 1;
        const pre = el("pre", "apollo-ui-code");
        const code = el("code", null, values.join("\n"));
        if (language) code.dataset.language = language;
        pre.appendChild(code);
        root.appendChild(pre);
        continue;
      }
      const table = line.includes("|") ? markdownTable(lines, index, citations) : null;
      if (table) { root.appendChild(table.node); index = table.next; continue; }
      const heading = line.match(/^(#{1,3})\s+(.+)$/);
      if (heading) {
        const node = el(`h${heading[1].length}`, `apollo-rich-h${heading[1].length}`);
        appendInline(node, heading[2], citations);
        root.appendChild(node);
        index += 1;
        continue;
      }
      if (/^>\s?/.test(line)) {
        const quote = el("blockquote");
        appendInline(quote, line.replace(/^>\s?/, ""), citations);
        root.appendChild(quote);
        index += 1;
        continue;
      }
      const listMatch = line.match(/^\s*([-*]|\d+\.)\s+(.+)$/);
      if (listMatch) {
        const ordered = /\d+\./.test(listMatch[1]);
        const collection = el(ordered ? "ol" : "ul");
        while (index < lines.length) {
          const current = lines[index].match(/^\s*([-*]|\d+\.)\s+(.+)$/);
          if (!current || /\d+\./.test(current[1]) !== ordered) break;
          const item = el("li");
          appendInline(item, current[2], citations);
          collection.appendChild(item);
          index += 1;
        }
        root.appendChild(collection);
        continue;
      }
      if (/^---+$/.test(line.trim())) { root.appendChild(el("hr")); index += 1; continue; }
      const paragraphLines = [line];
      index += 1;
      while (
        index < lines.length && lines[index].trim()
        && !/^(#{1,3})\s+/.test(lines[index])
        && !/^\s*([-*]|\d+\.)\s+/.test(lines[index])
        && !/^>\s?/.test(lines[index])
        && !/^```/.test(lines[index].trim())
      ) {
        paragraphLines.push(lines[index]);
        index += 1;
      }
      const paragraph = el("p");
      paragraphLines.forEach((paragraphLine, lineIndex) => {
        if (lineIndex) paragraph.appendChild(el("br"));
        appendInline(paragraph, paragraphLine, citations);
      });
      root.appendChild(paragraph);
    }
    return root;
  }

  function header(block, extraClass = "") {
    const wrapper = el("div", `apollo-ui-pad ${extraClass}`.trim());
    if (block.title) wrapper.appendChild(el("div", "apollo-ui-title", block.title));
    if (block.subtitle) wrapper.appendChild(el("div", "apollo-ui-subtitle", block.subtitle));
    return wrapper;
  }
  function toast(node, text) {
    const notification = el("div", "apollo-ui-toast", text);
    node.appendChild(notification);
    setTimeout(() => notification.remove(), 1800);
  }
  async function actionRun(action, buttonNode, context = {}) {
    if (!action || action.disabled) return;
    const oldDisabled = buttonNode?.disabled;
    if (buttonNode) buttonNode.disabled = true;
    try {
      if (action.type === "submit_message") {
        const input = document.getElementById("apolloInput");
        if (!input) throw Error("Composer unavailable");
        input.value = action.value || context.value || action.label;
        input.dispatchEvent(new Event("input"));
        await window.apolloSendMessage?.();
      } else if (action.type === "task_toggle") {
        const response = await fetch("/api/tasks/update", {
          method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({task_id: action.task_id, completed: Boolean(context.completed)})
        });
        if (!response.ok) throw Error("Task update failed");
      } else if (action.type === "routine_action") {
        const response = await fetch("/api/routines/action", {
          method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            ...action.payload,
            ...(typeof context.completed === "boolean" ? {completed: context.completed} : {}),
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
          })
        });
        if (!response.ok) throw Error("Routine update failed");
      } else if (action.type === "open_url" || action.type === "spotify_open") {
        const url = safeUrl(action.url || action.value);
        if (!url) throw Error("Link unavailable");
        window.open(url, "_blank", "noopener,noreferrer");
      } else if (action.type === "copy") {
        await navigator.clipboard.writeText(action.value || context.value || "");
      }
      if (buttonNode?.closest(".apollo-ui-block")) toast(buttonNode.closest(".apollo-ui-block"), "Done");
    } catch (error) {
      if (buttonNode?.closest(".apollo-ui-block")) {
        toast(buttonNode.closest(".apollo-ui-block"), error.message || "Couldn’t complete that");
      }
      throw error;
    } finally {
      if (buttonNode) buttonNode.disabled = Boolean(oldDisabled || action.disabled);
    }
  }
  function actionButton(action, context) {
    const node = el("button", `apollo-ui-button${action.primary ? " primary" : ""}`, action.label || "Continue");
    node.type = "button";
    node.disabled = action.disabled;
    node.addEventListener("click", () => actionRun(action, node, context).catch(() => {}));
    return node;
  }
  function actions(node, block) {
    if (!block.actions.length) return;
    const row = el("div", "apollo-ui-actions");
    block.actions.forEach((action, index) => {
      action.primary = index === 0;
      row.appendChild(actionButton(action));
    });
    node.appendChild(row);
  }

  function openImage(source, alt) {
    const box = el("div", "apollo-ui-lightbox");
    const image = el("img");
    const close = el("button", null, "×");
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-label", alt || "Image preview");
    image.src = source;
    image.alt = alt || "";
    close.type = "button";
    close.setAttribute("aria-label", "Close image preview");
    const dismiss = () => { box.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = event => { if (event.key === "Escape") dismiss(); };
    close.addEventListener("click", dismiss);
    box.addEventListener("click", event => { if (event.target === box) dismiss(); });
    document.addEventListener("keydown", onKey);
    box.append(image, close);
    document.body.appendChild(box);
    close.focus();
  }
  function imageNode(item) {
    const figure = el("figure", "apollo-ui-figure");
    const image = el("img", "apollo-ui-image");
    image.alt = item.alt || item.title || "";
    image.loading = "lazy";
    image.src = item.url;
    image.addEventListener("error", () => figure.replaceWith(el("div", "apollo-ui-error", "Image unavailable")));
    image.addEventListener("click", () => openImage(image.src, image.alt));
    figure.appendChild(image);
    if (item.caption) figure.appendChild(el("figcaption", null, item.caption));
    return figure;
  }

  async function reconcileChecklist(block, items, state, apply) {
    if (!block.persisted) return;
    try {
      const options = {cache: "no-store", credentials: "same-origin"};
      const taskItems = items.filter(item => item.task_id);
      if (taskItems.length) {
        const response = await fetch("/api/tasks", options);
        if (!response.ok) throw Error("Task refresh failed");
        const tasks = new Map((await response.json()).tasks.map(task => [Number(task.id), Boolean(task.completed)]));
        taskItems.forEach(item => { if (tasks.has(item.task_id)) item.completed = tasks.get(item.task_id); });
      }
      const routineItems = items.filter(item => item.action?.type === "routine_action");
      if (routineItems.length) {
        const payload = routineItems[0].action.payload || {};
        const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        const query = new URLSearchParams({date: String(payload.date || ""), timezone: zone});
        const response = await fetch(`/api/routines?${query}`, options);
        if (!response.ok) throw Error("Routine refresh failed");
        const data = await response.json();
        const routines = new Map((data.routines || []).map(routine => [String(routine.id), routine]));
        routineItems.forEach(item => {
          const value = item.action.payload || {};
          const routine = routines.get(String(value.routine_id));
          const step = (routine?.steps || []).find(candidate => String(candidate.id) === String(value.step_id));
          if (step) item.completed = Boolean(step.complete);
        });
      }
      items.forEach(item => { state[item.id] = item.completed; });
      stateSet(block, state);
      apply();
    } catch (_) {}
  }

  function renderChecklist(block) {
    const root = el("section", "apollo-ui-block apollo-ui-checklist-block");
    const head = el("div", "apollo-ui-checklist-head");
    const titleRow = el("div", "apollo-ui-checklist-title-row");
    const title = el("div", "apollo-ui-title", block.title || "Checklist");
    const meta = el("div", "apollo-ui-progress-meta");
    const state = stateGet(block);
    const items = block.items.map(item => ({...item, completed: state[item.id] ?? item.completed}));
    const track = el("div", "apollo-ui-progress-track");
    const fill = el("div", "apollo-ui-progress-fill");
    const subtitleHasProgress = /\b\d+\s+of\s+\d+\b/i.test(block.subtitle);
    titleRow.append(title, meta);
    head.appendChild(titleRow);
    if (block.subtitle && !subtitleHasProgress) {
      head.appendChild(el("div", "apollo-ui-subtitle", block.subtitle));
    }
    track.appendChild(fill);
    head.appendChild(track);
    root.appendChild(head);
    const listNode = el("div", "apollo-ui-checklist");
    const refresh = () => {
      const done = items.filter(item => item.completed).length;
      meta.textContent = `${done} of ${items.length}`;
      fill.style.width = `${items.length ? done / items.length * 100 : 0}%`;
    };
    const apply = () => {
      items.forEach((item, index) => {
        const row = listNode.children[index];
        const input = row?.querySelector("input");
        if (input) input.checked = item.completed;
        row?.classList.toggle("done", item.completed);
      });
      refresh();
    };
    items.forEach(item => {
      const row = el("div", `apollo-ui-check${item.completed ? " done" : ""}`);
      const input = el("input");
      input.type = "checkbox";
      input.checked = item.completed;
      input.id = `apollo-check-${hash(keyFor(block) + item.id)}`;
      const label = el("label", null, item.label);
      label.htmlFor = input.id;
      input.addEventListener("change", async () => {
        const previous = item.completed;
        item.completed = input.checked;
        row.classList.toggle("done", item.completed);
        refresh();
        state[item.id] = item.completed;
        stateSet(block, state);
        const action = item.action || (item.task_id ? {type: "task_toggle", task_id: item.task_id} : null);
        if (action) {
          try { await actionRun(action, null, {completed: item.completed}); }
          catch (_) {
            item.completed = previous;
            input.checked = previous;
            row.classList.toggle("done", previous);
            state[item.id] = previous;
            stateSet(block, state);
            refresh();
            toast(root, "Update rolled back");
          }
        }
      });
      row.append(input, label);
      listNode.appendChild(row);
    });
    root.appendChild(listNode);
    refresh();
    reconcileChecklist(block, items, state, apply);
    return root;
  }

  function renderQuiz(block) {
    const root = el("section", "apollo-ui-block apollo-ui-quiz");
    root.dataset.quizId = block.id;
    const state = stateGet(block);
    state.current = Math.max(0, Math.min(block.questions.length, Number(state.current) || 0));
    state.attempts = state.attempts && typeof state.attempts === "object" ? state.attempts : {};
    state.solved = state.solved && typeof state.solved === "object" ? state.solved : {};
    state.singleAnswers = state.singleAnswers && typeof state.singleAnswers === "object" ? state.singleAnswers : {};
    const persist = () => stateSet(block, state);
    const paint = () => {
      root.replaceChildren();
      if (state.current >= block.questions.length) {
        const completed = Object.keys(state.solved).length;
        const totalAttempts = Object.values(state.attempts).reduce(
          (sum, values) => sum + (Array.isArray(values) ? values.length : 0), 0
        );
        const summary = header({
          title: block.title || "Quiz complete",
          subtitle: `${completed} of ${block.questions.length} correct · ${totalAttempts} attempt${totalAttempts === 1 ? "" : "s"}`
        }, "apollo-ui-quiz-summary");
        const restart = el("button", "apollo-ui-button", "Restart quiz");
        restart.type = "button";
        restart.addEventListener("click", () => {
          stateClear(block);
          state.current = 0;
          state.attempts = {};
          state.solved = {};
          state.singleAnswers = {};
          paint();
        });
        const row = el("div", "apollo-ui-quiz-nav");
        row.appendChild(restart);
        summary.appendChild(row);
        root.appendChild(summary);
        return;
      }
      const question = block.questions[state.current];
      const attempted = Array.isArray(state.attempts[question.id]) ? state.attempts[question.id] : [];
      const solvedId = state.solved[question.id];
      const singleAnswer = state.singleAnswers[question.id];
      const finished = Boolean(solvedId || singleAnswer);
      const inside = header({
        title: block.title || "Knowledge check",
        subtitle: `Question ${state.current + 1} of ${block.questions.length}`
      });
      const progressTrack = el("div", "apollo-ui-progress-track apollo-ui-quiz-progress");
      const progressFill = el("div", "apollo-ui-progress-fill");
      progressFill.style.width = `${state.current / block.questions.length * 100}%`;
      progressTrack.appendChild(progressFill);
      inside.appendChild(progressTrack);
      inside.appendChild(el("div", "apollo-ui-quiz-question", question.question));
      const options = el("div", "apollo-ui-quiz-options");
      const feedback = el("div", "apollo-ui-feedback");
      feedback.setAttribute("aria-live", "polite");
      question.options.forEach(option => {
        const optionButton = el("button", "apollo-ui-button apollo-ui-quiz-option", option.label);
        optionButton.type = "button";
        optionButton.dataset.optionId = option.id;
        const wasWrong = attempted.includes(option.id) && option.id !== question.correct_answer_id;
        const isCorrect = option.id === question.correct_answer_id;
        optionButton.classList.toggle("incorrect", wasWrong);
        if (solvedId && isCorrect) optionButton.classList.add("correct");
        if (singleAnswer) {
          optionButton.disabled = true;
          if (isCorrect) optionButton.classList.add("correct");
          if (singleAnswer === option.id && !isCorrect) optionButton.classList.add("incorrect");
        } else if (solvedId) optionButton.disabled = true;
        else if (wasWrong) optionButton.disabled = true;
        optionButton.addEventListener("click", () => {
          if (finished || attempted.includes(option.id)) return;
          state.attempts[question.id] = [...attempted, option.id];
          if (isCorrect) state.solved[question.id] = option.id;
          else if (block.single_attempt) state.singleAnswers[question.id] = option.id;
          persist();
          paint();
        });
        options.appendChild(optionButton);
      });
      const latestAttempt = (state.attempts[question.id] || []).at(-1);
      if (solvedId) {
        const correctOption = question.options.find(option => option.id === solvedId);
        feedback.textContent = correctOption?.explanation || question.explanation || "Correct.";
        feedback.classList.add("correct");
      } else if (singleAnswer) {
        const selected = question.options.find(option => option.id === singleAnswer);
        feedback.textContent = selected?.explanation || question.explanation || "Not quite.";
        feedback.classList.add("incorrect");
      } else if (latestAttempt) {
        feedback.textContent = question.hint || "Not quite — try another answer.";
        feedback.classList.add("incorrect");
      }
      inside.append(options, feedback);
      const navigation = el("div", "apollo-ui-quiz-nav");
      if (state.current > 0) {
        const previous = el("button", "apollo-ui-button", "Previous");
        previous.type = "button";
        previous.addEventListener("click", () => { state.current -= 1; persist(); paint(); });
        navigation.appendChild(previous);
      }
      if (solvedId || singleAnswer) {
        const next = el(
          "button", "apollo-ui-button primary",
          state.current === block.questions.length - 1 ? "View results" : "Next question"
        );
        next.type = "button";
        next.addEventListener("click", () => { state.current += 1; persist(); paint(); });
        navigation.appendChild(next);
      }
      inside.appendChild(navigation);
      root.appendChild(inside);
    };
    paint();
    return root;
  }

  const chartKindLabel = value => ({
    measured: "Measured", reported: "Reported", retrieved: "Retrieved",
    calculated: "Calculated", estimated: "Estimated",
    illustrative: "Illustrative", hypothetical: "Illustrative"
  })[value] || "Estimated";
  const numberLabel = (value, unit = "") => {
    const formatted = new Intl.NumberFormat(undefined, {maximumFractionDigits: 2}).format(value);
    return unit === "%" ? `${formatted}%` : `${formatted}${unit ? ` ${unit}` : ""}`;
  };
  function renderChart(block) {
    const root = el("section", "apollo-ui-block apollo-ui-chart");
    const chartHead = el("div", "apollo-ui-chart-head");
    const titles = el("div");
    if (block.title) titles.appendChild(el("div", "apollo-ui-title", block.title));
    if (block.subtitle) titles.appendChild(el("div", "apollo-ui-subtitle", block.subtitle));
    chartHead.append(titles, el("span", `apollo-ui-data-kind ${block.data_kind}`, chartKindLabel(block.data_kind)));
    root.appendChild(chartHead);
    const series = block.series;
    const values = series.flatMap(value => value.items.map(item => item.value));
    const width = 640, height = 270;
    const padding = {left: 64, right: 22, top: 18, bottom: 54};
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const svg = svgEl("svg", {viewBox: `0 0 ${width} ${height}`, role: "img"});
    svg.setAttribute("aria-label", `${block.title || "Chart"}. ${block.y_label || "Value"} by ${block.x_label || "category"}.`);
    if (block.kind === "donut") {
      const items = series[0].items.filter(item => item.value >= 0);
      const total = items.reduce((sum, item) => sum + item.value, 0) || 1;
      const radius = 76, circumference = 2 * Math.PI * radius;
      let offset = 0;
      items.forEach((item, index) => {
        const segment = svgEl("circle", {
          cx: width / 2, cy: 116, r: radius, fill: "none", "stroke-width": 24,
          "stroke-dasharray": `${item.value / total * circumference} ${circumference}`,
          "stroke-dashoffset": -offset, transform: `rotate(-90 ${width / 2} 116)`,
          class: `apollo-ui-chart-donut series-${index % 4}`
        });
        const title = svgEl("title");
        title.textContent = `${item.label}: ${numberLabel(item.value, block.unit)}`;
        segment.appendChild(title);
        svg.appendChild(segment);
        offset += item.value / total * circumference;
      });
      const totalText = svgEl("text", {x: width / 2, y: 112, class: "apollo-ui-chart-total"});
      totalText.textContent = numberLabel(total, block.unit);
      svg.appendChild(totalText);
      const totalLabel = svgEl("text", {x: width / 2, y: 132, class: "apollo-ui-chart-total-label"});
      totalLabel.textContent = block.y_label || "Total";
      svg.appendChild(totalLabel);
    } else {
      let minimum = Math.min(...values), maximum = Math.max(...values);
      if (block.kind === "bar" && minimum > 0) minimum = 0;
      if (minimum === maximum) { minimum = Math.min(0, minimum - 1); maximum += 1; }
      const range = maximum - minimum;
      const paddedMaximum = maximum + range * 0.08;
      const paddedMinimum = minimum - (minimum < 0 ? range * 0.05 : 0);
      const plotRange = paddedMaximum - paddedMinimum || 1;
      const yFor = value => padding.top + (paddedMaximum - value) / plotRange * plotHeight;
      const labels = series[0].items.map(item => item.label);
      const xFor = index => padding.left + (labels.length === 1 ? 0.5 : index / (labels.length - 1)) * plotWidth;
      const groupWidth = plotWidth / Math.max(labels.length, 1);
      for (let tick = 0; tick < 5; tick += 1) {
        const y = padding.top + plotHeight * tick / 4;
        const value = paddedMaximum - plotRange * tick / 4;
        svg.appendChild(svgEl("line", {x1: padding.left, x2: width - padding.right, y1: y, y2: y, class: "apollo-ui-chart-grid"}));
        const label = svgEl("text", {x: padding.left - 10, y: y + 4, class: "apollo-ui-chart-tick y"});
        label.textContent = numberLabel(value, block.unit);
        svg.appendChild(label);
      }
      const labelStep = Math.max(1, Math.ceil(labels.length / 7));
      labels.forEach((label, index) => {
        if (index % labelStep && index !== labels.length - 1) return;
        const tick = svgEl("text", {x: xFor(index), y: height - 26, class: "apollo-ui-chart-tick x"});
        tick.textContent = label;
        svg.appendChild(tick);
      });
      series.forEach((currentSeries, seriesIndex) => {
        if (block.kind === "bar") {
          currentSeries.items.forEach((item, itemIndex) => {
            const zero = yFor(Math.max(0, paddedMinimum));
            const y = yFor(item.value);
            const barWidth = Math.max(5, groupWidth * 0.64 / series.length);
            const x = padding.left + itemIndex * groupWidth + groupWidth * 0.18 + seriesIndex * barWidth;
            const bar = svgEl("rect", {
              x, y: Math.min(y, zero), width: barWidth, height: Math.max(2, Math.abs(zero - y)),
              rx: 4, class: `apollo-ui-chart-bar series-${seriesIndex % 4}`
            });
            const title = svgEl("title");
            title.textContent = `${item.label} · ${currentSeries.label}: ${numberLabel(item.value, block.unit)}`;
            bar.appendChild(title);
            svg.appendChild(bar);
          });
        } else {
          const points = currentSeries.items.map((item, itemIndex) => `${xFor(itemIndex)},${yFor(item.value)}`).join(" ");
          svg.appendChild(svgEl("polyline", {points, class: `apollo-ui-chart-series series-${seriesIndex % 4}`}));
          currentSeries.items.forEach((item, itemIndex) => {
            const marker = svgEl("circle", {cx: xFor(itemIndex), cy: yFor(item.value), r: 4, class: `apollo-ui-chart-marker series-${seriesIndex % 4}`});
            const title = svgEl("title");
            title.textContent = `${item.label} · ${currentSeries.label}: ${numberLabel(item.value, block.unit)}`;
            marker.appendChild(title);
            svg.appendChild(marker);
          });
        }
      });
      const xLabel = svgEl("text", {x: padding.left + plotWidth / 2, y: height - 4, class: "apollo-ui-chart-axis-label x"});
      xLabel.textContent = block.x_label || "Category";
      svg.appendChild(xLabel);
      const yLabel = svgEl("text", {
        x: 14, y: padding.top + plotHeight / 2, class: "apollo-ui-chart-axis-label y",
        transform: `rotate(-90 14 ${padding.top + plotHeight / 2})`
      });
      yLabel.textContent = block.y_label || "Value";
      svg.appendChild(yLabel);
    }
    root.appendChild(svg);
    const legend = el("div", "apollo-ui-legend");
    const legendItems = block.kind === "donut" ? series[0].items : series.length > 1 ? series : [];
    legendItems.forEach((item, index) => {
      const label = el("span", `series-${index % 4}`);
      label.append(el("i"), document.createTextNode(item.label));
      legend.appendChild(label);
    });
    if (legend.childElementCount) root.appendChild(legend);
    if (block.note) root.appendChild(el("div", "apollo-ui-chart-note", block.note));
    return root;
  }

  function renderCard(block) {
    const root = el("article", "apollo-ui-block apollo-ui-card");
    if (block.url) root.appendChild(imageNode(block));
    const copy = el("div", "apollo-ui-card-copy");
    if (block.title) copy.appendChild(el("div", "apollo-ui-title", block.title));
    if (block.text || block.subtitle) copy.appendChild(el("p", null, block.text || block.subtitle));
    actions(copy, block);
    root.appendChild(copy);
    return root;
  }
  function renderTable(block) {
    const root = el("section", "apollo-ui-block");
    const wrap = el("div", "apollo-ui-table-wrap");
    const table = el("table", "apollo-ui-table");
    const head = el("thead"), headingRow = el("tr");
    block.columns.forEach(column => headingRow.appendChild(el("th", null, column.label)));
    head.appendChild(headingRow);
    table.appendChild(head);
    const body = el("tbody");
    block.rows.forEach(values => {
      const row = el("tr");
      block.columns.forEach(column => row.appendChild(el("td", null, str(values[column.key], 500))));
      body.appendChild(row);
    });
    table.appendChild(body);
    if (block.title || block.subtitle) root.appendChild(header(block));
    wrap.appendChild(table);
    root.appendChild(wrap);
    return root;
  }
  function renderForm(block) {
    const root = el("form", "apollo-ui-block apollo-ui-pad apollo-ui-stack");
    if (block.title) root.appendChild(el("div", "apollo-ui-title", block.title));
    block.fields.forEach((field, index) => {
      const wrapper = el("div", "apollo-ui-field");
      const id = `apollo-field-${hash(keyFor(block) + index)}`;
      const label = el("label", null, field.label);
      label.htmlFor = id;
      let input;
      if (field.type === "select") {
        input = el("select", "apollo-ui-select");
        field.options.forEach(value => {
          const option = el("option", null, str(value.label ?? value, 120));
          option.value = str(value.value ?? value, 200);
          input.appendChild(option);
        });
      } else {
        input = el("input", "apollo-ui-input");
        input.type = ["date", "time", "number", "email"].includes(field.type) ? field.type : "text";
        input.value = str(field.value, 500);
        input.placeholder = field.placeholder;
      }
      input.id = id;
      input.name = field.name || `field_${index}`;
      input.required = field.required;
      wrapper.append(label, input);
      root.appendChild(wrapper);
    });
    const submit = el("button", "apollo-ui-button primary", block.actions[0]?.label || "Continue");
    submit.type = "submit";
    root.appendChild(submit);
    root.addEventListener("submit", event => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(root));
      const action = block.actions[0] || {type: "submit_message", value: ""};
      actionRun({...action, value: (action.value || "").replace(/\{(\w+)\}/g, (_, key) => values[key] || "")}, submit, {value: JSON.stringify(values)}).catch(() => {});
    });
    return root;
  }
  function calculate(operation, values) {
    if (!values.length || values.some(value => !finite(value))) return null;
    if (operation === "sum") return values.reduce((sum, value) => sum + value, 0);
    if (operation === "multiply") return values.reduce((result, value) => result * value, 1);
    if (operation === "percentage") return values.length >= 2 ? values[0] / 100 * values[1] : null;
    if (operation === "divide") return values.length >= 2 && values[1] !== 0 ? values[0] / values[1] : null;
    return null;
  }
  function renderCalculator(block) {
    const root = el("section", "apollo-ui-block apollo-ui-calculator");
    const inside = header(block);
    const state = stateGet(block);
    const grid = el("div", "apollo-ui-calculator-fields");
    const inputs = new Map();
    block.fields.forEach(field => {
      const wrapper = el("label", "apollo-ui-calculator-field");
      wrapper.appendChild(el("span", null, field.label));
      const inputRow = el("div", "apollo-ui-calculator-input-row");
      const input = el("input", "apollo-ui-input");
      input.type = "number";
      input.min = field.min;
      input.max = field.max;
      input.step = field.step;
      input.value = finite(state[field.id]) ? state[field.id] : finite(field.value) ? field.value : 0;
      inputRow.appendChild(input);
      if (field.unit) inputRow.appendChild(el("span", null, field.unit));
      wrapper.appendChild(inputRow);
      grid.appendChild(wrapper);
      inputs.set(field.id, input);
    });
    const output = el("div", "apollo-ui-calculator-output");
    const outputValue = el("strong");
    output.append(el("span", null, block.output.label), outputValue);
    const refresh = () => {
      const values = block.operands.map(id => Number(inputs.get(id)?.value));
      const result = calculate(block.operation, values);
      outputValue.textContent = result === null || !Number.isFinite(result)
        ? "—"
        : `${result.toFixed(block.output.decimals)}${block.output.unit ? ` ${block.output.unit}` : ""}`;
      inputs.forEach((input, id) => { state[id] = Number(input.value); });
      stateSet(block, state);
    };
    inputs.forEach(input => input.addEventListener("input", refresh));
    inside.append(grid, output);
    root.appendChild(inside);
    refresh();
    return root;
  }

  function prepareCitations(parts) {
    const citations = new Map(), seen = new Map();
    let number = 1;
    parts.filter(part => part.type === "sources").forEach(block => {
      block.items.forEach(item => {
        if (seen.has(item.url)) {
          item.citationNumber = seen.get(item.url).number;
          item.citationId = seen.get(item.url).id;
          item.duplicate = true;
          return;
        }
        const id = `apollo-source-${hash(activeChatId() + item.url)}`;
        item.citationNumber = number;
        item.citationId = id;
        seen.set(item.url, {number, id});
        citations.set(String(number), id);
        number += 1;
      });
    });
    return citations;
  }
  function renderSources(block) {
    const root = el("section", "apollo-ui-sources");
    root.appendChild(el("div", "apollo-ui-sources-title", block.title || "Sources"));
    const listNode = el("ol");
    block.items.filter(item => !item.duplicate).forEach(item => {
      const row = el("li");
      row.id = item.citationId;
      row.value = item.citationNumber;
      const link = el("a");
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      let fallback = "Source";
      try { fallback = new URL(item.url).hostname.replace(/^www\./, ""); } catch (_) {}
      const title = item.title || item.publisher || fallback;
      link.appendChild(el("span", "apollo-ui-source-title", title));
      if (item.publisher && item.publisher !== title) link.appendChild(el("span", "apollo-ui-source-publisher", item.publisher));
      row.appendChild(link);
      if (item.note) row.appendChild(el("div", "apollo-ui-source-note", item.note));
      listNode.appendChild(row);
    });
    root.appendChild(listNode);
    return root;
  }

  function renderGeneric(block, citations) {
    if (block.type === "checklist") return renderChecklist(block);
    if (block.type === "quiz") return renderQuiz(block);
    if (block.type === "chart") return renderChart(block);
    if (block.type === "table") return renderTable(block);
    if (block.type === "form") return renderForm(block);
    if (block.type === "card") return renderCard(block);
    if (block.type === "calculator") return renderCalculator(block);
    if (block.type === "sources") return renderSources(block);
    if (block.type === "text") return richText(block.text, citations);
    if (block.type === "image") return imageNode(block);
    if (block.type === "image_gallery") {
      const root = el("div", `apollo-ui-block apollo-ui-gallery${block.items.length === 1 ? " one" : ""}`);
      block.items.filter(item => item.url).forEach(item => root.appendChild(imageNode(item)));
      return root;
    }
    if (block.type === "carousel") {
      const root = el("div", "apollo-ui-carousel");
      block.items.forEach((item, index) => {
        const card = validate({type: "card", id: `${block.id}-card-${index + 1}`, ...item, actions: item.action ? [item.action] : []}, index);
        if (card) root.appendChild(renderCard(card));
      });
      return root;
    }
    if (block.type === "code") {
      const root = el("section", "apollo-ui-block");
      if (block.language) root.appendChild(el("div", "apollo-ui-code-head", block.language));
      const pre = el("pre", "apollo-ui-code");
      pre.appendChild(el("code", null, block.text));
      root.appendChild(pre);
      const row = el("div", "apollo-ui-pad apollo-ui-code-actions");
      row.appendChild(actionButton({type: "copy", label: "Copy", value: block.text}, {value: block.text}));
      root.appendChild(row);
      return root;
    }
    if (block.type === "expandable") {
      const details = el("details", "apollo-ui-block apollo-ui-expand");
      details.append(el("summary", null, block.title || "Show more"), richText(block.text, citations));
      return details;
    }
    if (block.type === "status") return el("div", "apollo-ui-block apollo-ui-status", block.text || block.title);
    if (block.type === "timeline") {
      const root = el("section", "apollo-ui-block apollo-ui-timeline");
      if (block.title) root.appendChild(el("div", "apollo-ui-title", block.title));
      block.items.forEach(item => {
        const row = el("div", "apollo-ui-timeline-item");
        if (item.time) row.appendChild(el("div", "apollo-ui-time", item.time));
        row.appendChild(el("div", null, item.title || item.label));
        if (item.text) row.appendChild(el("div", "apollo-ui-subtitle", item.text));
        root.appendChild(row);
      });
      return root;
    }
    if (block.type === "progress") {
      const root = el("section", "apollo-ui-block apollo-ui-pad");
      const top = el("div", "apollo-ui-row apollo-ui-between");
      top.append(el("div", "apollo-ui-title", block.title || block.label || "Progress"), el("div", "apollo-ui-progress-meta", `${Math.round(block.progress * 100)}%`));
      const track = el("div", "apollo-ui-progress-track"), fill = el("div", "apollo-ui-progress-fill");
      fill.style.width = `${block.progress * 100}%`;
      track.appendChild(fill);
      root.append(top, track);
      return root;
    }
    if (block.type === "button_group") {
      const root = el("section", "apollo-ui-block apollo-ui-pad");
      if (block.title) root.appendChild(el("div", "apollo-ui-title", block.title));
      actions(root, block);
      return root;
    }
    if (block.type === "date_picker" || block.type === "slider") {
      const root = el("section", "apollo-ui-block apollo-ui-pad apollo-ui-stack");
      const label = el("label", "apollo-ui-title", block.label || block.title);
      const input = el("input", block.type === "slider" ? "apollo-ui-slider" : "apollo-ui-input");
      const value = el("output", "apollo-ui-slider-value");
      input.type = block.type === "slider" ? "range" : "date";
      if (block.type === "slider") {
        input.min = block.min;
        input.max = block.max;
        input.step = block.step;
        input.value = num(block.value, block.min, block.max, block.min);
        const refresh = () => { value.textContent = `${input.value}${block.unit || ""}`; };
        input.addEventListener("input", refresh);
        refresh();
        root.append(label, input, value);
      } else {
        input.value = str(block.value, 20);
        root.append(label, input);
      }
      if (block.actions[0]) {
        const action = el("button", "apollo-ui-button", block.actions[0].label || "Continue");
        action.type = "button";
        action.addEventListener("click", () => actionRun({
          ...block.actions[0], value: (block.actions[0].value || "").replace("{value}", input.value)
        }, action, {value: input.value}).catch(() => {}));
        root.appendChild(action);
      }
      return root;
    }
    if (block.type === "media") {
      const root = el("section", "apollo-ui-block");
      const media = el(block.kind === "video" ? "video" : "audio", "apollo-ui-media");
      media.controls = true;
      media.preload = "metadata";
      media.src = block.url;
      if (block.poster && media.tagName === "VIDEO") media.poster = block.poster;
      root.appendChild(media);
      return root;
    }
    if (block.type === "location") {
      const root = el("section", "apollo-ui-block apollo-ui-location");
      const copy = el("div");
      copy.append(el("div", "apollo-ui-title", block.title || block.label), el("div", "apollo-ui-subtitle", block.text));
      root.append(el("div", "apollo-ui-location-pin", "⌖"), copy);
      actions(copy, block);
      return root;
    }
    return el("div", "apollo-ui-error", "This interactive content isn’t available.");
  }

  function render(content) {
    const parsed = parse(content);
    if (!parsed.structured) return null;
    const citations = prepareCitations(parsed.parts);
    const root = el("div", "apollo-rich-message");
    parsed.parts.forEach(part => root.appendChild(
      part.type === "invalid"
        ? el("div", "apollo-ui-block apollo-ui-error", "Some interactive content could not be displayed.")
        : renderGeneric(part, citations)
    ));
    return root;
  }

  function blockCopyText(block) {
    if (block.type === "text") return block.text;
    if (block.type === "quiz") return [
      block.title || "Quiz",
      ...block.questions.flatMap((question, index) => [
        `${index + 1}. ${question.question}`,
        ...question.options.map(option => `- ${option.label}`)
      ])
    ].join("\n");
    if (block.type === "table") return [
      block.title,
      block.columns.map(column => column.label).join("\t"),
      ...block.rows.map(row => block.columns.map(column => str(row[column.key], 500)).join("\t"))
    ].filter(Boolean).join("\n");
    if (block.type === "chart") return [
      block.title, block.subtitle,
      `${block.x_label || "Category"} · ${block.y_label || "Value"} · ${chartKindLabel(block.data_kind)}`,
      ...block.series.flatMap(series => series.items.map(item => `${series.label ? `${series.label} · ` : ""}${item.label}: ${numberLabel(item.value, block.unit)}`)),
      block.note
    ].filter(Boolean).join("\n");
    if (block.type === "sources") return [
      block.title || "Sources",
      ...block.items.filter(item => !item.duplicate).map(item =>
        `[${item.citationNumber}] ${item.publisher ? `${item.publisher} — ` : ""}${item.title || item.url}\n${item.url}`
      )
    ].join("\n");
    if (block.type === "checklist") return [
      block.title, ...block.items.map(item => `${item.completed ? "[x]" : "[ ]"} ${item.label}`)
    ].filter(Boolean).join("\n");
    if (block.type === "calculator") return [
      block.title, ...block.fields.map(field => `${field.label}: ${field.value}${field.unit || ""}`)
    ].filter(Boolean).join("\n");
    if (block.type === "code") return block.text;
    if (block.type === "image") return [block.caption || block.alt || block.title, block.url].filter(Boolean).join("\n");
    if (["image_gallery", "carousel", "timeline"].includes(block.type)) {
      return [block.title, ...block.items.map(item => [item.time, item.title || item.label, item.text].filter(Boolean).join(" — "))].filter(Boolean).join("\n");
    }
    return [block.title, block.subtitle, block.text].filter(Boolean).join("\n");
  }
  function copyText(content) {
    const parsed = parse(content);
    if (!parsed.structured) return String(content || "");
    prepareCitations(parsed.parts);
    return parsed.parts.filter(part => part.type !== "invalid").map(blockCopyText).filter(Boolean).join("\n\n");
  }

  function install() {
    const original = window.apolloAddMessage;
    if (typeof original !== "function" || original.apolloGenUIInstalled) return;
    const wrapped = function(role, content, attachments, autoScroll) {
      const text = original.call(this, role, content, attachments, autoScroll);
      if (role !== "assistant") return text;
      const rich = render(content);
      if (!rich) return text;
      const body = text.closest(".apollo-message-body");
      if (body) text.replaceWith(rich);
      return rich;
    };
    wrapped.apolloGenUIInstalled = true;
    window.apolloAddMessage = wrapped;
    window.apolloGenUIStreamingText = value => {
      const source = String(value || "");
      const completeStart = source.search(/```apollo-ui/i);
      if (completeStart >= 0) {
        return `${source.slice(0, completeStart).trim()}\n\nPreparing interactive content…`.trim();
      }
      const partialFence = source.match(/```(?:a(?:p(?:o(?:l(?:l(?:o(?:-(?:u(?:i)?)?)?)?)?)?)?)?)?$/i);
      return (partialFence ? source.slice(0, partialFence.index) : source).trim();
    };
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install, {once: true});
  else install();
  window.ApolloGenUI = {parse, validate, render, copyText, install, keyFor};
})();
