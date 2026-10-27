(() => {
    "use strict";

    const state = {
        data: null,
        date: null,
        history: null,
        expanded: new Set(),
        showAll: new Set(),
        openMenu: null,
        loadToken: 0,
        saveQueue: Promise.resolve(),
        modal: null
    };

    const timeZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    const today = () => new Intl.DateTimeFormat("en-CA", {
        timeZone: timeZone(), year: "numeric", month: "2-digit", day: "2-digit"
    }).format(new Date());
    const esc = value => String(value ?? "").replace(/[&<>"']/g, character => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[character]);
    const checkIcon = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4 10 4 4 8-9"/></svg>';
    const chevronIcon = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5.5 7.5 4.5 4.5 4.5-4.5"/></svg>';
    const moreIcon = '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="4" cy="10" r="1.2"/><circle cx="10" cy="10" r="1.2"/><circle cx="16" cy="10" r="1.2"/></svg>';
    state.date = today();

    const nav = document.querySelector(".nav");
    const studioButton = [...(nav?.querySelectorAll(".nav-button") || [])]
        .find(item => item.querySelector(".nav-label")?.textContent.trim() === "Studio");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "nav-button";
    button.setAttribute("aria-label", "Routines");
    button.innerHTML = `
        <span class="nav-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7"/></svg></span>
        <span class="nav-label">Routines</span>`;
    /* Keep every legacy tab at its existing index. Some older Apollo modules
       still bind Studio by position, so Routines is appended after it. */
    nav?.insertBefore(button, studioButton?.nextSibling || null);

    const view = document.createElement("section");
    view.id = "routinesView";
    view.className = "apollo-routines-view";
    view.setAttribute("aria-label", "Routines");
    view.setAttribute("aria-hidden", "true");
    view.innerHTML = `
        <div class="routine-shell">
            <header class="routine-header">
                <div><div class="apollo-page-eyebrow">APOLLO</div><h1 class="routine-title">Routines</h1><div class="routine-subtitle">Small things, consistently.</div></div>
                <button class="routine-primary" id="routineCreate" type="button"><span>New routine</span><span class="routine-primary-mobile" aria-hidden="true">+</span></button>
            </header>
            <div class="routine-toolbar" aria-label="Routine date">
                <button class="routine-chip routine-date-arrow" data-date-move="-1" type="button" aria-label="Previous day">‹</button>
                <div class="routine-date-label" id="routineDateLabel"></div>
                <button class="routine-chip routine-date-arrow" data-date-move="1" type="button" aria-label="Next day">›</button>
                <button class="routine-chip" id="routineToday" type="button">Today</button>
            </div>
            <div class="routine-layout">
                <main class="routine-list" id="routineList" aria-live="polite"><div class="routine-empty">Loading routines…</div></main>
                <aside class="routine-side" aria-label="Routine insights"><div id="routineHydration"></div><div id="routineHistory"></div></aside>
            </div>
        </div>`;
    document.querySelector(".main")?.appendChild(view);
    window.ApolloDateNav?.mountRoutines();
    document.getElementById("routineDateLabel").textContent = dateLabel(state.date);
    window.ApolloDateNav?.setToday("routines", true);

    const canonicalViews = () => [document.querySelector(".home"), ...[
        "apolloView", "musicView", "calendarView", "tasksView", "studioView", "settingsView"
    ].map(id => document.getElementById(id))].filter(Boolean);

    function closeMenu({ renderView = true } = {}) {
        if (!state.openMenu) return;
        state.openMenu = null;
        if (renderView && state.data) render();
    }

    function closeModal() {
        const modal = state.modal;
        if (!modal) return;
        state.modal = null;
        modal.cleanup?.();
        modal.backdrop.classList.remove("active");
        window.setTimeout(() => modal.backdrop.remove(), 180);
        modal.returnFocus?.focus?.();
    }

    function closeTransientUi() {
        closeMenu({ renderView: false });
        closeModal();
        document.querySelectorAll(".routine-toast").forEach(element => element.remove());
    }

    function hideRoutines() {
        view.classList.remove("active");
        view.setAttribute("aria-hidden", "true");
        closeTransientUi();
    }

    function openRoutines(options = {}) {
        canonicalViews().forEach(element => {
            element.classList.remove("active");
            element.setAttribute("aria-hidden", "true");
            if (element.classList.contains("home")) element.classList.add("hidden");
        });
        document.querySelectorAll(".nav-button").forEach(item => item.classList.remove("active"));
        button.classList.add("active");
        view.classList.add("active");
        view.setAttribute("aria-hidden", "false");
        if (options.routineId) state.expanded.add(options.routineId);
        document.body.dataset.apolloRoute = "routines";
        history.replaceState(null, "", `?tab=routines${options.routineId ? `&routine=${encodeURIComponent(options.routineId)}` : ""}`);
        load(Boolean(state.data));
    }

    window.openRoutines = openRoutines;
    window.apolloCloseRoutinesUi = closeTransientUi;
    window.apolloHideRoutines = hideRoutines;
    button.addEventListener("click", () => window.openRoutines());
    document.addEventListener("click", event => {
        if (state.openMenu && !event.target.closest?.(".routine-menu-wrap")) closeMenu();
    });
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && state.openMenu) {
            event.preventDefault();
            closeMenu();
        }
    });

    async function api(payload) {
        const response = await fetch("/api/routines/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...payload, timezone: timeZone() })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || "Could not save that change");
        return data;
    }

    async function fetchJson(url) {
        const response = await fetch(url);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || "Routines are unavailable");
        return data;
    }

    async function load(silent = false) {
        const token = ++state.loadToken;
        const list = document.getElementById("routineList");
        if (!silent) list.setAttribute("aria-busy", "true");
        try {
            const [data, historyData] = await Promise.all([
                fetchJson(`/api/routines?date=${state.date}&timezone=${encodeURIComponent(timeZone())}`),
                fetchJson(`/api/routines/history?start=${shiftDate(state.date, -27)}&end=${state.date}&timezone=${encodeURIComponent(timeZone())}`)
            ]);
            if (token !== state.loadToken) return;
            state.data = data;
            state.history = historyData;
            render();
        } catch (error) {
            if (token === state.loadToken) toast(error.message || "Routines are unavailable");
        } finally {
            if (token === state.loadToken) list.removeAttribute("aria-busy");
        }
    }

    function shiftDate(value, amount) {
        const date = new Date(`${value}T12:00:00`);
        date.setDate(date.getDate() + amount);
        return date.toISOString().slice(0, 10);
    }

    function dateLabel(value) {
        if (value === today()) return "Today";
        return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
    }

    function scheduleLabel(item) {
        const days = item.schedule_days || [];
        if (days.length === 7) return "Every day";
        if (days.length === 5 && days.every((value, index) => value === index)) return "Weekdays";
        return days.map(index => ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][index]).join(", ");
    }

    function stepScheduleLabel(step) {
        if ((step.schedule_type || "daily") === "daily") return "Daily";
        const days = step.schedule_days || [];
        const labels = days.map(index => ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][index]).join(", ");
        if (step.schedule_type === "weekdays") return labels || "No days";
        const rule = step.recurrence_rule || {};
        const interval = Number(rule.interval || 1);
        return `${interval > 1 ? `Every ${interval} weeks` : "Weekly"}${labels ? ` · ${labels}` : ""}`;
    }

    function number(value) {
        return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 1 });
    }

    function render() {
        if (!state.data) return;
        document.getElementById("routineDateLabel").textContent = dateLabel(state.date);
        window.ApolloDateNav?.setToday("routines", state.date === today());
        const routines = state.data.routines || [];
        document.getElementById("routineList").innerHTML = routines.length
            ? routines.map(renderRoutine).join("")
            : `<div class="routine-empty"><strong>Build your first routine</strong><span>Group the things you want to do, then let Apollo remember the rest.</span><button class="routine-secondary" data-empty-create type="button">Create a routine</button></div>`;
        renderHydration();
        renderHistory();
    }

    function renderRoutine(item) {
        const expanded = state.expanded.has(item.id);
        const done = item.status === "completed";
        const unscheduled = item.status === "not_scheduled";
        const timing = item.window_start ? `${item.window_start}${item.window_end ? `–${item.window_end}` : ""}` : scheduleLabel(item);
        const progress = Math.round((item.progress || 0) * 100);
        const menuOpen = state.openMenu === item.id;
        const showingAll = state.showAll.has(item.id);
        const visibleSteps = showingAll ? (item.all_steps || item.steps).map(step => {
            const live = item.steps.find(candidate => candidate.id === step.id);
            return { ...step, ...(live || { value: 0, complete: false, completed_at: null }), scheduled_for_day: Boolean(live) };
        }) : item.steps.map(step => ({ ...step, scheduled_for_day: true }));
        return `
            <article class="routine-card ${expanded ? "expanded" : ""} ${done ? "is-complete" : ""} ${unscheduled ? "is-unscheduled" : ""}" data-routine="${esc(item.id)}">
                <div class="routine-card-head">
                    <button class="routine-card-toggle ${done ? "done" : ""}" data-routine-toggle type="button" aria-label="${done ? "Mark incomplete" : "Complete"} ${esc(item.title)}" ${unscheduled ? "disabled" : ""}>${checkIcon}</button>
                    <button class="routine-card-main" data-expand type="button" aria-expanded="${expanded}"><span class="routine-card-name">${esc(item.title)}</span><span class="routine-card-meta">${unscheduled ? "Not scheduled" : done ? "Complete" : `${item.completed_steps}/${item.required_steps} · ${esc(timing)}`}</span></button>
                    <div class="routine-head-actions">
                        <button class="routine-chevron" data-expand type="button" aria-label="${expanded ? "Collapse" : "Expand"} ${esc(item.title)}">${chevronIcon}</button>
                        <div class="routine-menu-wrap"><button class="routine-menu-button" data-menu type="button" aria-label="Options for ${esc(item.title)}" aria-expanded="${menuOpen}">${moreIcon}</button>${menuOpen ? renderRoutineMenu(item) : ""}</div>
                    </div>
                </div>
                <div class="routine-progress-track" aria-hidden="true"><div class="routine-progress-fill" style="--progress:${progress}%"></div></div>
                <div class="routine-body-wrap" aria-hidden="${!expanded}"><div class="routine-body"><div class="routine-body-inner">
                    ${item.description ? `<p class="routine-description">${esc(item.description)}</p>` : ""}
                    <div class="routine-schedule-toolbar"><button class="routine-text-button" data-show-schedule type="button">${showingAll ? "Today’s checklist" : "Weekly schedule"}</button></div>
                    ${showingAll ? renderWeeklySchedule(item.all_steps || item.steps) : ""}
                    <div class="routine-steps">${visibleSteps.length ? visibleSteps.map(step => renderStep(step, unscheduled || !step.scheduled_for_day, showingAll)).join("") : '<div class="routine-no-steps">No steps scheduled for this day.</div>'}</div>
                    <button class="routine-add-step" data-add-step type="button">+ Add step</button>
                </div></div></div>
            </article>`;
    }

    function renderWeeklySchedule(steps) {
        const headers = ["M", "T", "W", "T", "F", "S", "S"];
        return `<div class="routine-week-grid" aria-label="Weekly step schedule"><div></div>${headers.map(day => `<span>${day}</span>`).join("")}${steps.map(step => {
            const days = (step.schedule_type || "daily") === "daily" ? [0, 1, 2, 3, 4, 5, 6] : (step.schedule_days || []);
            return `<strong title="${esc(step.title)}">${esc(step.title)}</strong>${headers.map((_, index) => `<i class="${days.includes(index) ? "active" : ""}" aria-label="${days.includes(index) ? "Scheduled" : "Not scheduled"}"></i>`).join("")}`;
        }).join("")}</div>`;
    }

    function renderRoutineMenu(item) {
        return `<div class="routine-options-menu" role="menu">
            <button type="button" role="menuitem" data-edit-routine>Edit routine</button><button type="button" role="menuitem" data-duplicate>Duplicate</button>
            <button type="button" role="menuitem" data-routine-move="-1">Move up</button><button type="button" role="menuitem" data-routine-move="1">Move down</button>
            <span class="routine-menu-divider" aria-hidden="true"></span><button type="button" role="menuitem" data-archive>${item.archived ? "Unarchive" : "Archive"}</button>
            <button type="button" role="menuitem" class="danger" data-delete-routine>Delete</button></div>`;
    }

    function renderStep(step, disabled, showSchedule = false) {
        const counter = step.step_type !== "checkbox" ? `<div class="routine-counter" aria-label="${esc(step.title)} value"><button data-count="-1" type="button" aria-label="Decrease ${esc(step.title)}">−</button><span>${number(step.value)}</span><button data-count="1" type="button" aria-label="Increase ${esc(step.title)}">+</button></div><span class="routine-step-target">${esc(step.unit || "")} / ${number(step.target)}</span>` : "";
        return `<div class="routine-step ${step.complete ? "done" : ""}" data-step="${esc(step.id)}">
            <button class="routine-step-check ${step.complete ? "done" : ""}" data-step-toggle type="button" ${disabled ? "disabled" : ""} aria-label="${step.complete ? "Uncheck" : "Check"} ${esc(step.title)}">${checkIcon}</button>
            <div class="routine-step-label">${esc(step.title)}${showSchedule ? `<small>${esc(stepScheduleLabel(step))}${step.alternative_group ? ` · Either ${esc(step.alternative_group)}` : ""}</small>` : ""}</div><div class="routine-step-control">${counter}<button class="routine-icon-button" data-step-move="-1" type="button" title="Move earlier" aria-label="Move ${esc(step.title)} earlier">↑</button><button class="routine-icon-button" data-step-move="1" type="button" title="Move later" aria-label="Move ${esc(step.title)} later">↓</button><button class="routine-icon-button" data-edit-step type="button" aria-label="Edit ${esc(step.title)}">${moreIcon}</button></div></div>`;
    }

    document.getElementById("routineList").addEventListener("click", async event => {
        const target = event.target;
        if (target.closest("[data-empty-create]")) { openRoutineDialog(); return; }
        const card = target.closest("[data-routine]");
        if (!card) return;
        const routine = state.data?.routines.find(item => item.id === card.dataset.routine);
        if (!routine) return;
        if (target.closest("[data-menu]")) {
            event.stopPropagation();
            state.openMenu = state.openMenu === routine.id ? null : routine.id;
            render();
            if (state.openMenu) requestAnimationFrame(() => view.querySelector(`[data-routine="${CSS.escape(routine.id)}"] .routine-options-menu button`)?.focus());
            return;
        }
        if (target.closest("[data-expand]")) {
            state.expanded.has(routine.id) ? state.expanded.delete(routine.id) : state.expanded.add(routine.id);
            render(); return;
        }
        if (target.closest("[data-show-schedule]")) {
            state.showAll.has(routine.id) ? state.showAll.delete(routine.id) : state.showAll.add(routine.id);
            render(); return;
        }
        if (target.closest("[data-routine-toggle]")) {
            await save({ action: "set_routine", routine_id: routine.id, completed: routine.status !== "completed", date: state.date, idempotency_key: crypto.randomUUID() }); return;
        }
        const stepElement = target.closest("[data-step]");
        // Always prefer the hydrated step for the selected day. `all_steps`
        // contains schedule metadata, but intentionally has no live progress.
        const step = stepElement && (
            routine.steps.find(item => item.id === stepElement.dataset.step)
            || (routine.all_steps || []).find(item => item.id === stepElement.dataset.step)
        );
        if (step && target.closest("[data-step-toggle]")) {
            event.stopPropagation();
            target.closest("[data-step-toggle]").disabled = true;
            await save({ action: "set_step", routine_id: routine.id, step_id: step.id, completed: !step.complete, date: state.date, idempotency_key: crypto.randomUUID() }); return;
        }
        const delta = Number(target.closest("[data-count]")?.dataset.count || 0);
        if (step && delta) {
            event.stopPropagation();
            target.closest("[data-count]").disabled = true;
            await save({ action: "set_step", routine_id: routine.id, step_id: step.id, value: Math.max(0, Number(step.value) + delta), date: state.date, idempotency_key: crypto.randomUUID() }); return;
        }
        const stepMove = Number(target.closest("[data-step-move]")?.dataset.stepMove || 0);
        if (step && stepMove) {
            const ordered = routine.all_steps || routine.steps;
            const other = ordered[ordered.findIndex(item => item.id === step.id) + stepMove];
            if (other) { await api({ action: "update_step", step_id: step.id, changes: { position: other.position } }); await save({ action: "update_step", step_id: other.id, changes: { position: step.position } }); }
            return;
        }
        if (step && target.closest("[data-edit-step]")) { openStepDialog(routine, step); return; }
        if (target.closest("[data-add-step]")) { openStepDialog(routine); return; }
        if (target.closest("[data-edit-routine]")) { closeMenu({ renderView: false }); openRoutineDialog(routine); return; }
        if (target.closest("[data-duplicate]")) { closeMenu({ renderView: false }); await save({ action: "duplicate_routine", routine_id: routine.id }); return; }
        const routineMove = Number(target.closest("[data-routine-move]")?.dataset.routineMove || 0);
        if (routineMove) {
            const other = state.data.routines[state.data.routines.indexOf(routine) + routineMove];
            if (other) { await api({ action: "update_routine", routine_id: routine.id, changes: { position: other.position } }); await save({ action: "update_routine", routine_id: other.id, changes: { position: routine.position } }); }
            return;
        }
        if (target.closest("[data-archive]")) {
            closeMenu({ renderView: false });
            if (await confirmAction(`Archive “${routine.title}”? Its history will be kept.`)) await save({ action: "update_routine", routine_id: routine.id, changes: { archived: true } });
            return;
        }
        if (target.closest("[data-delete-routine]")) { closeMenu({ renderView: false }); await deleteRoutine(routine); }
    });

    async function save(payload) {
        const operation = state.saveQueue.then(async () => {
            await api(payload);
            // The database response is authoritative. Reload only after the
            // committed write so a slower earlier request cannot overwrite a
            // later check/uncheck or a routine switch.
            await load(true);
        });
        state.saveQueue = operation.catch(() => {});
        try { await operation; }
        catch (error) {
            // No optimistic state was applied, so retain the last confirmed
            // snapshot and surface the real backend failure.
            toast(error.message || "Could not save that change");
        }
    }

    function renderHydration() {
        const hydration = state.data.hydration;
        const progress = Math.round(Math.min(1, hydration.progress || 0) * 100);
        document.getElementById("routineHydration").innerHTML = `<section class="hydration-card">
            <div class="routine-panel-label">Water today</div><div class="hydration-value">${number(hydration.total_ml / 1000)} L <span>/ ${number(hydration.goal_ml / 1000)} L</span></div>
            <div class="hydration-water" role="progressbar" aria-label="Hydration" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}"><div style="--progress:${progress}%"></div></div>
            <div class="hydration-quick">${[150, 250, 500, 710].map(amount => `<button data-water="${amount}" type="button">+${amount} ml</button>`).join("")}</div>
            <div class="hydration-foot"><span><button class="routine-text-button" data-water-custom type="button">Custom</button><button class="routine-text-button" data-water-goal type="button">Set goal</button></span>${hydration.entries.length ? '<button class="routine-text-button" data-water-undo type="button">Undo</button>' : ""}</div></section>`;
        window.apolloShortcutWaterTarget?.();
    }

    document.getElementById("routineHydration").addEventListener("click", async event => {
        const hydration = state.data?.hydration;
        if (!hydration) return;
        const quick = event.target.closest("[data-water]");
        if (quick) { await addWater(Number(quick.dataset.water)); return; }
        if (event.target.closest("[data-water-custom]")) {
            const amount = await promptValue("Add water (ml)", "250");
            if (amount !== null) await addWater(Number(amount));
            return;
        }
        if (event.target.closest("[data-water-goal]")) {
            const goal = await promptValue("Daily water goal (ml)", hydration.goal_ml);
            if (goal !== null) {
                const value = Number(goal);
                if (!Number.isFinite(value) || value <= 0) toast("Enter a valid goal");
                else await save({ action: "update_hydration", goal_ml: value });
            }
            return;
        }
        if (event.target.closest("[data-water-undo]")) {
            const last = hydration.entries[hydration.entries.length - 1];
            if (last) await save({ action: "delete_hydration_entry", entry_id: last.id });
        }
    });

    let waterPending = false;
    let waterIntent = null;
    let waterLastSaved = 0;
    async function addWater(amount) {
        if (waterPending || Date.now() - waterLastSaved < 700) return;
        if (!Number.isFinite(amount) || amount <= 0) { toast("Enter a valid amount"); return; }
        waterPending = true;
        // Reuse the key after an uncertain response so retry cannot log twice.
        if (!waterIntent || waterIntent.amount_ml !== amount) waterIntent = { action: "log_water", amount_ml: amount, idempotency_key: crypto.randomUUID() };
        const disable = value => document.querySelectorAll("[data-water], [data-water-custom]").forEach(button => button.disabled = value);
        disable(true);
        try {
            const operation = state.saveQueue.then(async () => {
                await api(waterIntent);
                waterIntent = null;
                waterLastSaved = Date.now();
                await load(true);
            });
            state.saveQueue = operation.catch(() => {});
            await operation;
        } catch (error) { toast(error.message || "Could not save water. Tap again to retry safely."); }
        finally { waterPending = false; disable(false); }
    }

    function renderHistory() {
        const days = state.history?.days || [];
        const week = days.slice(-7);
        const average = week.length ? week.reduce((total, day) => total + (day.hydration?.total_ml || 0), 0) / week.length : 0;
        const consistency = week.length ? week.reduce((total, day) => total + (day.progress || 0), 0) / week.length : 0;
        document.getElementById("routineHistory").innerHTML = `<section class="routine-history-panel"><div class="routine-panel-label">Last 4 weeks</div>
            <div class="routine-heatmap">${days.map(day => { const progress = day.progress || 0; const level = progress === 0 ? 0 : progress < .5 ? 1 : progress < 1 ? 2 : 3; return `<button class="routine-heat ${day.date === state.date ? "active" : ""}" data-history-date="${esc(day.date)}" data-level="${level}" type="button" aria-label="${esc(day.date)}, ${Math.round(progress * 100)} percent complete" title="${esc(day.date)} · ${Math.round(progress * 100)}%"></button>`; }).join("")}</div>
            <p class="routine-history-summary">This week · ${Math.round(consistency * 100)}% routines · ${number(average / 1000)} L water average</p>
            <div class="routine-history-foot"><span>Consistency, not perfection.</span><button class="routine-text-button" data-export type="button">Export</button></div></section>`;
    }

    document.getElementById("routineHistory").addEventListener("click", event => {
        const day = event.target.closest("[data-history-date]");
        if (day) { state.date = day.dataset.historyDate; load(); return; }
        if (event.target.closest("[data-export]")) window.open(`/api/routines/export?timezone=${encodeURIComponent(timeZone())}`, "_blank");
    });

    function openFormDialog({ title, content, submitLabel, onSubmit }) {
        closeModal();
        const returnFocus = document.activeElement;
        const backdrop = document.createElement("div");
        backdrop.className = "apollo-task-modal-backdrop routine-dialog-backdrop";
        backdrop.innerHTML = `<div class="apollo-task-modal routine-dialog" role="dialog" aria-modal="true" aria-labelledby="routineDialogTitle">
            <div class="routine-dialog-header"><h2 class="apollo-task-modal-title" id="routineDialogTitle">${esc(title)}</h2><button class="routine-dialog-close" type="button" data-cancel aria-label="Close">×</button></div>
            <form>${content}<div class="apollo-task-modal-actions routine-dialog-actions"><button class="apollo-task-modal-button" type="button" data-cancel>Cancel</button><button class="apollo-task-modal-button primary" type="submit">${esc(submitLabel)}</button></div></form></div>`;
        document.body.appendChild(backdrop);
        const dialog = backdrop.querySelector(".routine-dialog");
        const focusable = () => [...dialog.querySelectorAll("button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled])")];
        const onKeydown = event => {
            if (event.key === "Escape") { event.preventDefault(); closeModal(); return; }
            if (event.key === "Tab") {
                const items = focusable(), first = items[0], last = items[items.length - 1];
                if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
                else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
            }
        };
        document.addEventListener("keydown", onKeydown);
        state.modal = { backdrop, returnFocus, cleanup: () => document.removeEventListener("keydown", onKeydown) };
        backdrop.addEventListener("click", event => { if (event.target === backdrop || event.target.closest("[data-cancel]")) closeModal(); });
        backdrop.querySelector("form").addEventListener("submit", async event => {
            event.preventDefault();
            const submit = event.submitter;
            submit.disabled = true;
            try { await onSubmit(new FormData(event.currentTarget)); closeModal(); await load(true); }
            catch (error) { toast(error.message || "Could not save that change"); submit.disabled = false; }
        });
        requestAnimationFrame(() => { backdrop.classList.add("active"); dialog.querySelector("input, textarea, select")?.focus(); });
        return backdrop;
    }

    const field = (label, control) => `<label class="routine-field"><span class="apollo-task-modal-label">${esc(label)}</span>${control}</label>`;

    function openRoutineDialog(routine = null) {
        const checked = index => (routine?.schedule_days || [0, 1, 2, 3, 4, 5, 6]).includes(index) ? "checked" : "";
        openFormDialog({
            title: routine ? "Edit routine" : "New routine", submitLabel: "Save",
            content: `${field("Name", `<input class="routine-input" name="title" maxlength="120" required value="${esc(routine?.title || "")}">`)}
                ${field("Description", `<textarea class="routine-input" name="description" rows="2">${esc(routine?.description || "")}</textarea>`)}
                <fieldset class="routine-field routine-day-field"><legend class="apollo-task-modal-label">Days</legend><div class="routine-weekdays">${["M", "T", "W", "T", "F", "S", "S"].map((day, index) => `<label><input type="checkbox" name="day" value="${index}" ${checked(index)}><span>${day}</span></label>`).join("")}</div></fieldset>
                <div class="routine-field-grid">${field("Starts", `<input class="routine-input" type="time" name="window_start" value="${esc(routine?.window_start || "")}">`)}${field("Ends", `<input class="routine-input" type="time" name="window_end" value="${esc(routine?.window_end || "")}">`)}</div>
                <label class="routine-toggle-row"><input type="checkbox" name="reminder_start" ${routine?.reminder_start ? "checked" : ""}><span>Remind me when the window begins</span></label>
                <label class="routine-toggle-row"><input type="checkbox" name="reminder_end" ${routine?.reminder_end ? "checked" : ""}><span>Remind me near the end if unfinished</span></label>`,
            onSubmit: async form => {
                const values = { title: form.get("title"), description: form.get("description"), schedule_days: form.getAll("day").map(Number), window_start: form.get("window_start"), window_end: form.get("window_end"), reminder_start: form.get("reminder_start") === "on", reminder_end: form.get("reminder_end") === "on" };
                if (!values.schedule_days.length) throw new Error("Choose at least one day");
                await api(routine ? { action: "update_routine", routine_id: routine.id, changes: values } : { action: "create_routine", ...values });
            }
        });
    }

    function openStepDialog(routine, step = null) {
        const scheduleType = step?.schedule_type || "daily";
        const scheduleDays = step?.schedule_days || [0, 1, 2, 3, 4, 5, 6];
        const rule = step?.recurrence_rule || {};
        const advanced = scheduleType !== "daily" || Boolean(step?.alternative_group);
        const backdrop = openFormDialog({
            title: step ? "Edit step" : "Add a step", submitLabel: step ? "Save" : "Add step",
            content: `${field("Name", `<input class="routine-input" name="title" required maxlength="160" value="${esc(step?.title || "")}">`)}
                ${field("Type", `<select class="routine-input" name="step_type">${[["checkbox", "Checkbox"], ["counter", "Counter"], ["quantity", "Measurable quantity"]].map(([value, label]) => `<option value="${value}" ${step?.step_type === value ? "selected" : ""}>${label}</option>`).join("")}</select>`)}
                <div class="routine-field-grid">${field("Target", `<input class="routine-input" name="target" type="number" min="0.01" step="0.01" value="${step?.target || 1}">`)}${field("Unit", `<input class="routine-input" name="unit" placeholder="mL, minutes…" value="${esc(step?.unit || "")}">`)}</div>
                <label class="routine-toggle-row"><input type="checkbox" name="linked_hydration" ${step?.linked_hydration ? "checked" : ""}><span>Link this target to water tracking</span></label>
                <label class="routine-toggle-row routine-advanced-toggle"><input type="checkbox" name="show_advanced" ${advanced ? "checked" : ""}><span>Schedule this step differently</span></label>
                <div class="routine-advanced-fields" ${advanced ? "" : "hidden"}>
                    ${field("Repeat", `<select class="routine-input" name="schedule_type"><option value="daily" ${scheduleType === "daily" ? "selected" : ""}>Every routine day</option><option value="weekdays" ${scheduleType === "weekdays" ? "selected" : ""}>Selected weekdays</option><option value="recurrence" ${scheduleType === "recurrence" ? "selected" : ""}>Custom recurrence</option></select>`)}
                    <fieldset class="routine-field routine-day-field"><legend class="apollo-task-modal-label">Weekdays</legend><div class="routine-weekdays">${["M", "T", "W", "T", "F", "S", "S"].map((day, index) => `<label><input type="checkbox" name="step_day" value="${index}" ${scheduleDays.includes(index) ? "checked" : ""}><span>${day}</span></label>`).join("")}</div></fieldset>
                    <div class="routine-recurrence-fields" ${scheduleType === "recurrence" ? "" : "hidden"}><div class="routine-field-grid">${field("Every", `<input class="routine-input" name="recurrence_interval" type="number" min="1" max="52" value="${Number(rule.interval || 1)}">`)}${field("Period", `<select class="routine-input" name="recurrence_frequency"><option value="weekly" ${rule.frequency !== "daily" ? "selected" : ""}>week(s)</option><option value="daily" ${rule.frequency === "daily" ? "selected" : ""}>day(s)</option></select>`)}</div>${field("Starting", `<input class="routine-input" name="recurrence_start" type="date" value="${esc(rule.start_date || state.date)}">`)}</div>
                    ${field("Alternative set (optional)", `<input class="routine-input" name="alternative_group" placeholder="e.g. nighttime treatment" value="${esc(step?.alternative_group || "")}"><small class="routine-field-help">Steps with the same set name count as one: completing either satisfies the routine.</small>`)}
                    ${step ? field(`Exception for ${dateLabel(state.date)}`, `<select class="routine-input" name="exception_action"><option value="">No change</option><option value="skip">Skip on this date</option><option value="substitute">Use a substitute</option><option value="clear">Clear existing exception</option></select><input class="routine-input routine-substitute-input" name="substitute_title" placeholder="Substitute step name" hidden>`) : ""}
                </div>${step ? '<button class="routine-delete-step" data-delete-step type="button">Delete step</button>' : ""}`,
            onSubmit: async form => {
                const selectedDays = form.getAll("step_day").map(Number);
                const useAdvanced = form.get("show_advanced") === "on";
                const kind = useAdvanced ? form.get("schedule_type") : "daily";
                if (useAdvanced && kind !== "daily" && !selectedDays.length) throw new Error("Choose at least one weekday");
                const values = { title: form.get("title"), step_type: form.get("step_type"), target: Number(form.get("target")), unit: form.get("unit"), linked_hydration: form.get("linked_hydration") === "on", schedule_type: kind, schedule_days: selectedDays, alternative_group: useAdvanced ? form.get("alternative_group") : "", recurrence_rule: kind === "recurrence" ? { frequency: form.get("recurrence_frequency"), interval: Number(form.get("recurrence_interval")), start_date: form.get("recurrence_start"), weekdays: selectedDays } : {} };
                await api(step ? { action: "update_step", step_id: step.id, changes: values } : { action: "add_step", routine_id: routine.id, ...values });
                const exceptionAction = form.get("exception_action");
                if (step && exceptionAction) await api({ action: "set_step_exception", routine_id: routine.id, step_id: step.id, date: state.date, exception_action: exceptionAction, substitute_title: form.get("substitute_title") });
            }
        });
        const advancedToggle = backdrop.querySelector('[name="show_advanced"]');
        const advancedFields = backdrop.querySelector(".routine-advanced-fields");
        const scheduleSelect = backdrop.querySelector('[name="schedule_type"]');
        const recurrenceFields = backdrop.querySelector(".routine-recurrence-fields");
        const exceptionSelect = backdrop.querySelector('[name="exception_action"]');
        const substituteInput = backdrop.querySelector(".routine-substitute-input");
        advancedToggle?.addEventListener("change", () => { advancedFields.hidden = !advancedToggle.checked; });
        scheduleSelect?.addEventListener("change", () => { recurrenceFields.hidden = scheduleSelect.value !== "recurrence"; });
        exceptionSelect?.addEventListener("change", () => { substituteInput.hidden = exceptionSelect.value !== "substitute"; });
        backdrop.querySelector("[data-delete-step]")?.addEventListener("click", async () => {
            if (await confirmAction(`Delete “${step.title}”? Past records will stay intact.`)) {
                try { await api({ action: "delete_step", step_id: step.id }); closeModal(); await load(true); }
                catch (error) { toast(error.message); }
            }
        });
    }

    async function deleteRoutine(routine) {
        if (!await confirmAction(`Permanently delete “${routine.title}” and all of its history? This cannot be undone.`)) return;
        const typed = await promptValue(`Type ${routine.title} to confirm`, "");
        if (typed === null) return;
        if (typed !== routine.title) { toast("Name did not match"); return; }
        await save({ action: "delete_routine", routine_id: routine.id, delete_history: true });
    }

    const confirmAction = message => typeof window.apolloConfirm === "function" ? window.apolloConfirm(message) : Promise.resolve(false);
    const promptValue = (title, value) => typeof window.apolloPrompt === "function" ? window.apolloPrompt(title, String(value ?? "")) : Promise.resolve(null);

    function toast(message) {
        document.querySelector(".routine-toast")?.remove();
        const element = document.createElement("div");
        element.className = "routine-toast";
        element.setAttribute("role", "status");
        element.textContent = message;
        document.body.appendChild(element);
        window.setTimeout(() => element.remove(), 2600);
    }

    document.getElementById("routineCreate").addEventListener("click", () => openRoutineDialog());
    document.querySelectorAll("[data-date-move]").forEach(element => element.addEventListener("click", () => {
        state.date = shiftDate(state.date, Number(element.dataset.dateMove));
        document.getElementById("routineDateLabel").textContent = dateLabel(state.date);
        window.ApolloDateNav?.setToday("routines", state.date === today());
        load();
    }));
    document.getElementById("routineToday").addEventListener("click", () => {
        state.date = today();
        document.getElementById("routineDateLabel").textContent = dateLabel(state.date);
        window.ApolloDateNav?.setToday("routines", true);
        load();
    });

    const params = new URLSearchParams(location.search);
    if (params.get("tab") === "routines") {
        const id = params.get("routine");
        if (id) state.expanded.add(id);
        window.setTimeout(() => window.openRoutines({ routineId: id }), 0);
    }
})();
