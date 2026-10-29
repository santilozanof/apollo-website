/* Small shared Settings disclosure controller. Existing controls keep their nodes/listeners. */
(() => {
    const inner = document.querySelector('#settingsView .apollo-settings-inner');
    if (!inner) return;
    const collapsed = /^(Memory & conversation history|Notifications|Notification history|Privacy & Security)/i;
    const chevron = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.classList.contains('apollo-reduce-motion');
    function mount(section) {
        if (section.dataset.apolloDisclosure || !section.classList.contains('apollo-settings-section')) return;
        const title = section.querySelector(':scope > .apollo-settings-section-title');
        const panel = section.querySelector(':scope > .apollo-settings-panel');
        if (!title || !panel) return;
        const label = title.textContent.trim();
        section.dataset.apolloDisclosure = '1';
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'apollo-settings-disclosure';
        button.innerHTML = `<span class="apollo-settings-disclosure-label"></span>${chevron}`;
        button.querySelector('span').textContent = label;
        const body = document.createElement('div');
        body.className = 'apollo-settings-disclosure-body';
        body.id = 'apollo-settings-disclosure-' + (section.id || [...inner.children].indexOf(section));
        button.setAttribute('aria-controls', body.id);
        title.replaceWith(button);
        panel.replaceWith(body);
        body.append(panel);
        let open = !collapsed.test(label);
        section.classList.toggle('is-open', open);
        button.setAttribute('aria-expanded', String(open));
        body.inert = !open;
        body.setAttribute('aria-hidden', String(!open));
        body.style.height = open ? 'auto' : '0px';
        button.addEventListener('click', () => {
            const next = !open;
            if (reduced()) {
                open = next; section.classList.toggle('is-open', open);
                button.setAttribute('aria-expanded', String(open));
                body.inert = !open; body.setAttribute('aria-hidden', String(!open));
                body.style.height = open ? 'auto' : '0px';
                return;
            }
            if (!next) body.style.height = body.scrollHeight + 'px';
            else { body.inert = false; body.setAttribute('aria-hidden', 'false'); }
            open = next;
            section.classList.toggle('is-open', open);
            button.setAttribute('aria-expanded', String(open));
            requestAnimationFrame(() => { body.style.height = open ? body.scrollHeight + 'px' : '0px'; });
        });
        body.addEventListener('transitionend', event => {
            if (event.target !== body || event.propertyName !== 'height') return;
            body.style.height = open ? 'auto' : '0px';
            body.inert = !open;
            body.setAttribute('aria-hidden', String(!open));
        });
    }
    inner.querySelectorAll(':scope > .apollo-settings-section').forEach(mount);
    new MutationObserver(() => inner.querySelectorAll(':scope > .apollo-settings-section').forEach(mount))
        .observe(inner, {childList:true});
})();
