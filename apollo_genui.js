/* Apollo Generative UI v2 — trusted, schema-driven response composition. */
(() => {
  "use strict";

  const TYPES = new Set([
    "text", "image", "image_gallery", "card", "carousel", "quiz",
    "checklist", "chart", "table", "progress", "form", "button_group",
    "date_picker", "slider", "media", "location", "code", "expandable",
    "status", "timeline", "calculator", "selector", "function_explorer",
    "metric_trend", "sources"
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
  const EXPRESSION_ARITIES = {
    add: [2, 8], subtract: [2, 2], multiply: [2, 8], divide: [2, 2],
    power: [2, 2], min: [2, 8], max: [2, 8], negate: [1, 1],
    abs: [1, 1], sqrt: [1, 1], exp: [1, 1], ln: [1, 1],
    log10: [1, 1], round: [1, 1], floor: [1, 1], ceil: [1, 1]
  };
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
  function validateExpression(raw, fieldIds, depth = 0, budget = {remaining: 64}) {
    budget.remaining -= 1;
    if (budget.remaining < 0 || depth > 10) return null;
    if (typeof raw === "number" && Number.isFinite(raw)) return raw;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
    if (Object.keys(raw).length === 1 && typeof raw.field === "string") {
      return fieldIds.has(raw.field) ? {field: raw.field} : null;
    }
    if (Object.keys(raw).length === 1 && finite(raw.const)) return Number(raw.const);
    const operation = str(raw.op, 30).toLowerCase();
    const arity = EXPRESSION_ARITIES[operation];
    const args = Array.isArray(raw.args) ? raw.args : [];
    if (!arity || args.length < arity[0] || args.length > arity[1]) return null;
    const normalized = args.map(value => validateExpression(value, fieldIds, depth + 1, budget));
    if (normalized.some(value => value === null)) return null;
    return {op: operation, args: normalized};
  }
  function evaluateExpression(expression, values, depth = 0) {
    if (depth > 10) return null;
    if (typeof expression === "number") return Number.isFinite(expression) ? expression : null;
    if (!expression || typeof expression !== "object") return null;
    if (typeof expression.field === "string") {
      const value = Number(values instanceof Map ? values.get(expression.field) : values?.[expression.field]);
      return Number.isFinite(value) ? value : null;
    }
    const args = (expression.args || []).map(value => evaluateExpression(value, values, depth + 1));
    if (args.some(value => value === null)) return null;
    let result = null;
    switch (expression.op) {
      case "add": result = args.reduce((sum, value) => sum + value, 0); break;
      case "subtract": result = args[0] - args[1]; break;
      case "multiply": result = args.reduce((product, value) => product * value, 1); break;
      case "divide": result = args[1] === 0 ? null : args[0] / args[1]; break;
      case "power": result = Math.abs(args[1]) > 1000 ? null : Math.pow(args[0], args[1]); break;
      case "min": result = Math.min(...args); break;
      case "max": result = Math.max(...args); break;
      case "negate": result = -args[0]; break;
      case "abs": result = Math.abs(args[0]); break;
      case "sqrt": result = args[0] < 0 ? null : Math.sqrt(args[0]); break;
      case "exp": result = Math.exp(args[0]); break;
      case "ln": result = args[0] <= 0 ? null : Math.log(args[0]); break;
      case "log10": result = args[0] <= 0 ? null : Math.log10(args[0]); break;
      case "round": result = Math.round(args[0]); break;
      case "floor": result = Math.floor(args[0]); break;
      case "ceil": result = Math.ceil(args[0]); break;
      default: return null;
    }
    return Number.isFinite(result) && Math.abs(result) <= 1e308 ? result : null;
  }
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
      preset: str(raw.preset, 40),
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
        options: list(field.options, 30).map(option => {
          if (option && typeof option === "object" && finite(option.value)) {
            return {label: str(option.label ?? option.value, 80), value: Number(option.value)};
          }
          return finite(option) ? {label: str(option, 80), value: Number(option)} : null;
        }).filter(Boolean)
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
      if (block.fields.length < 1 || !unique(block.fields.map(field => field.id))) return null;
      if (block.fields.some(field => !["number", "slider", "segmented", "select", ""].includes(field.type))) return null;
      if (block.fields.some(field => ["segmented", "select"].includes(field.type) && field.options.length < 2)) return null;
      const fieldIds = new Set(block.fields.map(field => field.id));
      block.operation = CALCULATIONS.has(raw.operation) ? raw.operation : "";
      block.operands = list(raw.operands, 8).map(value => str(value, 80)).filter(Boolean);
      let expression = validateExpression(raw.expression, fieldIds);
      if (!expression && block.operation && block.operands.every(id => fieldIds.has(id))) {
        const references = block.operands.map(field => ({field}));
        if (block.operation === "sum") expression = {op: "add", args: references};
        if (block.operation === "multiply") expression = {op: "multiply", args: references};
        if (block.operation === "divide" && references.length >= 2) {
          expression = {op: "divide", args: references.slice(0, 2)};
        }
        if (block.operation === "percentage" && references.length >= 2) {
          expression = {op: "multiply", args: [
            {op: "divide", args: [references[0], 100]}, references[1]
          ]};
        }
      }
      if (!expression) return null;
      const normalizeOutput = (value, fallbackExpression) => {
        const output = value && typeof value === "object" ? value : {};
        const format = ["number", "currency", "percent"].includes(output.format)
          ? output.format : "number";
        const outputExpression = validateExpression(output.expression, fieldIds)
          || fallbackExpression;
        if (!outputExpression) return null;
        const currency = /^[A-Z]{3}$/.test(str(output.currency, 3).toUpperCase())
          ? str(output.currency, 3).toUpperCase() : "USD";
        return {
          label: str(output.label, 120) || "Result",
          unit: str(output.unit, 30),
          decimals: Math.round(num(output.decimals, 0, 6, format === "currency" ? 2 : 1)),
          format,
          currency,
          expression: outputExpression
        };
      };
      block.outputs = list(raw.outputs, 4).map(value => normalizeOutput(value, null)).filter(Boolean);
      if (!block.outputs.length) block.outputs = [normalizeOutput(raw.output, expression)].filter(Boolean);
      if (!block.outputs.length) return null;
      block.expression = block.outputs[0].expression;
      block.output = {...block.outputs[0]};
      delete block.output.expression;
      block.note = str(raw.note, 500);
    }
    if (block.type === "selector") {
      const rawOptions = list(raw.options ?? raw.items, 8);
      block.options = rawOptions.map((option, optionIndex) => {
        if (!option || typeof option !== "object") return null;
        const id = str(option.id, 100) || `option-${optionIndex + 1}`;
        const label = str(option.label ?? option.title, 120);
        const description = str(option.description ?? option.text, 2000);
        const details = list(option.details, 12).map(detail =>
          detail && typeof detail === "object" && str(detail.label, 120) && str(detail.value, 500)
            ? {label: str(detail.label, 120), value: str(detail.value, 500)}
            : null
        ).filter(Boolean);
        if (!label || (!description && !details.length)) return null;
        return {
          id, label, title: str(option.title, 180) || label,
          subtitle: str(option.subtitle, 500), description, details
        };
      });
      if (
        block.options.some(option => !option)
        || block.options.length < 2
        || !unique(block.options.map(option => option.id))
      ) return null;
      block.control = ["segmented", "select"].includes(raw.control) ? raw.control : "segmented";
      block.selected = block.options.some(option => option.id === raw.selected)
        ? raw.selected : block.options[0].id;
    }
    if (block.type === "button_group" && !block.actions.length) return null;
    if (block.type === "function_explorer") {
      if (
        block.preset !== "removable_hole"
        || ![raw.target, raw.value, raw.min, raw.max, raw.step].every(finite)
        || Number(raw.max) <= Number(raw.min)
        || Number(raw.step) <= 0
        || Number(raw.target) < Number(raw.min)
        || Number(raw.target) > Number(raw.max)
      ) return null;
      block.target = Number(raw.target);
      block.value = num(raw.value, Number(raw.min), Number(raw.max), Number(raw.min));
      block.min = Number(raw.min);
      block.max = Number(raw.max);
      block.step = Number(raw.step);
    }
    if (block.type === "metric_trend") {
      const rawItems = list(raw.items);
      if (rawItems.length < 2 || rawItems.some(item => !item || !finite(item.value))) return null;
      block.ranges = list(raw.ranges, 3)
        .map(value => Math.round(Number(value)))
        .filter((value, index, values) => value > 1 && value <= block.items.length && values.indexOf(value) === index);
      if (!block.ranges.length) block.ranges = [Math.min(7, block.items.length)];
      block.data_kind = DATA_KINDS.has(raw.data_kind) ? raw.data_kind : "measured";
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

  function renderMath(value, displayMode = false) {
    const node = el(displayMode ? "div" : "span", displayMode ? "apollo-math apollo-math-block" : "apollo-math");
    const expression = String(value || "").trim();
    try {
      if (!window.katex?.render) throw new Error("KaTeX unavailable");
      window.katex.render(expression, node, {
        displayMode,
        throwOnError: false,
        strict: "warn",
        trust: false,
        output: "htmlAndMathml"
      });
    } catch (_) {
      node.classList.add("apollo-math-fallback");
      node.textContent = expression;
    }
    return node;
  }

  function appendInline(parent, value, citations = new Map()) {
    const source = String(value || "");
    const pattern = /(`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)]+\)|\\\([\s\S]+?\\\)|\$(?!\s)(?:\\.|[^$\\])+?\$(?!\d)|\*\*[^*]+\*\*|\*[^*\n]+\*|\[(\d+)\])/g;
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
        } else if (citation) {
          node = el("a", "apollo-citation-ref", `[${citation[1]}]`);
          node.dataset.citationNumber = citation[1];
          if (citations.has(citation[1])) node.href = `#${citations.get(citation[1])}`;
          node.setAttribute("aria-label", `Source ${citation[1]}`);
        } else node = document.createTextNode(token);
      } else if (token.startsWith("**")) node = el("strong", null, token.slice(2, -2));
      else if (token.startsWith("*")) node = el("em", null, token.slice(1, -1));
      else if (token.startsWith("`")) node = el("code", null, token.slice(1, -1));
      else if (token.startsWith("\\(")) node = renderMath(token.slice(2, -2));
      else if (token.startsWith("$")) node = renderMath(token.slice(1, -1));
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
        const value = values[cellIndex] || "";
        if (/^[+-]?(?:\d[\d,.]*|\\\(.+\\\)|\$.+\$)$/.test(value)) {
          cell.classList.add("apollo-rich-table-number");
        }
        appendInline(cell, value, citations);
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
      const displayStart = line.trim();
      if (displayStart.startsWith("\\[") || displayStart.startsWith("$$")) {
        const opener = displayStart.startsWith("\\[") ? "\\[" : "$$";
        const closer = opener === "\\[" ? "\\]" : "$$";
        const values = [];
        let current = line.slice(line.indexOf(opener) + opener.length);
        let closed = false;
        while (true) {
          const end = current.indexOf(closer);
          if (end >= 0) {
            values.push(current.slice(0, end));
            closed = true;
            break;
          }
          values.push(current);
          index += 1;
          if (index >= lines.length) break;
          current = lines[index];
        }
        root.appendChild(renderMath(values.join("\n"), true));
        index += closed ? 1 : 0;
        continue;
      }
      if (/^\\(?:lim|frac|dfrac|tfrac|int|iint|sum|prod|begin|sqrt|vec|partial|nabla)\b/.test(displayStart)) {
        root.appendChild(renderMath(displayStart, true));
        index += 1;
        continue;
      }
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
    image.addEventListener("load", () => figure.classList.add("is-loaded"));
    image.addEventListener("error", () => {
      const container = figure.parentElement;
      figure.remove();
      if (container?.classList.contains("apollo-ui-card")) {
        container.classList.add("apollo-ui-card-text-only");
      } else if (container?.classList.contains("apollo-ui-gallery")) {
        const remaining = container.querySelectorAll(".apollo-ui-figure").length;
        container.classList.toggle("one", remaining === 1);
        if (!remaining) container.remove();
      }
    });
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
    let paintTimer = 0;
    const commitPaint = (content, direction) => {
      const oldHeight = root.getBoundingClientRect().height;
      root.classList.remove("is-transitioning");
      root.style.height = "";
      root.replaceChildren(content);
      const next = root.firstElementChild;
      if (next) next.dataset.quizTransition = direction;
      if (!oldHeight || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      const newHeight = root.scrollHeight;
      window.clearTimeout(paintTimer);
      root.style.height = `${oldHeight}px`;
      requestAnimationFrame(() => {
        root.classList.add("is-transitioning");
        root.style.height = `${newHeight}px`;
      });
      paintTimer = window.setTimeout(() => {
        root.classList.remove("is-transitioning");
        root.style.height = "";
      }, 260);
    };
    const paint = (direction = "settle") => {
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
          paint("reverse");
        });
        const row = el("div", "apollo-ui-quiz-nav");
        row.appendChild(restart);
        summary.appendChild(row);
        commitPaint(summary, direction);
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
      const questionNode = el("div", "apollo-ui-quiz-question");
      appendInline(questionNode, question.question);
      inside.appendChild(questionNode);
      const options = el("div", "apollo-ui-quiz-options");
      const feedback = el("div", "apollo-ui-feedback");
      feedback.setAttribute("aria-live", "polite");
      question.options.forEach(option => {
        const optionButton = el("button", "apollo-ui-button apollo-ui-quiz-option");
        appendInline(optionButton, option.label);
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
          paint("settle");
        });
        options.appendChild(optionButton);
      });
      const latestAttempt = (state.attempts[question.id] || []).at(-1);
      if (solvedId) {
        const correctOption = question.options.find(option => option.id === solvedId);
        appendInline(feedback, correctOption?.explanation || question.explanation || "Correct.");
        feedback.classList.add("correct");
      } else if (singleAnswer) {
        const selected = question.options.find(option => option.id === singleAnswer);
        appendInline(feedback, selected?.explanation || question.explanation || "Not quite.");
        feedback.classList.add("incorrect");
      } else if (latestAttempt) {
        appendInline(feedback, question.hint || "Not quite — try another answer.");
        feedback.classList.add("incorrect");
      }
      inside.append(options, feedback);
      const navigation = el("div", "apollo-ui-quiz-nav");
      if (state.current > 0) {
        const previous = el("button", "apollo-ui-button", "Previous");
        previous.type = "button";
        previous.addEventListener("click", () => { state.current -= 1; persist(); paint("reverse"); });
        navigation.appendChild(previous);
      }
      if (solvedId || singleAnswer) {
        const next = el(
          "button", "apollo-ui-button primary",
          state.current === block.questions.length - 1 ? "View results" : "Next question"
        );
        next.type = "button";
        next.addEventListener("click", () => { state.current += 1; persist(); paint("forward"); });
        navigation.appendChild(next);
      }
      inside.appendChild(navigation);
      commitPaint(inside, direction);
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
  function formatCalculatedValue(result, output) {
    if (result === null || !Number.isFinite(result)) return "—";
    if (output.format === "currency") {
      try {
        return new Intl.NumberFormat(undefined, {
          style: "currency", currency: output.currency || "USD",
          minimumFractionDigits: output.decimals,
          maximumFractionDigits: output.decimals
        }).format(result);
      } catch (_) {}
    }
    if (output.format === "percent") {
      try {
        return new Intl.NumberFormat(undefined, {
          style: "percent", minimumFractionDigits: output.decimals,
          maximumFractionDigits: output.decimals
        }).format(result);
      } catch (_) {}
    }
    const value = result.toLocaleString(undefined, {
      minimumFractionDigits: output.decimals,
      maximumFractionDigits: output.decimals
    });
    return `${value}${output.unit ? ` ${output.unit}` : ""}`;
  }
  function renderCalculator(block) {
    const root = el("section", "apollo-ui-block apollo-ui-calculator");
    const inside = header(block);
    const state = stateGet(block);
    const grid = el("div", "apollo-ui-calculator-fields");
    const inputs = new Map();
    block.fields.forEach(field => {
      const wrapper = el("div", `apollo-ui-calculator-field ${field.type || "number"}`);
      const fieldHead = el("div", "apollo-ui-calculator-field-head");
      fieldHead.appendChild(el("span", null, field.label));
      const inputRow = el("div", "apollo-ui-calculator-input-row");
      const initial = finite(state[field.id]) ? Number(state[field.id]) : Number(field.value) || 0;
      let input;
      if (field.type === "segmented") {
        input = el("input");
        input.type = "hidden";
        input.value = initial;
        const segmented = el("div", "apollo-ui-segmented");
        segmented.setAttribute("role", "radiogroup");
        segmented.setAttribute("aria-label", field.label);
        const select = value => {
          input.value = value;
          [...segmented.children].forEach(button => {
            const active = Number(button.dataset.value) === Number(value);
            button.classList.toggle("active", active);
            button.setAttribute("aria-checked", String(active));
          });
        };
        field.options.forEach(option => {
          const button = el("button", "apollo-ui-segment", option.label);
          button.type = "button";
          button.dataset.value = option.value;
          button.setAttribute("role", "radio");
          button.addEventListener("click", () => {
            select(option.value);
            input.dispatchEvent(new Event("input", {bubbles: true}));
          });
          segmented.appendChild(button);
        });
        if (!field.options.some(option => Number(option.value) === initial)) {
          input.value = field.options[0].value;
        }
        select(input.value);
        inputRow.append(segmented, input);
      } else if (field.type === "select") {
        input = el("select", "apollo-ui-select");
        field.options.forEach(option => {
          const optionNode = el("option", null, option.label);
          optionNode.value = option.value;
          input.appendChild(optionNode);
        });
        input.value = field.options.some(option => Number(option.value) === initial)
          ? String(initial) : String(field.options[0].value);
        inputRow.appendChild(input);
      } else if (field.type === "slider") {
        input = el("input", "apollo-ui-slider");
        input.type = "range";
        input.min = field.min;
        input.max = field.max;
        input.step = field.step;
        input.value = initial;
        const current = el("output", "apollo-ui-slider-value");
        const labelValue = () => {
          current.textContent = `${input.value}${field.unit ? ` ${field.unit}` : ""}`;
        };
        input.addEventListener("input", labelValue);
        labelValue();
        fieldHead.appendChild(current);
        inputRow.appendChild(input);
      } else {
        input = el("input", "apollo-ui-input");
        input.type = "number";
        input.min = field.min;
        input.max = field.max;
        input.step = field.step;
        input.value = initial;
        inputRow.appendChild(input);
        if (field.unit) inputRow.appendChild(el("span", null, field.unit));
      }
      wrapper.append(fieldHead, inputRow);
      grid.appendChild(wrapper);
      inputs.set(field.id, input);
    });
    const output = el("div", "apollo-ui-calculator-outputs");
    const outputRows = block.outputs.map((definition, index) => {
      const row = el("div", `apollo-ui-calculator-output${index === 0 ? " primary" : ""}`);
      const value = el("strong");
      row.append(el("span", null, definition.label), value);
      output.appendChild(row);
      return {definition, value};
    });
    const refresh = () => {
      const values = new Map([...inputs].map(([id, input]) => [id, Number(input.value)]));
      outputRows.forEach(({definition, value}) => {
        const result = evaluateExpression(definition.expression, values);
        value.textContent = formatCalculatedValue(result, definition);
        value.classList.remove("is-updating");
        void value.offsetWidth;
        value.classList.add("is-updating");
      });
      inputs.forEach((input, id) => { state[id] = Number(input.value); });
      stateSet(block, state);
    };
    inputs.forEach(input => input.addEventListener("input", refresh));
    inside.append(grid, output);
    if (block.note) inside.appendChild(el("div", "apollo-ui-calculator-note", block.note));
    root.appendChild(inside);
    refresh();
    return root;
  }

  function renderSelector(block) {
    const root = el("section", "apollo-ui-block apollo-ui-selector");
    const inside = header(block);
    const state = stateGet(block);
    let selected = block.options.some(option => option.id === state.selected)
      ? state.selected : block.selected;
    const detail = el("div", "apollo-ui-selector-detail");
    const updateDetail = () => {
      const option = block.options.find(item => item.id === selected) || block.options[0];
      selected = option.id;
      detail.replaceChildren();
      const copy = el("div", "apollo-ui-selector-copy");
      copy.appendChild(el("div", "apollo-ui-selector-title", option.title || option.label));
      if (option.subtitle) copy.appendChild(el("div", "apollo-ui-subtitle", option.subtitle));
      if (option.description) copy.appendChild(richText(option.description, new Map()));
      detail.appendChild(copy);
      if (option.details.length) {
        const grid = el("dl", "apollo-ui-selector-details");
        option.details.forEach(item => {
          const pair = el("div", "apollo-ui-selector-detail-row");
          pair.append(el("dt", null, item.label), el("dd", null, item.value));
          grid.appendChild(pair);
        });
        detail.appendChild(grid);
      }
      state.selected = selected;
      stateSet(block, state);
    };

    if (block.control === "select") {
      const control = el("select", "apollo-ui-select apollo-ui-selector-control");
      control.setAttribute("aria-label", block.title || "Choose an option");
      block.options.forEach(option => {
        const node = el("option", null, option.label);
        node.value = option.id;
        control.appendChild(node);
      });
      control.value = selected;
      control.addEventListener("change", () => {
        selected = control.value;
        updateDetail();
      });
      inside.appendChild(control);
    } else {
      const controls = el("div", "apollo-ui-segmented apollo-ui-selector-controls");
      controls.setAttribute("role", "radiogroup");
      controls.setAttribute("aria-label", block.title || "Choose an option");
      block.options.forEach(option => {
        const button = el("button", "apollo-ui-segment", option.label);
        button.type = "button";
        button.setAttribute("role", "radio");
        const refresh = () => {
          const active = selected === option.id;
          button.classList.toggle("active", active);
          button.setAttribute("aria-checked", String(active));
        };
        button.addEventListener("click", () => {
          selected = option.id;
          [...controls.children].forEach(child => {
            const active = child === button;
            child.classList.toggle("active", active);
            child.setAttribute("aria-checked", String(active));
          });
          updateDetail();
        });
        controls.appendChild(button);
        refresh();
      });
      inside.appendChild(controls);
    }
    inside.appendChild(detail);
    root.appendChild(inside);
    updateDetail();
    return root;
  }

  function renderFunctionExplorer(block) {
    const root = el("section", "apollo-ui-block apollo-ui-function-explorer");
    const inside = header(block);
    const state = stateGet(block);
    const target = block.target;
    const sliderHead = el("div", "apollo-ui-row apollo-ui-between");
    const sliderLabel = el("label", "apollo-ui-title", "Adjust x");
    const sliderValue = el("output", "apollo-ui-slider-value");
    const slider = el("input", "apollo-ui-slider");
    slider.type = "range";
    slider.min = block.min;
    slider.max = block.max;
    slider.step = block.step;
    slider.value = finite(state.value)
      ? num(state.value, block.min, block.max, block.value)
      : block.value;
    sliderLabel.htmlFor = `apollo-explorer-${hash(keyFor(block))}`;
    slider.id = sliderLabel.htmlFor;
    sliderHead.append(sliderLabel, sliderValue);

    const formula = el("div", "apollo-ui-explorer-formula");
    appendInline(formula, `\\(f(x)=\\frac{x^2-${target ** 2}}{x-${target}}=x+${target}\\), for \\(x\\ne ${target}\\)`);
    const readouts = el("div", "apollo-ui-explorer-readouts");
    const current = el("div");
    const currentLabel = el("span", null, "f(x)");
    const currentValue = el("strong");
    current.append(currentLabel, currentValue);
    const limit = el("div");
    limit.append(el("span", null, `Limit as x → ${target}`), el("strong", null, String(2 * target)));
    readouts.append(current, limit);
    const graph = svgEl("svg", {viewBox: "0 0 360 150", role: "img"});
    graph.setAttribute("aria-label", `Graph approaching a removable hole at x equals ${target}`);

    const drawGraph = value => {
      graph.replaceChildren();
      const width = 360, height = 150, pad = 18;
      const yMin = block.min + target;
      const yMax = block.max + target;
      const xFor = x => pad + (x - block.min) / (block.max - block.min) * (width - pad * 2);
      const yFor = y => height - pad - (y - yMin) / Math.max(yMax - yMin, 1) * (height - pad * 2);
      graph.append(
        svgEl("line", {x1: pad, x2: width - pad, y1: height - pad, y2: height - pad, class: "apollo-ui-chart-grid"}),
        svgEl("line", {x1: pad, x2: pad, y1: pad, y2: height - pad, class: "apollo-ui-chart-grid"})
      );
      const left = [], right = [];
      for (let index = 0; index <= 64; index += 1) {
        const x = block.min + (block.max - block.min) * index / 64;
        const point = `${xFor(x)},${yFor(x + target)}`;
        (x < target ? left : right).push(point);
      }
      [left, right].filter(points => points.length).forEach(points => {
        graph.appendChild(svgEl("polyline", {points: points.join(" "), class: "apollo-ui-chart-series"}));
      });
      graph.appendChild(svgEl("circle", {
        cx: xFor(target), cy: yFor(2 * target), r: 5,
        class: "apollo-ui-explorer-hole"
      }));
      if (Math.abs(value - target) >= Math.max(block.step / 2, 1e-9)) {
        graph.appendChild(svgEl("circle", {
          cx: xFor(value), cy: yFor(value + target), r: 4,
          class: "apollo-ui-chart-marker apollo-ui-explorer-marker"
        }));
      }
    };
    const refresh = () => {
      const value = Number(slider.value);
      const atHole = Math.abs(value - target) < Math.max(block.step / 2, 1e-9);
      sliderValue.textContent = `x = ${Number(value.toFixed(6))}`;
      currentValue.textContent = atHole ? "undefined" : String(Number((value + target).toFixed(4)));
      currentValue.classList.toggle("is-undefined", atHole);
      state.value = value;
      stateSet(block, state);
      drawGraph(value);
    };
    slider.addEventListener("input", refresh);
    inside.append(formula, sliderHead, slider, graph, readouts);
    root.appendChild(inside);
    refresh();
    return root;
  }

  function renderMetricTrend(block) {
    const root = el("section", "apollo-ui-block apollo-ui-metric-trend");
    const inside = header(block);
    const state = stateGet(block);
    let range = block.ranges.includes(Number(state.range))
      ? Number(state.range)
      : block.ranges[0];
    const rangeControls = el("div", "apollo-ui-segmented apollo-ui-trend-ranges");
    rangeControls.setAttribute("role", "radiogroup");
    rangeControls.setAttribute("aria-label", "Trend range");
    const summary = el("div", "apollo-ui-trend-summary");
    const chartHost = el("div", "apollo-ui-trend-chart-host");
    const detailRow = el("div", "apollo-ui-trend-detail-row");
    const daySelect = el("select", "apollo-ui-select apollo-ui-trend-select");
    daySelect.setAttribute("aria-label", "Selected day");
    const detail = el("div", "apollo-ui-trend-detail");
    detailRow.append(daySelect, detail);

    const paintDetail = points => {
      const selected = points.find(item => item.id === daySelect.value) || points.at(-1);
      if (!selected) return;
      daySelect.value = selected.id;
      detail.replaceChildren(
        el("strong", null, numberLabel(selected.value, block.unit)),
        el("span", null, selected.description || selected.label)
      );
      state.point = selected.id;
      stateSet(block, state);
    };
    const paint = () => {
      const points = block.items.slice(-range);
      const average = points.reduce((total, item) => total + item.value, 0) / points.length;
      summary.replaceChildren(
        el("span", null, `${range}-day average`),
        el("strong", null, numberLabel(average, block.unit))
      );
      const chartBlock = validate({
        type: "chart", id: `${block.id}-${range}`, kind: "line",
        x_label: "Day", y_label: block.title || "Value", unit: block.unit,
        data_kind: block.data_kind,
        items: points.map(item => ({id: item.id, label: item.label, value: item.value}))
      }, 0);
      const chart = renderChart(chartBlock);
      chart.classList.add("apollo-ui-trend-chart");
      chartHost.replaceChildren(chart);
      daySelect.replaceChildren();
      points.forEach(item => {
        const option = el("option", null, item.label);
        option.value = item.id;
        daySelect.appendChild(option);
      });
      if (points.some(item => item.id === state.point)) daySelect.value = state.point;
      else daySelect.value = points.at(-1)?.id || "";
      paintDetail(points);
      [...rangeControls.children].forEach(button => {
        const active = Number(button.dataset.range) === range;
        button.classList.toggle("active", active);
        button.setAttribute("aria-checked", String(active));
      });
      state.range = range;
      stateSet(block, state);
    };
    block.ranges.forEach(value => {
      const button = el("button", "apollo-ui-segment", `${value} days`);
      button.type = "button";
      button.dataset.range = value;
      button.setAttribute("role", "radio");
      button.addEventListener("click", () => { range = value; paint(); });
      rangeControls.appendChild(button);
    });
    daySelect.addEventListener("change", () => paintDetail(block.items.slice(-range)));
    if (block.ranges.length > 1) inside.appendChild(rangeControls);
    inside.append(summary, chartHost, detailRow);
    root.appendChild(inside);
    paint();
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
    if (block.type === "selector") return renderSelector(block);
    if (block.type === "function_explorer") return renderFunctionExplorer(block);
    if (block.type === "metric_trend") return renderMetricTrend(block);
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
    if (!parsed.structured) {
      const root = el("div", "apollo-rich-message");
      root.appendChild(richText(content));
      return root;
    }
    const citations = prepareCitations(parsed.parts);
    const root = el("div", "apollo-rich-message");
    parsed.parts.forEach(part => root.appendChild(
      part.type === "invalid"
        ? el("div", "apollo-ui-block apollo-ui-error", "Some interactive content could not be displayed.")
        : renderGeneric(part, citations)
    ));
    return root;
  }

  function hasIncompleteInline(value) {
    const source = String(value || "");
    const withoutCode = source.replace(/`[^`]*`/g, "");
    if ((source.match(/(?<!\\)`/g) || []).length % 2) return true;
    if (withoutCode.lastIndexOf("\\(") > withoutCode.lastIndexOf("\\)")) return true;
    if ((withoutCode.match(/(?<!\\)\$\$(?!\$)/g) || []).length % 2) return true;
    const dollars = withoutCode.match(/(?<!\\)\$(?!\s|\$)/g) || [];
    if (dollars.length % 2) return true;
    if ((withoutCode.match(/\*\*/g) || []).length % 2) return true;
    if (/\[[^\]]*$|\[[^\]]+\]\([^)]*$/.test(withoutCode)) return true;
    return false;
  }

  function completeStreamSegments(value, final = false) {
    const source = String(value || "").replace(/\r/g, "");
    const segments = [];
    let cursor = 0;
    const lineEnd = start => {
      const end = source.indexOf("\n", start);
      return end < 0 ? source.length : end + 1;
    };
    while (cursor < source.length) {
      while (cursor < source.length && /\s/.test(source[cursor])) cursor += 1;
      if (cursor >= source.length) break;
      const start = cursor;
      const tail = source.slice(start);
      const fence = tail.match(/^```[^\n]*\n/);
      if (fence) {
        const bodyStart = start + fence[0].length;
        const closing = source.slice(bodyStart).match(/^```[ \t]*(?:\n|$)/m);
        if (!closing) {
          if (!final) return {segments, pending: source.slice(start)};
          segments.push(source.slice(start));
          cursor = source.length;
          continue;
        }
        const end = bodyStart + closing.index + closing[0].length;
        segments.push(source.slice(start, end).trim());
        cursor = end;
        continue;
      }
      const opener = tail.startsWith("\\[") ? "\\[" : tail.startsWith("$$") ? "$$" : "";
      if (opener) {
        const closer = opener === "\\[" ? "\\]" : "$$";
        const closeAt = source.indexOf(closer, start + opener.length);
        if (closeAt < 0) {
          if (!final) return {segments, pending: source.slice(start)};
          segments.push(source.slice(start));
          cursor = source.length;
          continue;
        }
        const end = lineEnd(closeAt + closer.length);
        segments.push(source.slice(start, end).trim());
        cursor = end;
        continue;
      }
      const firstEnd = source.indexOf("\n", start);
      const firstLine = source.slice(start, firstEnd < 0 ? source.length : firstEnd);
      if (/^(#{1,6})\s+|^---+$/.test(firstLine.trim()) && firstEnd >= 0) {
        segments.push(firstLine.trim());
        cursor = firstEnd + 1;
        continue;
      }
      const boundary = source.slice(start).search(/\n[ \t]*\n/);
      if (boundary < 0) {
        if (!final) return {segments, pending: source.slice(start)};
        segments.push(source.slice(start).trim());
        cursor = source.length;
        continue;
      }
      const end = start + boundary;
      const segment = source.slice(start, end).trim();
      if (hasIncompleteInline(segment) && !final) {
        return {segments, pending: source.slice(start)};
      }
      if (segment) segments.push(segment);
      cursor = start + boundary + source.slice(start + boundary).match(/^\n[ \t]*\n/)[0].length;
    }
    return {segments, pending: source.slice(cursor)};
  }

  function createStreamRenderer(host, options = {}) {
    const root = el("div", "apollo-rich-message apollo-stream-content");
    const indicator = el("div", "apollo-stream-indicator");
    indicator.setAttribute("role", "status");
    indicator.setAttribute("aria-label", "Apollo is continuing the response");
    indicator.append(el("i"), el("i"), el("i"));
    const scrollElement = options.scrollElement || document.getElementById("apolloMessages");
    let segments = [];
    let lastSource = "";
    let finished = false;
    host.replaceChildren(root);

    const nearBottom = () => !scrollElement
      || scrollElement.scrollHeight - scrollElement.scrollTop - scrollElement.clientHeight < 140;
    const settleScroll = anchored => {
      if (anchored && scrollElement) scrollElement.scrollTop = scrollElement.scrollHeight;
    };
    const refreshCitations = () => {
      const sources = [...root.querySelectorAll(".apollo-ui-sources li[id]")];
      root.querySelectorAll(".apollo-citation-ref[data-citation-number]").forEach(link => {
        const source = sources[Number(link.dataset.citationNumber) - 1];
        if (source) link.href = `#${source.id}`;
      });
    };
    const appendSegment = segment => {
      const rendered = render(segment);
      while (rendered.firstChild) root.appendChild(rendered.firstChild);
      refreshCitations();
    };
    const rebuild = next => {
      root.replaceChildren();
      segments = [];
      next.forEach(segment => { appendSegment(segment); segments.push(segment); });
    };
    const update = (value, isFinal = false) => {
      if (finished) return root;
      const source = String(value || "");
      const anchored = nearBottom();
      const next = completeStreamSegments(source, isFinal).segments;
      const diverged = !source.startsWith(lastSource)
        || segments.some((segment, index) => next[index] !== segment);
      if (diverged) rebuild(next);
      else for (let index = segments.length; index < next.length; index += 1) {
        appendSegment(next[index]);
        segments.push(next[index]);
      }
      lastSource = source;
      indicator.remove();
      if (!isFinal) root.appendChild(indicator);
      else finished = true;
      settleScroll(anchored);
      return root;
    };
    return {
      update: value => update(value, false),
      finish: value => update(value, true),
      interrupt(message = "Response interrupted") {
        const anchored = nearBottom();
        indicator.remove();
        if (!finished) root.appendChild(el("div", "apollo-stream-interrupted", message));
        finished = true;
        settleScroll(anchored);
        return root;
      },
      root
    };
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
    if (block.type === "selector") return [
      block.title,
      ...block.options.map(option => [
        option.label,
        option.description,
        ...option.details.map(detail => `${detail.label}: ${detail.value}`)
      ].filter(Boolean).join(" — "))
    ].filter(Boolean).join("\n");
    if (block.type === "function_explorer") return [
      block.title,
      `f(x) = (x² - ${block.target ** 2}) / (x - ${block.target})`,
      `Target: x → ${block.target}; limit: ${2 * block.target}`
    ].filter(Boolean).join("\n");
    if (block.type === "metric_trend") return [
      block.title, block.subtitle,
      ...block.items.map(item => `${item.label}: ${numberLabel(item.value, block.unit)}${item.description ? ` — ${item.description}` : ""}`)
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
    const wrapped = function(role, content, attachments, autoScroll, existingMessage) {
      const text = original.call(this, role, content, attachments, autoScroll, existingMessage);
      if (role !== "assistant") return text;
      const rich = render(content);
      const body = text.closest(".apollo-message-body");
      if (body) text.replaceWith(rich);
      return rich;
    };
    wrapped.apolloGenUIInstalled = true;
    window.apolloAddMessage = wrapped;
    window.apolloGenUIStreamingText = value => completeStreamSegments(value, false).segments.join("\n\n");
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install, {once: true});
    else install();
  }
  const api = {parse, validate, render, copyText, install, keyFor, completeStreamSegments, hasIncompleteInline, createStreamRenderer, evaluateExpression};
  if (typeof window !== "undefined") window.ApolloGenUI = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
