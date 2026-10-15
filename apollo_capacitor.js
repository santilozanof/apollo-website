/* Apollo's optional iOS bridge. It is a no-op in ordinary browsers. */
(() => {
    const capacitor = window.Capacitor;
    if (!capacitor?.isNativePlatform?.()) return;
    if (window.__apolloCapacitorVersion === "1.4") return;
    window.__apolloCapacitorVersion = "1.4";
    window.__apolloCapacitorReady = true;

    const platform = capacitor.getPlatform?.() || "native";
    const nativeHandler = window.webkit?.messageHandlers?.apolloNative;
    const plugins = capacitor.Plugins || {};
    const { App, Browser, Haptics, Keyboard, StatusBar } = plugins;
    const APOLLO_ORIGIN = location.origin;
    const NATIVE_ROUTES = new Set([
        "home", "apollo", "music", "calendar", "tasks", "studio", "routines", "settings"
    ]);
    const nativeRequests = new Map();
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let networkBanner;
    let lastHapticAt = 0;

    document.documentElement.classList.add("apollo-capacitor", `apollo-capacitor-${platform}`);
    document.documentElement.classList.toggle("apollo-reduce-motion", reduceMotion.matches);

    const sunMark = '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7"/>';
    const aMark = '<rect x="1" y="1" width="30" height="30" rx="8" fill="#0d0d0d"/><path d="M5 25 L14.5 6 L27 25" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M6.5 20 C11 15.5 18 14.5 27 19" fill="none" stroke="currentColor" stroke-width="1.35"/>';
    function applyApolloMark() {
        document.querySelectorAll(
            ".apollo-boot-logo svg, .brand-mark svg, .os-wordmark-mark svg, .os-command-mark svg"
        ).forEach(svg => {
            if (svg.dataset.apolloA === "true") return;
            svg.setAttribute("viewBox", "0 0 32 32");
            svg.setAttribute("fill", "none");
            svg.setAttribute("stroke-linecap", "round");
            svg.setAttribute("stroke-linejoin", "round");
            svg.innerHTML = aMark;
            svg.dataset.apolloA = "true";
        });
        document.querySelectorAll(
            ".apollo-welcome-mark svg, .apollo-mobile-chat-mark svg, .apollo-message-mark svg, .apollo-image-generating-mark svg"
        ).forEach(svg => {
            if (svg.dataset.apolloSun === "true") return;
            svg.setAttribute("viewBox", "0 0 24 24");
            svg.setAttribute("fill", "none");
            svg.setAttribute("stroke", "currentColor");
            svg.setAttribute("stroke-width", "1.65");
            svg.setAttribute("stroke-linecap", "round");
            svg.setAttribute("stroke-linejoin", "round");
            svg.innerHTML = sunMark;
            svg.dataset.apolloSun = "true";
        });
    }
    applyApolloMark();
    document.addEventListener("DOMContentLoaded", applyApolloMark, { once: true });
    const messageRoot = document.getElementById("apolloMessages");
    if (messageRoot) {
        new MutationObserver(records => {
            const hasNewMark = records.some(record => [...record.addedNodes].some(node =>
                node.nodeType === Node.ELEMENT_NODE && (
                    node.matches?.(".apollo-message-mark, .apollo-image-generating-mark")
                    || node.querySelector?.(".apollo-message-mark, .apollo-image-generating-mark")
                )
            ));
            if (hasNewMark) applyApolloMark();
        }).observe(messageRoot, { childList: true, subtree: true });
    }

    function pluginCall(plugin, method, options) {
        try {
            const result = plugin?.[method]?.(options);
            result?.catch?.(() => {});
            return result;
        } catch (_) {
            return undefined;
        }
    }

    function postNative(type, payload = {}) {
        if (!nativeHandler?.postMessage) return false;
        try {
            nativeHandler.postMessage({ type, ...payload });
            return true;
        } catch (_) {
            return false;
        }
    }

    function requestNative(type, payload = {}) {
        return new Promise((resolve, reject) => {
            const requestID = `${Date.now()}-${crypto.getRandomValues(new Uint32Array(1))[0]}`;
            const timeout = window.setTimeout(() => {
                nativeRequests.delete(requestID);
                reject(new Error(`Native ${type} request timed out`));
            }, 30000);
            nativeRequests.set(requestID, value => {
                window.clearTimeout(timeout);
                resolve(value);
            });
            if (!postNative(type, { requestID, ...payload })) {
                window.clearTimeout(timeout);
                nativeRequests.delete(requestID);
                reject(new Error("Native bridge is unavailable"));
            }
        });
    }

    window.__apolloNativeResolve = (requestID, value) => {
        const resolve = nativeRequests.get(String(requestID));
        if (!resolve) return;
        nativeRequests.delete(String(requestID));
        resolve(value);
    };

    function currentRoute() {
        const route = document.body?.dataset?.apolloRoute || "home";
        return NATIVE_ROUTES.has(route) ? route : "home";
    }

    function syncRoute() {
        applyApolloMark();
        upgradeNativeUI();
        const route = document.body?.dataset?.apolloRoute;
        if (NATIVE_ROUTES.has(route)) postNative("routeChanged", { route });
    }

    window.apolloNativeNavigate = (route, reselected = false) => {
        const destination = String(route || "").toLowerCase();
        if (!NATIVE_ROUTES.has(destination)) return false;

        if (reselected && destination === currentRoute()) {
            const activeView = document.querySelector(".main > .active, .main > .home:not(.hidden)");
            const scroller = activeView?.querySelector?.(".apollo-messages") || activeView || document.querySelector(".main");
            scroller?.scrollTo?.({ top: 0, behavior: reduceMotion.matches ? "auto" : "smooth" });
            return true;
        }

        window.apolloNavigate?.(destination);
        syncRoute();
        return true;
    };

    // UIKit owns the visible viewport through UIKeyboardLayoutGuide. No JS
    // keyboard geometry, class toggle, or second composer animation is needed.

    function upgradeNativeUI() {
        const routineToolbar = document.querySelector("#routinesView .routine-toolbar");
        const routineAdd = document.getElementById("routineCreate");
        if (routineToolbar && routineAdd && !routineToolbar.classList.contains("apollo-native-date-controls")) {
            const dateLabel = document.getElementById("routineDateLabel");
            const today = document.getElementById("routineToday");
            routineToolbar.classList.add("apollo-native-date-controls");
            if (dateLabel) routineToolbar.prepend(dateLabel);
            routineToolbar.append(routineAdd, today);
            routineToolbar.querySelectorAll("[data-date-move]").forEach(button => routineToolbar.append(button));
            // Routines normally hides Today on the current day. The shared
            // Calendar-style row keeps its center position, disabled instead.
            if (dateLabel && today) {
                const syncToday = () => {
                    const isToday = dateLabel.textContent.trim() === "Today";
                    today.hidden = false;
                    today.disabled = isToday;
                    today.setAttribute("aria-current", isToday ? "date" : "false");
                };
                new MutationObserver(syncToday).observe(dateLabel, { childList: true });
                new MutationObserver(() => {
                    if (today.hidden) syncToday();
                }).observe(today, { attributes: true, attributeFilter: ["hidden"] });
                syncToday();
            }
        }

        const nowPlaying = document.getElementById("apolloNowPlaying");
        const queue = document.getElementById("apolloQueue");
        if (nowPlaying && queue && !queue.classList.contains("apollo-native-queue-action")) {
            queue.classList.add("apollo-native-queue-action");
            nowPlaying.append(queue);
            // Keep the fixed sheet outside the card's isolated stacking context,
            // above its existing scrim. The desktop queue handler retains the
            // same elements and listeners; only their native presentation moves.
            const panel = document.getElementById("apolloQueuePanel");
            if (panel) document.getElementById("musicView")?.append(panel);
        }

        const history = document.querySelector("#settingsView .apollo-notification-history-section");
        if (history && !history.querySelector(".apollo-native-notification-disclosure")) {
            const heading = document.createElement("button");
            heading.type = "button";
            heading.className = "apollo-native-notification-disclosure";
            heading.setAttribute("aria-expanded", "false");
            heading.setAttribute("aria-controls", "apolloNotificationHistoryPanel");
            heading.innerHTML = '<span>Recent notifications <small class="apollo-native-notification-count"></small></span><span class="apollo-native-disclosure-chevron" aria-hidden="true"></span>';
            const panel = history.querySelector(".apollo-settings-panel");
            if (panel) {
                panel.id = "apolloNotificationHistoryPanel";
                panel.inert = true;
                panel.setAttribute("aria-hidden", "true");
                history.insertBefore(heading, panel);
                heading.addEventListener("click", () => {
                    const expanded = !history.classList.toggle("apollo-native-collapsed");
                    history.classList.toggle("apollo-native-expanded", expanded);
                    heading.setAttribute("aria-expanded", String(expanded));
                    panel.inert = !expanded;
                    panel.setAttribute("aria-hidden", String(!expanded));
                    if (expanded) {
                        panel.style.maxHeight = `${panel.scrollHeight}px`;
                    } else {
                        panel.style.maxHeight = `${panel.scrollHeight}px`;
                        requestAnimationFrame(() => { panel.style.maxHeight = "0px"; });
                    }
                });
                history.classList.add("apollo-native-collapsed");
                const list = document.getElementById("apolloNotificationHistory");
                const updateCount = () => {
                    const count = list?.querySelectorAll(".apollo-notification-history-row").length || 0;
                    heading.querySelector(".apollo-native-notification-count").textContent = String(count);
                    if (history.classList.contains("apollo-native-expanded")) {
                        panel.style.maxHeight = `${panel.scrollHeight}px`;
                    }
                };
                updateCount();
                if (list) new MutationObserver(updateCount).observe(list, { childList: true });
            }
        }
    }

    upgradeNativeUI();
    document.addEventListener("DOMContentLoaded", upgradeNativeUI, { once: true });
    const settingsInner = document.querySelector("#settingsView .apollo-settings-inner");
    if (settingsInner && !settingsInner.querySelector(".apollo-notification-history-section")) {
        const observer = new MutationObserver(() => {
            upgradeNativeUI();
            if (settingsInner.querySelector(".apollo-notification-history-section")) observer.disconnect();
        });
        observer.observe(settingsInner, { childList: true });
    }

    function syncStatusBarAndTheme() {
        const theme = document.documentElement.dataset.theme;
        const isLight = theme === "light";
        pluginCall(StatusBar, "show");
        pluginCall(StatusBar, "setOverlaysWebView", { overlay: true });
        // Capacitor names styles for their intended background: DARK means light text.
        pluginCall(StatusBar, "setStyle", { style: isLight ? "LIGHT" : "DARK" });
        const preference = document.documentElement.dataset.themePreference
            || localStorage.getItem("apollo.setting.theme")
            || "system";
        postNative("themeChanged", {
            theme: isLight ? "light" : "dark",
            preference: ["light", "dark", "system"].includes(preference) ? preference : "system"
        });
    }

    function showNetworkState(message) {
        if (!networkBanner) {
            networkBanner = document.createElement("div");
            networkBanner.className = "apollo-native-network-banner";
            networkBanner.setAttribute("role", "status");
            networkBanner.setAttribute("aria-live", "polite");
            document.body.appendChild(networkBanner);
        }
        networkBanner.textContent = message || "";
        networkBanner.classList.toggle("is-visible", Boolean(message));
    }

    async function checkApolloConnection() {
        try {
            const response = await fetch("/api/connections", {
                cache: "no-store",
                headers: { Accept: "application/json" },
                signal: AbortSignal.timeout?.(7000)
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            showNetworkState("");
            document.dispatchEvent(new CustomEvent("apollo:native-network", { detail: { online: true } }));
            return true;
        } catch (_) {
            showNetworkState("Apollo is offline — check Tailscale");
            document.dispatchEvent(new CustomEvent("apollo:native-network", { detail: { online: false } }));
            return false;
        }
    }

    window.apolloNativeDidResume = () => {
        document.dispatchEvent(new CustomEvent("apollo:native-resume"));
        checkApolloConnection();
        if (document.body?.dataset?.apolloRoute === "settings") {
            window.setTimeout(() => window.openSettings?.(), 120);
        }
    };

    function externalURL(rawURL) {
        try {
            const url = new URL(rawURL, location.href);
            if (url.origin === APOLLO_ORIGIN) return null;
            if (!["http:", "https:"].includes(url.protocol)) return null;
            return url.href;
        } catch (_) {
            return null;
        }
    }

    function hapticsEnabled() {
        return localStorage.getItem("apollo-ios-haptics") !== "off";
    }

    function playHaptic(style = "LIGHT") {
        const now = performance.now();
        if (!hapticsEnabled() || now - lastHapticAt < 80) return;
        lastHapticAt = now;
        pluginCall(Haptics, "impact", { style });
    }

    function dismissWebMenu(trigger, menu) {
        menu.style.display = "none";
        trigger.setAttribute("aria-expanded", "false");
        trigger.closest?.(".apollo-history-card")?.classList.remove("menu-open");
        document.body.classList.remove("apollo-chat-menu-open");

        if (trigger.matches("[data-menu]")) {
            document.body.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        }
    }

    async function presentNativeContextMenu(trigger) {
        const menu = trigger.matches("[data-menu]")
            ? trigger.parentElement?.querySelector?.("[role='menu']")
            : document.querySelector(".apollo-history-menu[style*='block']");
        const buttons = [...(menu?.querySelectorAll?.("button") || [])].filter(button => !button.disabled);
        if (!menu || !buttons.length) return;

        const previousDisplay = menu.style.display;
        menu.style.display = "none";

        const options = buttons.map((button, index) => ({
            id: `item-${index}`,
            label: button.textContent.trim(),
            destructive: button.matches(".danger, .delete, [data-delete-routine], [data-delete-step]")
        }));

        try {
            const selectedID = await window.apolloNative.actionSheet(
                trigger.getAttribute("aria-label") || "Options",
                options
            );
            if (typeof selectedID === "string" && selectedID.startsWith("item-")) {
                const index = Number(selectedID.slice(5));
                if (Number.isInteger(index) && buttons[index]?.isConnected) {
                    buttons[index].click();
                    return;
                }
            }
            dismissWebMenu(trigger, menu);
        } catch (_) {
            menu.style.display = previousDisplay || "block";
        }
    }

    window.apolloNative = Object.freeze({
        confirm(message, options = {}) {
            return requestNative("confirm", {
                title: String(options.title || "Are you sure?"),
                message: String(message || ""),
                confirmLabel: String(options.confirmLabel || "Continue"),
                destructive: options.destructive !== false
            }).then(Boolean);
        },
        prompt(title, value = "", options = {}) {
            return requestNative("prompt", {
                title: String(title || "Enter a value"),
                message: String(options.message || ""),
                value: String(value || ""),
                confirmLabel: String(options.confirmLabel || "Save")
            });
        },
        actionSheet(title, options, message = "") {
            const safeOptions = Array.isArray(options) ? options.slice(0, 8).map(option => ({
                id: String(option.id || ""),
                label: String(option.label || ""),
                destructive: Boolean(option.destructive)
            })) : [];
            return requestNative("actionSheet", {
                title: String(title || "Choose an option"),
                message: String(message || ""),
                options: safeOptions
            });
        },
        setHapticsEnabled(enabled) {
            localStorage.setItem("apollo-ios-haptics", enabled ? "on" : "off");
        },
        get hapticsEnabled() {
            return hapticsEnabled();
        },
        checkConnection: checkApolloConnection
    });

    const fallbackConfirm = window.apolloConfirm;
    if (typeof fallbackConfirm === "function") {
        window.apolloConfirm = (message = "Delete this item?", options = {}) =>
            window.apolloNative.confirm(message, {
                ...options,
                title: options.title || "Delete this?",
                confirmLabel: options.confirmLabel || "Delete",
                destructive: options.destructive !== false
            }).catch(() => fallbackConfirm(message, options));
    }

    const fallbackPrompt = window.apolloPrompt;
    if (typeof fallbackPrompt === "function") {
        window.apolloPrompt = (title = "Enter a value", value = "") =>
            window.apolloNative.prompt(title, value).catch(() => fallbackPrompt(title, value));
    }

    document.addEventListener("click", event => {
        const menuTrigger = event.target.closest?.("[data-menu], .apollo-history-menu-button");
        if (menuTrigger) {
            const routineID = menuTrigger.closest?.("[data-routine]")?.dataset?.routine;
            requestAnimationFrame(() => {
                const liveTrigger = routineID
                    ? document.querySelector(`[data-routine="${CSS.escape(routineID)}"] [data-menu]`)
                    : menuTrigger;
                if (liveTrigger) presentNativeContextMenu(liveTrigger);
            });
        }

        const interactive = event.target.closest?.("button, .nav-button, [role='button']");
        if (interactive && !interactive.disabled) {
            const meaningful = interactive.matches(
                ".apollo-send-button, [type='submit'], .routine-step-check, .apollo-task-check, .apollo-confirm-delete, .routine-primary"
            );
            playHaptic(meaningful ? "MEDIUM" : "LIGHT");
        }

        const anchor = event.target.closest?.("a[href]");
        const target = anchor && externalURL(anchor.href);
        if (!target || !Browser?.open) return;
        event.preventDefault();
        pluginCall(Browser, "open", { url: target });
    }, { capture: true });

    document.addEventListener("change", event => {
        if (event.target.matches?.("input[type='checkbox'], input[type='radio'], select")) {
            pluginCall(Haptics, "selectionChanged");
        }
    }, { capture: true });

    const originalOpen = window.open.bind(window);
    window.open = (url, target, features) => {
        const external = externalURL(url);
        if (external && Browser?.open) {
            pluginCall(Browser, "open", { url: external });
            return null;
        }
        return originalOpen(url, target, features);
    };

    pluginCall(Keyboard, "setResizeMode", { mode: "none" });

    App?.addListener?.("appStateChange", ({ isActive }) => {
        document.body.classList.toggle("apollo-native-backgrounded", !isActive);
        if (isActive) window.apolloNativeDidResume();
    });

    window.addEventListener("online", checkApolloConnection);
    window.addEventListener("offline", () => showNetworkState("Apollo is offline — check Tailscale"));
    window.addEventListener("statusTap", () => window.apolloNativeNavigate(currentRoute(), true));

    new MutationObserver(syncStatusBarAndTheme).observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme"]
    });
    new MutationObserver(syncRoute).observe(document.body, {
        attributes: true,
        attributeFilter: ["data-apollo-route"]
    });

    const syncBadge = () => postNative("badgeChanged", {
        visible: Boolean(document.querySelector(".nav-button.apollo-response-ready"))
    });
    const badgeObserver = new MutationObserver(syncBadge);
    document.querySelectorAll(".nav-button").forEach(button => badgeObserver.observe(button, {
        attributes: true,
        attributeFilter: ["class"]
    }));

    const syncReducedMotion = event => {
        document.documentElement.classList.toggle("apollo-reduce-motion", event.matches);
    };
    reduceMotion.addEventListener?.("change", syncReducedMotion);

    syncStatusBarAndTheme();
    syncBadge();
    checkApolloConnection();
    postNative("ready", { route: currentRoute() });
})();
