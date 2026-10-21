/* One shared, bounded health poller for Home and Settings. Only safe labels persist. */
(() => {
    const banner = document.getElementById('apolloConnectionBanner');
    if (!banner) return;
    const key = 'apollo.connection-health.v2';
    let pending = null, lastRequest = 0, timer;
    function review() {
        window.openSettings?.();
        document.getElementById('apolloConnectionsPanel')?.scrollIntoView({block: 'center', behavior: 'smooth'});
    }
    function render(data) {
        const problems = (data.integrations || []).filter(item => item.needs_attention);
        banner.replaceChildren();
        banner.hidden = !problems.length;
        if (!problems.length) return;
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        summary.textContent = problems.length === 1 ? `${problems[0].name} needs attention` : `${problems.length} connections need attention`;
        const copy = document.createElement('p');
        copy.textContent = problems.map(item => item.name).join(', ') + ' cannot sync. Review connections to restore your dashboard and Daily Debrief.';
        details.append(summary, copy);
        problems.forEach(item => {
            const row = document.createElement('div');
            row.className = 'apollo-health-detail';
            const label = document.createElement('span');
            label.textContent = item.management_note || `${item.name}: reconnect to restore syncing.`;
            const action = (item.actions || []).find(action => action.method === 'GET' && ['connect', 'reconnect'].includes(action.id));
            const button = document.createElement(action ? 'a' : 'button');
            button.textContent = action ? `Reconnect ${item.name}` : 'Open connection settings';
            if (action && /^\/api\/(google|whoop)\/connect$/.test(action.url)) button.href = action.url;
            else button.addEventListener('click', review);
            row.append(label, button); details.append(row);
        });
        const reviewButton = document.createElement('button');
        reviewButton.type = 'button'; reviewButton.textContent = 'Review connections';
        reviewButton.addEventListener('click', review);
        banner.append(details, reviewButton);
    }
    async function refresh(force = false) {
        if (pending) return pending;
        if (!force && Date.now() - lastRequest < 60000) return;
        lastRequest = Date.now();
        pending = (async () => {
            try {
                const response = await fetch('/api/connections' + (force ? '?refresh=1' : ''), {cache: 'no-store'});
                if (!response.ok) return;
                const data = await response.json();
                if (!data.checked_at) { clearTimeout(timer); timer = setTimeout(() => refresh(true), 12000); return; }
                render(data);
                try { localStorage.setItem(key, JSON.stringify(data)); } catch (_) {}
                window.dispatchEvent(new CustomEvent('apollo:connection-health', {detail: data}));
            } catch (_) { /* Preserve a known issue while the network is unavailable. */ }
            finally { pending = null; }
        })();
        return pending;
    }
    try { render(JSON.parse(localStorage.getItem(key) || '{}')); } catch (_) {}
    window.apolloRefreshConnectionHealth = refresh;
    window.addEventListener('focus', () => refresh(true));
    window.addEventListener('online', () => refresh(true));
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
    setInterval(() => { if (!document.hidden) refresh(); }, 120000);
    refresh(true);
})();
