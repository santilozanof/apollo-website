/* =========================================================
   APOLLO OS V1
   A new product shell built around now, conversation and time.
   Existing feature implementations remain the system of record.
   ========================================================= */

(() => {
    "use strict";

    if (window.apolloOSV1Installed) return;
    window.apolloOSV1Installed = true;

    const doc = document;
    const root = doc.documentElement;
    const app = doc.querySelector(".app");
    const main = doc.querySelector(".main");
    const oldSidebar = doc.querySelector(".sidebar");
    const home = doc.querySelector(".home");

    if (!app || !main || !home) return;

    root.classList.add("apollo-os-v1");
    oldSidebar?.setAttribute("aria-hidden", "true");

    const icon = name => ({
        mark: '<svg viewBox="0 0 28 28" aria-hidden="true"><path d="M5.4 22.2 13.2 5.6l9.4 16.6M7.2 18.2c4.3-3.5 9.6-4 15.4-1.2"/></svg>',
        now: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12a7 7 0 1 0 14 0 7 7 0 1 0-14 0"/><path d="M12 8v4l2.8 1.8"/></svg>',
        chat: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5.5h14v10.2H9.2L5 19z"/></svg>',
        tasks: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7.2h2.5M10 7.2h9M5 12h2.5M10 12h9M5 16.8h2.5M10 16.8h9"/></svg>',
        time: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6.8h14v12H5zM8 4v4M16 4v4M5 10h14"/></svg>',
        studio: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h2M9 8v8M13 5v14M17 9v6M21 11v2"/></svg>',
        health: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 12h3l1.8-4.2 3.1 8.4 2.2-5.1 1.2 2.4h5.7"/></svg>',
        brief: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4.5h12v15H6zM9 8h6M9 12h6M9 16h4"/></svg>',
        music: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 18V6l8-1.6v11.8M7.5 18a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0ZM18 16.2a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z"/></svg>',
        settings: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 3.5v2M12 18.5v2M3.5 12h2M18.5 12h2M6 6l1.4 1.4M16.6 16.6 18 18M18 6l-1.4 1.4M7.4 16.6 6 18"/></svg>',
        more: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="18" cy="12" r="1"/></svg>',
        arrow: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h13M14 7l5 5-5 5"/></svg>',
        plus: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
        spark: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5c.5 4.7 3.1 7.4 7.5 8.5-4.4 1.1-7 3.8-7.5 8.5-.5-4.7-3.1-7.4-7.5-8.5 4.4-1.1 7-3.8 7.5-8.5Z"/></svg>',
        chevron: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 10 4 4 4-4"/></svg>',
        close: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>'
    }[name] || "");

    const routeMeta = {
        now: ["Now", "What matters"],
        chat: ["Apollo", "Conversation"],
        tasks: ["Tasks", "Commitments"],
        time: ["Time", "Agenda"],
        calendar: ["Week", "Calendar"],
        studio: ["Studio", "Creative work"],
        health: ["Health", "Body context"],
        brief: ["Briefing", "Daily debrief"],
        music: ["Music", "Listening"],
        settings: ["Settings", "Preferences"]
    };

    const navItem = (route, label, iconName, extra = "") => `
        <button class="os-dock-button ${extra}" type="button" data-os-route="${route}" aria-label="${label}">
            <span class="os-dock-icon">${icon(iconName)}</span>
            <span class="os-dock-label">${label}</span>
        </button>`;

    const chrome = doc.createElement("div");
    chrome.className = "os-chrome";
    chrome.innerHTML = `
        <header class="os-topbar">
            <button class="os-wordmark" type="button" data-os-route="now" aria-label="Open Now">
                <span class="os-wordmark-mark">${icon("mark")}</span>
                <span class="os-wordmark-name">Apollo</span>
            </button>
            <div class="os-location" aria-live="polite">
                <span class="os-location-name" id="osLocationName">Now</span>
                <span class="os-location-rule"></span>
                <span class="os-location-context" id="osLocationContext">What matters</span>
            </div>
            <div class="os-topbar-end">
                <span class="os-preview-state" id="osPreviewState" hidden>Preview · read only</span>
                <time class="os-clock" id="osClock"></time>
                <button class="os-top-settings" type="button" data-os-route="settings" aria-label="Settings">${icon("settings")}</button>
            </div>
        </header>
        <nav class="os-dock" aria-label="Apollo spaces">
            ${navItem("now", "Now", "now")}
            ${navItem("chat", "Apollo", "chat")}
            ${navItem("tasks", "Tasks", "tasks")}
            ${navItem("time", "Time", "time")}
            ${navItem("studio", "Studio", "studio")}
            <span class="os-dock-divider" aria-hidden="true"></span>
            ${navItem("health", "Health", "health", "os-aux-route")}
            ${navItem("brief", "Briefing", "brief", "os-aux-route")}
            ${navItem("music", "Music", "music", "os-aux-route")}
            ${navItem("settings", "Settings", "settings", "os-aux-route")}
            <button class="os-dock-button os-more-button" type="button" data-os-more aria-label="More spaces">
                <span class="os-dock-icon">${icon("more")}</span>
                <span class="os-dock-label">More</span>
            </button>
        </nav>
        <div class="os-more-backdrop" id="osMoreBackdrop" hidden></div>
        <section class="os-more-sheet" id="osMoreSheet" aria-label="More Apollo spaces" aria-hidden="true">
            <div class="os-sheet-handle" aria-hidden="true"></div>
            <div class="os-sheet-head">
                <div><span>Spaces</span><strong>Everything else, close by.</strong></div>
                <button type="button" data-os-close-more aria-label="Close">${icon("close")}</button>
            </div>
            <div class="os-sheet-grid">
                ${navItem("health", "Health", "health")}
                ${navItem("brief", "Briefing", "brief")}
                ${navItem("music", "Music", "music")}
                ${navItem("settings", "Settings", "settings")}
            </div>
        </section>
        <div class="os-toast" id="osToast" role="status" aria-live="polite"></div>
    `;
    app.prepend(chrome);

    const customViews = {};
    [
        ["time", "apolloOSTime"],
        ["health", "apolloOSHealth"],
        ["brief", "apolloOSBrief"]
    ].forEach(([name, id]) => {
        const view = doc.createElement("section");
        view.id = id;
        view.className = `os-custom-view os-${name}-view`;
        view.setAttribute("aria-labelledby", `${id}Title`);
        main.appendChild(view);
        customViews[name] = view;
    });

    home.innerHTML = `
        <div class="os-home-shell">
            <header class="os-home-intro">
                <div class="os-date-line" id="osDateLine"></div>
                <h1 id="osGreeting">Good day.</h1>
                <p id="osHomeLead">Apollo is gathering what matters now.</p>
            </header>

            <form class="os-command" id="osCommand">
                <span class="os-command-mark">${icon("spark")}</span>
                <label class="os-sr-only" for="osCommandInput">Ask Apollo</label>
                <textarea id="osCommandInput" rows="1" maxlength="12000" placeholder="Ask Apollo anything…"></textarea>
                <button type="submit" aria-label="Send to Apollo">${icon("arrow")}</button>
            </form>

            <div class="os-home-grid">
                <section class="os-focus" aria-labelledby="osFocusLabel">
                    <div class="os-section-line">
                        <span id="osFocusLabel">Right now</span>
                        <span class="os-focus-index">01</span>
                    </div>
                    <div class="os-focus-body">
                        <div class="os-focus-kicker" id="osFocusKicker">Preparing your day</div>
                        <h2 id="osFocusTitle">One moment.</h2>
                        <p id="osFocusDetail">Calendar, tasks, health, and your latest briefing are being read securely.</p>
                    </div>
                    <div class="os-focus-actions" id="osFocusActions"></div>
                </section>

                <section class="os-up-next" aria-labelledby="osUpNextTitle">
                    <div class="os-section-line">
                        <span id="osUpNextTitle">Up next</span>
                        <button type="button" data-os-route="time">Open agenda ${icon("arrow")}</button>
                    </div>
                    <div class="os-agenda-list" id="osAgendaList">
                        <div class="os-skeleton-row"></div><div class="os-skeleton-row"></div><div class="os-skeleton-row short"></div>
                    </div>
                </section>
            </div>

            <section class="os-signal-field" aria-labelledby="osSignalTitle">
                <div class="os-section-line">
                    <span id="osSignalTitle">In your orbit</span>
                    <span>Live context</span>
                </div>
                <div class="os-signal-list" id="osSignalList">
                    <div class="os-skeleton-signal"></div><div class="os-skeleton-signal"></div><div class="os-skeleton-signal"></div>
                </div>
            </section>
        </div>`;

    const legacy = {
        home: window.openHome,
        chat: window.openApollo,
        tasks: window.openTasks,
        calendar: window.openCalendar,
        studio: window.openStudio,
        music: window.openMusic,
        settings: window.openSettings
    };

    const builtInViews = () => [
        doc.getElementById("apolloView"),
        doc.getElementById("calendarView"),
        doc.getElementById("tasksView"),
        doc.getElementById("studioView"),
        doc.getElementById("musicView"),
        doc.getElementById("settingsView")
    ].filter(Boolean);

    let currentRoute = "now";
    let previewReadOnly = false;
    let dataCache = null;
    let dataLoading = null;
    let toastTimer = 0;

    function hideAllViews() {
        home.classList.add("hidden");
        builtInViews().forEach(view => view.classList.remove("active"));
        Object.values(customViews).forEach(view => view.classList.remove("active"));
    }

    function syncRoute(route, updateHash = true) {
        currentRoute = route;
        doc.body.dataset.osRoute = route;
        const [name, context] = routeMeta[route] || routeMeta.now;
        doc.getElementById("osLocationName").textContent = name;
        doc.getElementById("osLocationContext").textContent = context;
        doc.querySelectorAll("[data-os-route]").forEach(button => {
            const active = button.dataset.osRoute === route || (route === "calendar" && button.dataset.osRoute === "time");
            button.classList.toggle("is-active", active);
            if (button.classList.contains("os-dock-button")) button.setAttribute("aria-current", active ? "page" : "false");
        });
        closeMore();
        if (updateHash) history.replaceState(null, "", `${location.pathname}${location.search}#${route}`);
    }

    function openRoute(route, options = {}) {
        hideAllViews();

        if (route === "now") {
            if (typeof legacy.home === "function") legacy.home();
            home.classList.remove("hidden");
            loadAllData(Boolean(options.refresh));
        } else if (route === "time" || route === "health" || route === "brief") {
            customViews[route].classList.add("active");
            loadAllData(Boolean(options.refresh)).then(() => renderCustom(route));
        } else if (route === "calendar") {
            if (typeof legacy.calendar === "function") legacy.calendar();
        } else if (typeof legacy[route] === "function") {
            legacy[route]();
            if (route === "tasks" && typeof window.apolloLoadTasks === "function") window.apolloLoadTasks();
        }

        syncRoute(route);
        requestAnimationFrame(() => main.scrollTo?.({top: 0, behavior: "instant"}));
    }

    const routeForLegacy = {openHome: "now", openApollo: "chat", openTasks: "tasks", openCalendar: "calendar", openStudio: "studio", openMusic: "music", openSettings: "settings"};
    Object.entries(routeForLegacy).forEach(([name, route]) => {
        const original = window[name];
        if (typeof original !== "function") return;
        window[name] = function(...args) {
            hideAllViews();
            const result = original.apply(this, args);
            syncRoute(route);
            if (route === "now") loadAllData();
            return result;
        };
    });

    function showToast(message) {
        const toast = doc.getElementById("osToast");
        toast.textContent = message;
        toast.classList.add("is-visible");
        clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 2800);
    }

    function openMore() {
        const sheet = doc.getElementById("osMoreSheet");
        const backdrop = doc.getElementById("osMoreBackdrop");
        backdrop.hidden = false;
        sheet.setAttribute("aria-hidden", "false");
        requestAnimationFrame(() => doc.body.classList.add("os-more-open"));
    }

    function closeMore() {
        const sheet = doc.getElementById("osMoreSheet");
        const backdrop = doc.getElementById("osMoreBackdrop");
        doc.body.classList.remove("os-more-open");
        sheet?.setAttribute("aria-hidden", "true");
        window.setTimeout(() => { if (!doc.body.classList.contains("os-more-open") && backdrop) backdrop.hidden = true; }, 220);
    }

    doc.addEventListener("click", event => {
        const routeButton = event.target.closest("[data-os-route]");
        if (routeButton) {
            event.preventDefault();
            openRoute(routeButton.dataset.osRoute);
            return;
        }
        if (event.target.closest("[data-os-more]")) openMore();
        if (event.target.closest("[data-os-close-more]") || event.target.id === "osMoreBackdrop") closeMore();
        if (event.target.closest("[data-os-week]")) openRoute("calendar");
        if (event.target.closest("[data-os-add-event]")) {
            openRoute("calendar");
            window.setTimeout(() => doc.getElementById("apolloWeekAdd")?.click(), 180);
        }
        const ask = event.target.closest("[data-os-ask]");
        if (ask) sendToApollo(ask.dataset.osAsk || "Help me think through today.", false);
        const retry = event.target.closest("[data-os-retry]");
        if (retry) loadAllData(true);
    });

    doc.addEventListener("keydown", event => {
        if (event.key === "Escape") closeMore();
        if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
            event.preventDefault();
            if (currentRoute !== "now") openRoute("now");
            window.setTimeout(() => doc.getElementById("osCommandInput")?.focus(), 80);
        }
    });

    const command = doc.getElementById("osCommand");
    const commandInput = doc.getElementById("osCommandInput");
    command.addEventListener("submit", event => {
        event.preventDefault();
        const value = commandInput.value.trim();
        if (!value) return commandInput.focus();
        sendToApollo(value, true);
    });
    commandInput.addEventListener("input", () => {
        commandInput.style.height = "auto";
        commandInput.style.height = `${Math.min(commandInput.scrollHeight, 132)}px`;
    });
    commandInput.addEventListener("keydown", event => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            command.requestSubmit();
        }
    });

    function sendToApollo(text, send) {
        if (previewReadOnly && send) return showToast("This preview is read only. Your message was not sent.");
        openRoute("chat");
        window.setTimeout(() => {
            const input = doc.getElementById("apolloInput");
            if (!input) return;
            input.value = text;
            input.dispatchEvent(new Event("input", {bubbles: true}));
            input.focus();
            if (send && typeof window.apolloSendMessage === "function") window.apolloSendMessage();
        }, 80);
    }

    function updateTime() {
        const now = new Date();
        doc.getElementById("osClock").textContent = new Intl.DateTimeFormat(undefined, {hour: "numeric", minute: "2-digit"}).format(now);
        doc.getElementById("osDateLine").textContent = new Intl.DateTimeFormat(undefined, {weekday: "long", month: "long", day: "numeric"}).format(now);
        const hour = now.getHours();
        doc.getElementById("osGreeting").textContent = hour < 12 ? "Good morning." : hour < 18 ? "Good afternoon." : "Good evening.";
    }
    updateTime();
    window.setInterval(updateTime, 30000);

    const readJSON = async (path, attempts = 2) => {
        try {
            const response = await fetch(path, {cache: "no-store", headers: {Accept: "application/json"}});
            let body = {};
            try { body = await response.json(); } catch (_) {}
            if (!response.ok) throw new Error(body.error || "Unavailable");
            return body;
        } catch (error) {
            if (attempts <= 1) throw error;
            await new Promise(resolve => window.setTimeout(resolve, 320));
            return readJSON(path, attempts - 1);
        }
    };

    function whoopInsightText(value) {
        const text = String(value || "").trim();
        if (!text) return "";
        const lower = text.toLowerCase();
        const blockedMarkers = [
            "api call failed",
            "http 429",
            "usage limit",
            "rate limit",
            "too many requests",
            "request failed",
            "service unavailable",
            "not authenticated"
        ];
        return blockedMarkers.some(marker => lower.includes(marker)) ? "" : text;
    }

    async function loadAllData(force = false) {
        if (dataCache && !force) {
            renderHome(dataCache);
            return dataCache;
        }
        if (dataLoading && !force) return dataLoading;

        home.classList.add("is-loading");
        const requests = {
            tasks: "/api/tasks",
            calendar: "/api/calendar/events?days=7",
            health: "/api/whoop/summary",
            briefing: `/api/debrief?time_zone=${encodeURIComponent(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC")}`,
            studio: "/api/studio/projects",
            chats: "/api/chats",
            music: "/api/now-playing"
        };
        dataLoading = Promise.allSettled(Object.entries(requests).map(async ([key, path]) => [key, await readJSON(path)]))
            .then(results => {
                const next = {_errors: []};
                results.forEach((result, index) => {
                    if (result.status === "fulfilled") next[result.value[0]] = result.value[1];
                    else {
                        const key = Object.keys(requests)[index];
                        if (key && dataCache?.[key]) next[key] = dataCache[key];
                        next._errors.push(result.reason?.message || "Unavailable");
                    }
                });
                dataCache = next;
                renderHome(next);
                if (currentRoute === "time" || currentRoute === "health" || currentRoute === "brief") renderCustom(currentRoute);
                return next;
            })
            .finally(() => {
                dataLoading = null;
                home.classList.remove("is-loading");
            });
        return dataLoading;
    }

    function parseLocalDate(value) {
        if (!value) return null;
        if (value instanceof Date) return value;
        const raw = String(value);
        const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})(?:T|\s)(\d{2}):(\d{2})(?::(\d{2}))?/);
        if (match) return new Date(+match[1], +match[2] - 1, +match[3], +match[4], +match[5], +(match[6] || 0));
        const dateOnly = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (dateOnly) return new Date(+dateOnly[1], +dateOnly[2] - 1, +dateOnly[3]);
        const parsed = new Date(raw);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    }

    function eventDate(event) {
        return parseLocalDate(event?.start?.dateTime || event?.start?.date);
    }

    function taskDate(task) { return parseLocalDate(task?.due_at); }
    function dayKey(date) { return date ? `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}` : ""; }
    function sameDay(a, b) { return dayKey(a) === dayKey(b); }
    function timeLabel(date, allDay = false) { return allDay ? "All day" : date ? new Intl.DateTimeFormat(undefined, {hour: "numeric", minute: "2-digit"}).format(date) : "Anytime"; }
    function dateLabel(date) {
        if (!date) return "Anytime";
        const today = new Date();
        const tomorrow = new Date(today); tomorrow.setDate(today.getDate() + 1);
        if (sameDay(date, today)) return "Today";
        if (sameDay(date, tomorrow)) return "Tomorrow";
        return new Intl.DateTimeFormat(undefined, {weekday: "short", month: "short", day: "numeric"}).format(date);
    }
    function relativeTime(date) {
        if (!date) return "";
        const delta = date - new Date();
        const minutes = Math.round(delta / 60000);
        if (Math.abs(minutes) < 60) return minutes >= 0 ? `in ${Math.max(1, minutes)} min` : `${Math.abs(minutes)} min ago`;
        const hours = Math.round(delta / 3600000);
        if (Math.abs(hours) < 24) return hours >= 0 ? `in ${hours} hr` : `${Math.abs(hours)} hr ago`;
        return dateLabel(date);
    }

    function briefingContent(raw) {
        const debrief = raw?.debrief;
        if (!debrief) return null;
        let content = debrief.content;
        if (typeof content === "string") {
            try { content = JSON.parse(content); } catch (_) { content = {summary: content, items: []}; }
        }
        return {...debrief, parsed: content || {}};
    }

    function normalizedData(data) {
        const now = new Date();
        const tasks = Array.isArray(data?.tasks?.tasks) ? data.tasks.tasks : [];
        const activeTasks = tasks.filter(task => !task.completed);
        const events = (Array.isArray(data?.calendar?.events) ? data.calendar.events : [])
            .map(event => ({...event, _date: eventDate(event)}))
            .filter(event => event._date)
            .sort((a, b) => a._date - b._date);
        const upcomingEvents = events.filter(event => event._date >= new Date(now.getTime() - 3600000));
        const datedTasks = activeTasks.map(task => ({...task, _date: taskDate(task)})).sort((a, b) => (a._date || Infinity) - (b._date || Infinity));
        const overdue = datedTasks.filter(task => task._date && task._date < now && !sameDay(task._date, now));
        const todayTasks = datedTasks.filter(task => !task._date || sameDay(task._date, now));
        const projects = Array.isArray(data?.studio?.projects) ? data.studio.projects : [];
        const brief = briefingContent(data?.briefing);
        return {now, tasks, activeTasks, events, upcomingEvents, datedTasks, overdue, todayTasks, projects, brief, health: data?.health || null, music: data?.music || null};
    }

    function actionButton(label, route, primary = false) {
        return `<button class="os-text-action${primary ? " is-primary" : ""}" type="button" data-os-route="${route}">${label}${icon("arrow")}</button>`;
    }

    function renderHome(data) {
        const n = normalizedData(data);
        const lead = doc.getElementById("osHomeLead");
        const kicker = doc.getElementById("osFocusKicker");
        const title = doc.getElementById("osFocusTitle");
        const detail = doc.getElementById("osFocusDetail");
        const actions = doc.getElementById("osFocusActions");
        const agenda = doc.getElementById("osAgendaList");
        const signals = doc.getElementById("osSignalList");

        const nextEvent = n.upcomingEvents[0];
        const priorityTask = n.overdue[0] || n.todayTasks[0];
        const briefSummary = n.brief?.parsed?.summary;

        lead.textContent = data._errors?.length >= 3 ? "Some parts of your day are unavailable, but the useful context is here." : "Here’s what deserves your attention.";

        if (nextEvent && nextEvent._date - n.now < 6 * 3600000) {
            kicker.textContent = `${dateLabel(nextEvent._date)} · ${timeLabel(nextEvent._date, Boolean(nextEvent.start?.date))}`;
            title.textContent = nextEvent.summary || "Your next commitment";
            detail.textContent = [nextEvent.location, relativeTime(nextEvent._date)].filter(Boolean).join(" · ") || "Coming up on your calendar.";
            actions.innerHTML = actionButton("See your time", "time", true) + `<button class="os-text-action" type="button" data-os-ask="Help me prepare for ${escapeAttr(nextEvent.summary || "my next event")}">Prepare with Apollo${icon("arrow")}</button>`;
        } else if (priorityTask) {
            kicker.textContent = n.overdue.includes(priorityTask) ? "Needs attention" : "One thing to move";
            title.textContent = priorityTask.title || "An open task";
            detail.textContent = priorityTask._date ? `${dateLabel(priorityTask._date)} · ${timeLabel(priorityTask._date)}` : `${n.activeTasks.length} open ${n.activeTasks.length === 1 ? "task" : "tasks"}`;
            actions.innerHTML = actionButton("Open tasks", "tasks", true) + `<button class="os-text-action" type="button" data-os-ask="Help me make a plan for this task: ${escapeAttr(priorityTask.title || "")}">Make a plan${icon("arrow")}</button>`;
        } else if (briefSummary) {
            kicker.textContent = "Today’s signal";
            title.textContent = briefSummary;
            detail.textContent = "From your latest Daily Briefing.";
            actions.innerHTML = actionButton("Read briefing", "brief", true);
        } else {
            kicker.textContent = "Clear space";
            title.textContent = "Nothing urgent is asking for you.";
            detail.textContent = "Use the quiet, or ask Apollo where to begin.";
            actions.innerHTML = `<button class="os-text-action is-primary" type="button" data-os-ask="What would be the best use of the next hour?">Ask Apollo${icon("arrow")}</button>`;
        }

        const timeline = [
            ...n.upcomingEvents.slice(0, 4).map(event => ({type: "Event", title: event.summary || "Untitled event", date: event._date, allDay: Boolean(event.start?.date)})),
            ...n.datedTasks.filter(task => task._date && task._date >= new Date(n.now.getTime() - 86400000)).slice(0, 4).map(task => ({type: "Task", title: task.title || "Untitled task", date: task._date}))
        ].sort((a, b) => a.date - b.date).slice(0, 4);

        agenda.innerHTML = timeline.length ? timeline.map(item => `
            <button class="os-agenda-row" type="button" data-os-route="${item.type === "Task" ? "tasks" : "time"}">
                <span class="os-agenda-when"><strong>${dateLabel(item.date)}</strong><small>${timeLabel(item.date, item.allDay)}</small></span>
                <span class="os-agenda-copy"><b>${escapeHTML(item.title)}</b><small>${item.type}</small></span>
                ${icon("arrow")}
            </button>`).join("") : `<div class="os-empty-line"><strong>Your near horizon is clear.</strong><span>No timed commitments are coming up.</span></div>`;

        const recovery = Number(n.health?.summary?.recovery?.score);
        const recoveryText = Number.isFinite(recovery) ? `${Math.round(recovery)}% recovery` : "Health context unavailable";
        const latestProject = n.projects.slice().sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")))[0];
        const briefItems = Array.isArray(n.brief?.parsed?.items) ? n.brief.parsed.items : [];
        const musicTitle = n.music?.title || n.music?.item?.name;

        const signalRows = [
            {route: "health", index: "01", label: "Body", title: recoveryText, note: whoopInsightText(n.health?.interpretation) || "See the context behind today’s numbers."},
            {route: "tasks", index: "02", label: "Commitments", title: `${n.activeTasks.length} open ${n.activeTasks.length === 1 ? "task" : "tasks"}`, note: n.overdue.length ? `${n.overdue.length} past due` : "Nothing overdue"},
            {route: "studio", index: "03", label: "Studio", title: latestProject?.title || "Your creative work", note: latestProject ? `${n.projects.length} active ${n.projects.length === 1 ? "project" : "projects"}` : "No projects yet"},
            {route: "brief", index: "04", label: "Briefing", title: briefItems[0]?.headline || (n.brief ? "Your Daily Briefing is ready" : "No briefing yet"), note: n.brief ? `${briefItems.length} signals today` : "Apollo will surface one when ready"},
            {route: "music", index: "05", label: "Listening", title: musicTitle || "Nothing playing", note: musicTitle ? (n.music?.artists || "Spotify") : "Your music stays close"}
        ];
        signals.innerHTML = signalRows.map(item => `
            <button class="os-signal-row" type="button" data-os-route="${item.route}">
                <span class="os-signal-index">${item.index}</span>
                <span class="os-signal-label">${item.label}</span>
                <span class="os-signal-copy"><strong>${escapeHTML(item.title)}</strong><small>${escapeHTML(item.note)}</small></span>
                ${icon("arrow")}
            </button>`).join("");

        if (data._errors?.length && !n.tasks.length && !n.events.length && !n.health && !n.brief) {
            actions.innerHTML += `<button class="os-text-action" type="button" data-os-retry>Try again${icon("arrow")}</button>`;
        }
    }

    function renderCustom(route) {
        if (!dataCache) return;
        if (route === "time") renderTime(normalizedData(dataCache));
        if (route === "health") renderHealth(normalizedData(dataCache));
        if (route === "brief") renderBrief(normalizedData(dataCache));
    }

    function pageHeader(eyebrow, title, subtitle, actions = "") {
        return `<header class="os-page-header"><div><div class="os-page-eyebrow">${eyebrow}</div><h1>${title}</h1><p>${subtitle}</p></div><div class="os-page-actions">${actions}</div></header>`;
    }

    function renderTime(n) {
        const view = customViews.time;
        const entries = [
            ...n.events.map(event => ({type: "event", title: event.summary || "Untitled event", date: event._date, end: parseLocalDate(event?.end?.dateTime || event?.end?.date), allDay: Boolean(event.start?.date), meta: event.location || "Calendar"})),
            ...n.datedTasks.filter(task => task._date).map(task => ({type: "task", title: task.title || "Untitled task", date: task._date, meta: task.completed ? "Completed" : "Task"}))
        ].sort((a, b) => a.date - b.date);
        const grouped = new Map();
        entries.forEach(entry => {
            const key = dayKey(entry.date);
            if (!grouped.has(key)) grouped.set(key, []);
            grouped.get(key).push(entry);
        });
        const days = [...grouped.values()];
        view.innerHTML = `<div class="os-page-shell">
            ${pageHeader("Your time", "The next seven days.", "Commitments in sequence, with the full week one step away.", `<button class="os-control" type="button" data-os-week>Week view</button><button class="os-control is-dark" type="button" data-os-add-event>${icon("plus")} Add event</button>`)}
            <div class="os-time-layout">
                <aside class="os-time-now"><span>Now</span><strong>${new Intl.DateTimeFormat(undefined, {hour: "numeric", minute: "2-digit"}).format(n.now)}</strong><p>${n.upcomingEvents[0] ? `${relativeTime(n.upcomingEvents[0]._date)} until your next event.` : "Your calendar has room."}</p></aside>
                <div class="os-timeline">${days.length ? days.map(day => `
                    <section class="os-day-group">
                        <header><span>${dateLabel(day[0].date)}</span><time>${new Intl.DateTimeFormat(undefined, {month: "short", day: "numeric"}).format(day[0].date)}</time></header>
                        <div>${day.map(entry => `<button class="os-time-row" type="button" data-os-route="${entry.type === "task" ? "tasks" : "calendar"}">
                            <span class="os-time-hour">${timeLabel(entry.date, entry.allDay)}</span>
                            <span class="os-time-marker ${entry.type}"></span>
                            <span class="os-time-copy"><strong>${escapeHTML(entry.title)}</strong><small>${escapeHTML(entry.meta)}${entry.end && !entry.allDay ? ` · until ${timeLabel(entry.end)}` : ""}</small></span>
                            ${icon("arrow")}
                        </button>`).join("")}</div>
                    </section>`).join("") : `<div class="os-large-empty"><span>Nothing scheduled.</span><strong>Your next seven days are open.</strong><button class="os-control is-dark" type="button" data-os-add-event>Add an event</button></div>`}</div>
            </div>
        </div>`;
    }

    function renderHealth(n) {
        const health = n.health;
        const summary = health?.summary || {};
        const recovery = summary.recovery || {};
        const sleep = summary.sleep || {};
        const cycle = summary.cycle || {};
        const score = Number(recovery.score);
        const state = Number.isFinite(score) ? (score >= 67 ? "ready" : score >= 34 ? "steady" : "rest") : "unknown";
        const metrics = [
            ["Recovery", Number.isFinite(score) ? `${Math.round(score)}%` : "—", state === "ready" ? "Room to push" : state === "steady" ? "Use your energy deliberately" : state === "rest" ? "Protect recovery" : "Awaiting data"],
            ["Sleep", Number.isFinite(Number(sleep.performance_percentage)) ? `${Math.round(Number(sleep.performance_percentage))}%` : "—", Number.isFinite(Number(sleep.total_sleep_hours)) ? `${Number(sleep.total_sleep_hours).toFixed(1)} hours` : "No sleep total"],
            ["Strain", Number.isFinite(Number(cycle.strain)) ? Number(cycle.strain).toFixed(1) : "—", "Today’s accumulated load"]
        ];
        customViews.health.innerHTML = `<div class="os-page-shell os-health-shell" data-recovery-state="${state}">
            ${pageHeader("Body context", "Health, in plain language.", "Numbers only matter when they change what you do.", `<button class="os-control is-dark" type="button" data-os-ask="Interpret my WHOOP data and help me decide how hard to push today.">Talk this through</button>`)}
            <section class="os-health-hero">
                <div class="os-health-score"><span>Recovery</span><strong>${Number.isFinite(score) ? Math.round(score) : "—"}<small>${Number.isFinite(score) ? "%" : ""}</small></strong><i></i></div>
                <div class="os-health-meaning"><span>What it means</span><h2>${escapeHTML(whoopInsightText(health?.interpretation) || "Apollo is waiting for enough health data to give you useful context.")}</h2><p>${health?.status === "ready" ? "Updated from your latest WHOOP cycle." : "Your current status may still be processing."}</p></div>
            </section>
            <section class="os-metric-strip">${metrics.map(([label, value, note], index) => `<div><span>0${index + 1} · ${label}</span><strong>${value}</strong><p>${note}</p></div>`).join("")}</section>
            <section class="os-health-detail"><div><span>Quiet signals</span><p>Useful supporting numbers, kept in proportion.</p></div><dl>
                <div><dt>HRV</dt><dd>${Number.isFinite(Number(recovery.hrv_ms)) ? `${Math.round(Number(recovery.hrv_ms))} ms` : "—"}</dd></div>
                <div><dt>Resting heart rate</dt><dd>${Number.isFinite(Number(recovery.resting_heart_rate)) ? `${Math.round(Number(recovery.resting_heart_rate))} bpm` : "—"}</dd></div>
                <div><dt>Total sleep</dt><dd>${Number.isFinite(Number(sleep.total_sleep_hours)) ? `${Number(sleep.total_sleep_hours).toFixed(1)} hr` : "—"}</dd></div>
            </dl></section>
        </div>`;
    }

    function renderBrief(n) {
        const brief = n.brief;
        const parsed = brief?.parsed || {};
        const items = Array.isArray(parsed.items) ? parsed.items : [];
        const generated = parseLocalDate(brief?.generated_at);
        customViews.brief.innerHTML = `<div class="os-page-shell os-brief-shell">
            ${pageHeader("Daily Briefing", "A quieter view of today.", generated ? `Prepared ${dateLabel(generated)} at ${timeLabel(generated)}.` : "Apollo will prepare a briefing when enough context is available.", `<button class="os-control is-dark" type="button" data-os-ask="Give me the most useful takeaway from today’s Daily Briefing.">Discuss with Apollo</button>`)}
            ${brief ? `<article class="os-brief-lead"><span>In brief</span><h2>${escapeHTML(parsed.summary || "Your briefing is ready.")}</h2></article>
            ${parsed.weather ? `<aside class="os-weather-note"><span>Outside</span><strong>${escapeHTML(parsed.weather.headline || "Weather")}</strong><p>${escapeHTML(parsed.weather.body || "")}</p></aside>` : ""}
            <section class="os-brief-items"><div class="os-section-line"><span>Signals</span><span>${items.length} items</span></div>${items.length ? items.map((item, index) => `<details class="os-brief-item" ${index === 0 ? "open" : ""}>
                <summary><span>${String(index + 1).padStart(2, "0")}</span><small>${escapeHTML(item.category || "Worth knowing")}</small><strong>${escapeHTML(item.headline || "Untitled signal")}</strong>${icon("chevron")}</summary>
                <div><p>${escapeHTML(item.body || "")}</p>${item.source ? `<cite>${escapeHTML(item.source)}</cite>` : ""}</div>
            </details>`).join("") : `<div class="os-large-empty"><span>No signals yet.</span><strong>There’s nothing to debrief today.</strong></div>`}</section>` : `<div class="os-large-empty"><span>Not ready yet.</span><strong>Your next briefing will appear here.</strong><button class="os-control" type="button" data-os-retry>Check again</button></div>`}
        </div>`;
    }

    function escapeHTML(value) {
        return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
    }
    function escapeAttr(value) { return escapeHTML(value).replaceAll("`", "&#096;"); }

    async function detectPreview() {
        try {
            const response = await fetch("/__preview_meta__", {cache: "no-store"});
            if (!response.ok) return;
            const meta = await response.json();
            previewReadOnly = Boolean(meta.mutations_blocked);
            if (!previewReadOnly) return;
            doc.body.classList.add("os-read-only");
            const badge = doc.getElementById("osPreviewState");
            badge.hidden = false;
            badge.title = `Development preview · ${meta.branch || "dev"}@${String(meta.commit || "").slice(0, 12)}`;
            installReadOnlyGuard();
        } catch (_) {}
    }

    function installReadOnlyGuard() {
        const writeSelector = [
            "#apolloSend", "#apolloPresenceSend", "#apolloTaskAdd button", "[data-task-action]", "#apolloTaskSave", "#apolloTaskDelete",
            "#apolloWeekAdd", "[data-new-project]", "[data-studio-action]", ".studio5-primary", ".studio5-row-more",
            "[data-music-action]", ".apollo-music-control"
        ].join(",");
        doc.addEventListener("click", event => {
            const target = event.target.closest(writeSelector);
            if (!target || !previewReadOnly) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            showToast("Read-only preview. No personal data was changed.");
        }, true);
        doc.addEventListener("submit", event => {
            if (!previewReadOnly || !event.target.matches("#apolloTaskAdd")) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            showToast("Read-only preview. No personal data was changed.");
        }, true);
    }

    detectPreview();

    const initialHash = location.hash.replace("#", "");
    const initialRoute = routeMeta[initialHash] ? initialHash : "now";
    openRoute(initialRoute, {refresh: true});

    window.apolloOS = {open: openRoute, refresh: () => loadAllData(true), get route() { return currentRoute; }};
})();
