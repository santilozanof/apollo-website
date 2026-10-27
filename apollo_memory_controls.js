/* Memory controls share Apollo's existing private API; retrieved text is never HTML. */
(() => {
    const create = (tag, text) => {
        const element = document.createElement(tag);
        if (text !== undefined) element.textContent = text;
        return element;
    };
    async function api(path = '', method = 'GET', data) {
        const response = await fetch('/api/memory' + path, {
            method, cache: 'no-store', headers: {'Content-Type': 'application/json'},
            body: data === undefined ? undefined : JSON.stringify(data)
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Memory request failed');
        return result;
    }
    function mount() {
        const settings = document.querySelector('#settingsView .apollo-settings-inner');
        if (!settings || document.getElementById('apolloMemoryControls')) return;
        const section = create('section');
        section.id = 'apolloMemoryControls'; section.className = 'apollo-settings-section';
        const title = create('div', 'Memory & conversation history');
        title.className = 'apollo-settings-section-title';
        const panel = create('div'); panel.className = 'apollo-settings-panel';
        const details = create('details');
        details.append(create('summary', 'Review memories and privacy controls'));
        const content = create('div'); content.style.padding = '16px';
        const status = create('p'); status.setAttribute('role', 'status');
        details.append(content, status); panel.append(details); section.append(title, panel); settings.append(section);
        const run = async fn => {
            try { status.textContent = ''; await fn(); }
            catch (error) { status.textContent = error.message; }
        };
        const button = (label, handler) => {
            const el = create('button', label); el.type = 'button';
            el.addEventListener('click', () => run(async () => {
                el.disabled = true;
                try { await handler(); } finally { el.disabled = false; }
            }));
            return el;
        };
        async function load() {
            const data = await api(); content.replaceChildren();
            content.append(create('p', 'Saved memories carry their sources. Forgetting excludes them from future recall; delete a chat to remove its original messages.'));
            for (const [key, label] of [['auto_memory', 'Automatically save useful, nonsensitive facts'], ['history_search', 'Search past conversations when relevant']]) {
                const row = create('label'); row.style.display = 'block'; row.style.marginBlock = '12px';
                const input = create('input'); input.type = 'checkbox'; input.checked = Boolean(data.settings[key]);
                input.addEventListener('change', () => run(async () => {
                    try { await api('/settings', 'POST', {[key]: input.checked}); }
                    catch (error) { input.checked = !input.checked; throw error; }
                }));
                row.append(input, document.createTextNode(' ' + label)); content.append(row);
            }
            const retentionLabel = create('label', 'Conversation retention (days; 0 keeps all): ');
            const retention = create('input'); retention.type = 'number'; retention.min = '0'; retention.max = '36500';
            retention.value = data.settings.retention_days; retention.style.width = '90px'; retentionLabel.append(retention);
            content.append(retentionLabel, button('Save retention', async () => {
                const days = Number(retention.value);
                if (!Number.isInteger(days) || days < 0 || days > 36500) throw new Error('Enter a whole number from 0 to 36500.');
                if (days && !confirm(`Permanently delete messages older than ${days} days and their derived memories?`)) return;
                await api('/settings', 'POST', {retention_days: days}); await load();
            }));
            const semantic = data.semantic_search === 'not_configured'
                ? 'Search currently matches words and exact phrases. Meaning-based search is not available yet.'
                : 'Meaning-based search is enabled. Older conversations may still be indexing.';
            content.append(create('p', semantic));
            content.append(create('h4', 'Saved memories'));
            if (!data.memories.length) content.append(create('p', 'No saved memories yet.'));
            for (const memory of data.memories) {
                const item = create('div'); item.style.marginBlock = '16px';
                item.append(create('p', memory.content));
                item.append(create('small', `${memory.category} · ${new Date(memory.source_created_at || memory.updated_at).toLocaleDateString()} · ${memory.source_message_id ? `chat ${memory.chat_id}, message ${memory.source_message_id}` : 'saved by you'}`));
                item.append(button('Correct', async () => {
                    const value = prompt('Correct this memory:', memory.content);
                    if (!value?.trim()) return;
                    await api('', 'POST', {content: value, category: memory.category, key: memory.memory_key}); await load();
                }), button('Forget', async () => { await api('/' + memory.id, 'DELETE'); await load(); }));
                content.append(item);
            }
            content.append(create('h4', 'Exclude a topic'));
            const phrase = create('input'); phrase.type = 'text'; phrase.placeholder = 'Exact word or phrase';
            phrase.setAttribute('aria-label', 'Topic to exclude from recall');
            content.append(phrase, button('Exclude', async () => {
                await api('/forget', 'POST', {phrase: phrase.value}); await load();
            }), create('p', data.exclusions.length ? 'Excluded phrases: ' + data.exclusions.join(', ') : 'No excluded topics.'));
            for (const excluded of data.exclusions) content.append(button(`Allow topic: ${excluded}`, async () => {
                await api('/allow-topic', 'POST', {phrase: excluded}); await load();
            }));
            content.append(create('h4', 'Exclude a conversation'));
            const chatID = create('select');
            const chatsResponse = await fetch('/api/chats', {cache: 'no-store'});
            if (!chatsResponse.ok) throw new Error('Conversations could not be loaded.');
            const chats = (await chatsResponse.json()).chats || [];
            for (const chat of chats) {
                const option = create('option', chat.title || `Chat ${chat.id}`); option.value = chat.id; chatID.append(option);
            }
            chatID.setAttribute('aria-label', 'Conversation to exclude');
            content.append(chatID, button('Exclude chat', async () => {
                await api('/exclude-chat', 'POST', {chat_id: Number(chatID.value), excluded: true}); await load();
            }));
            for (const id of data.excluded_chats) content.append(button(`Allow chat ${id} again`, async () => {
                await api('/exclude-chat', 'POST', {chat_id: id, excluded: false}); await load();
            }));
            content.append(create('h4', 'Search conversations'));
            const query = create('input'); query.type = 'search'; query.placeholder = 'Restaurant in Paris…';
            query.setAttribute('aria-label', 'Conversation search');
            const results = create('div'); results.setAttribute('aria-live', 'polite');
            content.append(query, button('Search', async () => {
                const found = await api('/search?q=' + encodeURIComponent(query.value)); results.replaceChildren();
                if (!found.results.length) results.append(create('p', found.status === 'disabled' ? 'History search is disabled.' : 'Nothing found.'));
                for (const result of found.results) {
                    results.append(create('p', `Chat ${result.chat_id} · ${result.created_at} · ${result.role}`), create('blockquote', result.content));
                }
            }), results);
        }
        details.addEventListener('toggle', () => { if (details.open) run(load); });
    }
    mount();
    const observer = new MutationObserver(() => {
        mount();
        if (document.getElementById('apolloMemoryControls')) observer.disconnect();
    });
    observer.observe(document.body, {childList: true, subtree: true});
})();
