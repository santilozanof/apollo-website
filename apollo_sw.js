/* Apollo Web Push service worker.  It contains no account data or secrets. */
self.addEventListener("push", event => {
    let payload = {};
    try {
        payload = event.data ? event.data.json() : {};
    } catch (_) {}
    const url = typeof payload.url === "string" && payload.url.startsWith("/") && !payload.url.startsWith("//")
        ? payload.url
        : "/";
    event.waitUntil(self.registration.showNotification(payload.title || "Apollo", {
        body: payload.body || "You have an Apollo update.",
        tag: payload.notification_id || undefined,
        data: {url, notificationId: payload.notification_id || null},
        icon: "/favicon.svg",
        badge: "/favicon.svg",
    }));
});

self.addEventListener("notificationclick", event => {
    event.notification.close();
    const url = event.notification.data?.url || "/";
    event.waitUntil((async () => {
        const windows = await clients.matchAll({type: "window", includeUncontrolled: true});
        for (const client of windows) {
            if (client.url.startsWith(self.location.origin)) {
                await client.focus();
                if ("navigate" in client) await client.navigate(url);
                return;
            }
        }
        await clients.openWindow(url);
    })());
});
