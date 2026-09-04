/* Apollo Notifications UI. Automations are created and managed through chat. */
(() => {
    const doc = document;
    const escapeHTML = value => String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
    const api = async (url, options = {}) => {
        const response = await fetch(url, {
            ...options,
            headers: {"Content-Type": "application/json", ...(options.headers || {})},
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || "Request failed");
        return data;
    };
    const toUint8Array = value => {
        const base64 = String(value).replace(/-/g, "+").replace(/_/g, "/");
        const padded = base64 + "=".repeat((4 - base64.length % 4) % 4);
        const raw = atob(padded);
        return Uint8Array.from(raw, char => char.charCodeAt(0));
    };
    const settings = doc.getElementById("settingsView");
    const inner = settings?.querySelector(".apollo-settings-inner");
    if (!settings || !inner) return;

    const section = doc.createElement("section");
    section.className = "apollo-settings-section apollo-notification-settings";
    section.innerHTML = `
        <div class="apollo-settings-section-title">Notifications</div>
        <div class="apollo-settings-panel">
            <div class="apollo-setting-row">
                <div class="apollo-setting-copy"><div class="apollo-setting-name">Notifications</div><div class="apollo-setting-description" id="apolloNotificationState">Checking this device…</div></div>
                <div class="apollo-setting-control apollo-notification-actions"><button type="button" class="apollo-toggle" id="apolloNotificationMaster" aria-label="Notifications"></button><button type="button" class="apollo-notification-button" id="apolloNotificationEnable">Enable notifications</button></div>
            </div>
            <div class="apollo-notification-category-list" id="apolloNotificationCategories"></div>
        </div>
    `;
    const historySection = doc.createElement("section");
    historySection.className = "apollo-settings-section apollo-notification-history-section";
    historySection.innerHTML = `
        <div class="apollo-settings-section-title">Notification history</div>
        <div class="apollo-settings-panel"><div class="apollo-notification-history-actions"><span id="apolloNotificationHistoryState">Recent notifications</span><button type="button" class="apollo-notification-text-button" id="apolloNotificationClear">Clear</button></div><div id="apolloNotificationHistory" class="apollo-notification-history"></div></div>
    `;
    inner.append(section, historySection);

    let state = null;
    const categoryLabels = {calendar: "Calendar", tasks: "Tasks", debrief: "Daily Debrief", whoop: "WHOOP", travel: "Travel", automations: "Automations / Reminders", sound: "Sound"};

    const statusCopy = () => {
        if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) return "Notifications aren’t supported in this browser.";
        if (Notification.permission === "denied") return "Notifications are blocked for Apollo in this browser.";
        if (!state?.push_configured) return "Push is not configured on Apollo yet.";
        if (Notification.permission === "granted" && state.subscription_count) return "Enabled on this device.";
        return "Enable notifications to receive Apollo updates when this app is closed.";
    };

    const renderPreferences = () => {
        const prefs = state?.preferences || {};
        const master = doc.getElementById("apolloNotificationMaster");
        const enable = doc.getElementById("apolloNotificationEnable");
        const stateNode = doc.getElementById("apolloNotificationState");
        const permission = "Notification" in window
            ? Notification.permission
            : "unsupported";
        if (master) {
            // Settings' shared toggle stylesheet uses `.on`, not `.active`.
            master.classList.toggle("on", Boolean(prefs.master));
            master.setAttribute("aria-pressed", String(Boolean(prefs.master)));
        }
        if (stateNode) stateNode.textContent = statusCopy();
        if (enable) {
            enable.hidden = permission === "granted" && Boolean(state?.subscription_count);
            enable.disabled = permission === "unsupported" || permission === "denied" || !state?.push_configured;
            enable.textContent = permission === "denied" ? "Permission blocked" : "Enable notifications";
        }
        const list = doc.getElementById("apolloNotificationCategories");
        if (!list) return;
        list.innerHTML = Object.entries(categoryLabels).map(([key, label]) => `
            <button type="button" class="apollo-notification-category ${prefs[key] ? "is-enabled" : ""}" data-notification-category="${key}" aria-pressed="${Boolean(prefs[key])}"><span>${label}</span><small>${prefs[key] ? "On" : "Off"}</small></button>
        `).join("");
    };

    const formatWhen = value => {
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? "Watching" : new Intl.DateTimeFormat(undefined, {month:"short", day:"numeric", hour:"numeric", minute:"2-digit"}).format(date);
    };
    const renderHistory = notifications => {
        const list = doc.getElementById("apolloNotificationHistory");
        if (!list) return;
        list.innerHTML = notifications.length ? notifications.map(item => `<button type="button" class="apollo-notification-history-row ${item.read ? "" : "is-unread"}" data-notification-id="${escapeHTML(item.id)}" data-notification-link="${escapeHTML(item.deep_link || "/")}"><span><strong>${escapeHTML(item.title)}</strong><small>${escapeHTML(item.body)}</small></span><time>${escapeHTML(formatWhen(item.created_at))}</time></button>`).join("") : `<p class="apollo-automation-empty">No notifications yet.</p>`;
    };
    const openDeepLink = link => {
        const tab = new URL(link, location.origin).searchParams.get("tab");
        const routes = {calendar: "openCalendar", tasks: "openTasks", apollo: "openApollo", home: "openHome"};
        if (routes[tab] && typeof window[routes[tab]] === "function") window[routes[tab]]();
    };
    const refresh = async () => {
        try {
            const [nextState, historyData] = await Promise.all([api("/api/notifications/status"), api("/api/notifications")]);
            state = nextState;
            renderPreferences();
            renderHistory(historyData.notifications || []);
        } catch (_) {
            const node = doc.getElementById("apolloNotificationState");
            if (node) node.textContent = "Notification settings are temporarily unavailable.";
        }
    };
    const setPreferences = async values => {
        state.preferences = await api("/api/notifications/preferences", {method:"POST", body:JSON.stringify({preferences: values})}).then(data => data.preferences);
        renderPreferences();
    };
    const enablePush = async () => {
        const node = doc.getElementById("apolloNotificationState");
        try {
            if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) throw new Error("Notifications aren’t supported in this browser.");
            if (!state?.vapid_public_key) throw new Error("Push is not configured on Apollo yet.");
            const permission = await Notification.requestPermission();
            if (permission !== "granted") throw new Error("Permission was not granted. You can change it in your browser settings.");
            const registration = await navigator.serviceWorker.register("/apollo_sw.js");
            const ready = await navigator.serviceWorker.ready;
            const subscription = await ready.pushManager.getSubscription() || await ready.pushManager.subscribe({userVisibleOnly:true, applicationServerKey:toUint8Array(state.vapid_public_key)});
            await api("/api/notifications/subscribe", {method:"POST", body:JSON.stringify({subscription})});
            await setPreferences({master:true, automations:true});
            await refresh();
        } catch (error) {
            if (node) node.textContent = error.message || "Notifications could not be enabled.";
        }
    };

    section.addEventListener("click", async event => {
        if (event.target.closest("#apolloNotificationEnable")) return enablePush();
        if (event.target.closest("#apolloNotificationMaster")) return setPreferences({master: !state?.preferences?.master});
        const category = event.target.closest("[data-notification-category]")?.dataset.notificationCategory;
        if (category) return setPreferences({[category]: !state?.preferences?.[category]});
    });
    historySection.addEventListener("click", async event => {
        if (event.target.closest("#apolloNotificationClear")) { await api("/api/notifications/clear", {method:"POST", body:"{}"}); return refresh(); }
        const row = event.target.closest("[data-notification-id]");
        if (!row) return;
        await api("/api/notifications/read", {method:"POST", body:JSON.stringify({id:row.dataset.notificationId})}).catch(() => {});
        openDeepLink(row.dataset.notificationLink);
        refresh();
    });
    const deepLink = new URL(location.href).searchParams.get("tab");
    if (deepLink) setTimeout(() => openDeepLink(`/?tab=${deepLink}`), 0);
    refresh();
})();
