/* Server-authorized tab step-up. No credentials or grants enter web storage. */
(() => {
    'use strict';
    const names = {home: 'Home', apollo: 'Chat', music: 'Music', calendar: 'Calendar',
        tasks: 'Tasks', routines: 'Routines', studio: 'Studio', settings: 'Settings'};
    const resources = {home: 'debrief', apollo: 'chat', music: 'music', calendar: 'calendar',
        tasks: 'tasks', routines: 'routines', studio: 'studio'};
    const opens = {home: 'openHome', apollo: 'openApollo', music: 'openMusic',
        calendar: 'openCalendar', tasks: 'openTasks', routines: 'openRoutines',
        studio: 'openStudio', settings: 'openSettings'};
    const original = Object.fromEntries(Object.entries(opens).map(([route, key]) => [route, window[key]]));
    const originalNavigate = window.apolloNavigate;
    let state = null, current = document.body.dataset.apolloRoute || 'home';
    let pending = null, stateAt = 0, lockBusy = false;
    let lockedChatId = null;
    const main = document.querySelector('.main');
    if (!main) return;
    const lock = document.createElement('section');
    lock.id = 'apolloSecurityLock';
    lock.setAttribute('role', 'dialog');
    lock.setAttribute('aria-modal', 'true');
    lock.setAttribute('aria-labelledby', 'apolloSecurityTitle');
    lock.innerHTML = `<div class="apollo-security-card">
        <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>
        <h2 id="apolloSecurityTitle">Unlock Apollo</h2>
        <p id="apolloSecurityDescription">Verify it's you to continue.</p>
        <button type="button" class="apollo-security-primary" id="apolloDeviceUnlock">Unlock with passkey</button>
        <input id="apolloSecuritySecret" type="password" autocomplete="current-password" placeholder="Passphrase" aria-label="Security passphrase">
        <button type="button" class="apollo-security-secondary" id="apolloPassphraseUnlock">Unlock with passphrase</button>
        <button type="button" class="apollo-security-secondary" id="apolloRecoveryMode">Use recovery code</button>
        <div id="apolloPublicQuestion" hidden>
            <p>Public question? Ask without unlocking. Apollo will not use your history or connected accounts.</p>
            <input id="apolloPublicInput" type="text" maxlength="1200" aria-label="Public question" placeholder="Ask a public question">
            <button type="button" class="apollo-security-secondary" id="apolloPublicSubmit">Ask publicly</button>
            <p id="apolloPublicAnswer" aria-live="polite"></p>
        </div>
        <div class="apollo-security-feedback" id="apolloSecurityFeedback" role="status" aria-live="polite"></div>
    </div>`;
    main.append(lock);
    const secret = lock.querySelector('#apolloSecuritySecret');
    const feedback = lock.querySelector('#apolloSecurityFeedback');
    const device = lock.querySelector('#apolloDeviceUnlock');
    let recoveryMode = false;

    async function request(path, payload) {
        const response = await fetch('/api/security/' + path, {
            method: payload === undefined ? 'GET' : 'POST', credentials: 'same-origin',
            cache: 'no-store', headers: {'Content-Type': 'application/json', 'X-Apollo-Request': 'security'},
            body: payload === undefined ? undefined : JSON.stringify(payload)
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.error || `Security request failed (${response.status})`);
        return body;
    }
    const resourceFor = route => resources[route] || null;
    const protectedRoute = route => {
        const resource = resourceFor(route);
        if (!resource || !state) return false;
        if (state.tabs?.[resource]) return true;
        if (state.privacy === 'maximum') return true;
        if (state.privacy === 'enhanced') return route === 'apollo' || route === 'home' || route === 'calendar';
        return false;
    };
    const canShow = route => !protectedRoute(route) || !!state.unlocked?.[resourceFor(route)];
    function conceal() { document.body.classList.add('apollo-security-conceal'); }
    function reveal() { document.body.classList.remove('apollo-security-conceal'); document.documentElement.classList.remove('apollo-security-pending'); }
    async function refresh() {
        state = await request('state');
        stateAt = Date.now();
        renderSettings();
        return state;
    }
    function showLock(route, resource = resourceFor(route)) {
        pending = {route, resource};
        conceal();
        if (resource === 'chat') {
            try { lockedChatId = typeof apolloChatId !== 'undefined' ? apolloChatId : null; } catch (_) {}
            const messages = document.querySelector('#apolloMessages');
            for (const child of [...(messages?.children || [])]) if (child.id !== 'apolloWelcome') child.remove();
            document.querySelector('#apolloHistoryTrack')?.replaceChildren();
        }
        document.documentElement.classList.remove('apollo-security-pending');
        lock.querySelector('#apolloSecurityTitle').textContent = route === 'settings' ? 'Verify security settings' : `Unlock ${names[route] || 'Apollo'}`;
        lock.querySelector('#apolloSecurityDescription').textContent = route === 'apollo'
            ? 'Verify it’s you to access private conversations and connected information.'
            : 'Verify it’s you to access this area.';
        feedback.textContent = '';
        secret.value = '';
        recoveryMode = false;
        secret.placeholder = 'Passphrase';
        device.hidden = !(state?.passkeys > 0 && window.PublicKeyCredential && window.isSecureContext);
        lock.querySelector('#apolloPublicQuestion').hidden = route !== 'apollo';
        lock.querySelector('#apolloPublicAnswer').textContent = '';
        lock.querySelector('#apolloRecoveryMode').textContent = 'Use recovery code';
        (device.hidden ? secret : device).focus({preventScroll: true});
    }
    function finishUnlock() {
        const target = pending;
        pending = null;
        if (target?.route && target.route !== current) {
            current = target.route;
            originalNavigate?.(target.route);
        }
        reveal();
        if (target?.resource === 'chat') {
            if (lockedChatId && typeof apolloHistoryOpenChat === 'function') apolloHistoryOpenChat(lockedChatId);
            else {
                const messages = document.querySelector('#apolloMessages');
                if (messages && typeof apolloWelcome !== 'undefined') {
                    apolloWelcome.style.display = 'flex';
                    if (!messages.contains(apolloWelcome)) messages.append(apolloWelcome);
                }
                if (typeof apolloRefreshHistory === 'function') apolloRefreshHistory();
            }
            lockedChatId = null;
        }
        if (target?.route === 'settings') renderSettings();
    }
    async function authenticate(method, value) {
        if (!pending || lockBusy) return;
        lockBusy = true;
        feedback.textContent = '';
        for (const button of lock.querySelectorAll('button')) button.disabled = true;
        try {
            const payload = method === 'recovery' ? {resource: pending.resource, method, code: value}
                : {resource: pending.resource, method, passphrase: value};
            await request('authenticate', payload);
            await refresh();
            if (!state.unlocked?.[pending.resource]) throw new Error('Verification did not create an access grant');
            finishUnlock();
        } catch (error) { feedback.textContent = error.message || 'Verification failed'; }
        finally { lockBusy = false; for (const button of lock.querySelectorAll('button')) button.disabled = false; }
    }
    function decode(value) {
        const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
        const raw = atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, '='));
        return Uint8Array.from(raw, char => char.charCodeAt(0));
    }
    function encode(value) {
        return btoa(String.fromCharCode(...new Uint8Array(value)))
            .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    }
    async function passkey(resource) {
        const challenge = await request('passkey/authenticate/options', {resource});
        const publicKey = challenge.options;
        publicKey.challenge = decode(publicKey.challenge);
        publicKey.allowCredentials = (publicKey.allowCredentials || []).map(item => ({...item, id: decode(item.id)}));
        const credential = await navigator.credentials.get({publicKey});
        if (!credential) throw new Error('Device verification was canceled');
        await request('passkey/authenticate/finish', {challenge_id: challenge.challenge_id,
            credential: {id: credential.id, rawId: encode(credential.rawId), type: credential.type,
                response: {authenticatorData: encode(credential.response.authenticatorData),
                    clientDataJSON: encode(credential.response.clientDataJSON),
                    signature: encode(credential.response.signature),
                    userHandle: credential.response.userHandle ? encode(credential.response.userHandle) : null}}});
    }
    device.addEventListener('click', async () => {
        if (!pending || lockBusy) return;
        lockBusy = true;
        device.disabled = true;
        feedback.textContent = '';
        try {
            await passkey(pending.resource);
            await refresh();
            if (!state.unlocked?.[pending.resource]) throw new Error('Verification did not create an access grant');
            finishUnlock();
        } catch (error) { feedback.textContent = error.name === 'NotAllowedError' ? 'Device verification was canceled' : error.message; }
        finally { device.disabled = false; lockBusy = false; }
    });
    lock.querySelector('#apolloPassphraseUnlock').addEventListener('click', () => authenticate(recoveryMode ? 'recovery' : 'passphrase', secret.value));
    secret.addEventListener('keydown', event => {
        if (event.key === 'Enter') authenticate(recoveryMode ? 'recovery' : 'passphrase', secret.value);
    });
    lock.querySelector('#apolloRecoveryMode').addEventListener('click', event => {
        recoveryMode = !recoveryMode;
        secret.value = '';
        secret.placeholder = recoveryMode ? 'Recovery code' : 'Passphrase';
        event.currentTarget.textContent = recoveryMode ? 'Use passphrase' : 'Use recovery code';
        secret.focus();
    });
    lock.querySelector('#apolloPublicSubmit').addEventListener('click', async () => {
        const input = lock.querySelector('#apolloPublicInput');
        const answer = lock.querySelector('#apolloPublicAnswer');
        answer.textContent = 'Answering without personal data…';
        try {
            const result = await request('public-answer', {question: input.value});
            answer.textContent = result.answer;
        } catch (error) { answer.textContent = error.message; }
    });
    async function routeTo(route) {
        if (!opens[route]) return;
        conceal();
        try {
            if (!state || Date.now() - stateAt > 5000) await refresh();
            const previous = resourceFor(current);
            if (previous && previous !== resourceFor(route) && state.tabs?.[previous] === 'leave') {
                await request('revoke', {resource: previous});
                state.unlocked[previous] = false;
            }
            if (!canShow(route)) { showLock(route); return; }
            pending = null;
            current = route;
            originalNavigate?.(route);
            reveal();
        } catch (error) { showLock(route); feedback.textContent = error.message || 'Security state unavailable'; }
    }
    document.addEventListener('click', event => {
        const button = event.target.closest('.nav-button');
        if (!button) return;
        const label = button.querySelector('.nav-label')?.textContent.trim().toLowerCase();
        const route = label === 'apollo' ? 'apollo' : Object.keys(names).find(key => names[key].toLowerCase() === label);
        if (!route) return;
        event.preventDefault(); event.stopImmediatePropagation();
        routeTo(route);
    }, true);
    window.apolloNavigate = routeTo;
    for (const [route, name] of Object.entries(opens)) window[name] = (...args) => routeTo(route, ...args);
    function checkCurrent() {
        refresh().then(() => {
            if (pending && !state.unlocked?.[pending.resource]) {
                if (!document.body.classList.contains('apollo-security-conceal')) showLock(pending.route, pending.resource);
            }
            else if (!canShow(current)) showLock(current);
            else reveal();
        }).catch(error => { showLock(current); feedback.textContent = error.message || 'Security state unavailable'; });
    }
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            const resource = resourceFor(current);
            if (resource && state?.tabs?.[resource] === 'leave') {
                conceal();
                state.unlocked[resource] = false;
                fetch('/api/security/revoke', {method:'POST', credentials:'same-origin', keepalive:true,
                    headers:{'Content-Type':'application/json','X-Apollo-Request':'security'},
                    body:JSON.stringify({resource})}).catch(() => {});
            }
        } else checkCurrent();
    });
    window.addEventListener('pagehide', () => {
        const resource = resourceFor(current);
        if (resource && state?.tabs?.[resource] === 'leave') {
            fetch('/api/security/revoke', {method:'POST', credentials:'same-origin', keepalive:true,
                headers:{'Content-Type':'application/json','X-Apollo-Request':'security'},
                body:JSON.stringify({resource})}).catch(() => {});
        }
    });
    setInterval(() => { if (!document.hidden && (protectedRoute(current) || pending)) checkCurrent(); }, 5000);
    checkCurrent();

    const settings = document.querySelector('#settingsView .apollo-settings-inner');
    let settingsPanel;
    if (settings) {
        const section = document.createElement('section');
        section.className = 'apollo-settings-section';
        section.innerHTML = `<div class="apollo-settings-section-title">Privacy &amp; Security · Tab Locks</div>
            <div class="apollo-settings-panel"><div class="apollo-security-settings" id="apolloSecuritySettings"></div></div>`;
        settings.append(section);
        settingsPanel = section.querySelector('#apolloSecuritySettings');
    }
    const labels = {chat:'Chat', music:'Music', calendar:'Calendar', tasks:'Tasks',
        routines:'Routines', debrief:'Daily Debrief', studio:'Studio'};
    function renderSettings() {
        if (!settingsPanel || !state) return;
        settingsPanel.replaceChildren();
        if (!state.enrolled) {
            const intro = document.createElement('p');
            intro.textContent = 'First-time enrollment protects private tabs. Ask the Apollo deployment operator for the one-time setup token, then choose a passphrase of at least 16 characters. The token is supplied privately and is never stored in this page.';
            intro.className = 'apollo-security-intro';
            settingsPanel.append(intro);
            const token = document.createElement('input'); token.placeholder = 'Operator setup token'; token.type = 'password'; token.autocomplete = 'off'; token.setAttribute('aria-label', 'Operator setup token');
            const pass = document.createElement('input'); pass.placeholder = 'New passphrase (16+ characters)'; pass.type = 'password'; pass.autocomplete = 'new-password'; pass.setAttribute('aria-label', 'New security passphrase');
            const fields = document.createElement('div'); fields.className = 'apollo-security-enrollment-fields'; fields.append(token, pass);
            const reveal = document.createElement('button'); reveal.type = 'button'; reveal.className = 'apollo-security-reveal'; reveal.textContent = 'Show'; reveal.setAttribute('aria-label', 'Show setup token and passphrase');
            reveal.onclick = () => { const show = token.type === 'password'; token.type = pass.type = show ? 'text' : 'password'; reveal.textContent = show ? 'Hide' : 'Show'; reveal.setAttribute('aria-label', (show ? 'Hide' : 'Show') + ' setup token and passphrase'); };
            const button = document.createElement('button'); button.type = 'button'; button.className = 'apollo-security-enroll-button'; button.textContent = 'Set up security';
            const message = document.createElement('p'); message.className = 'apollo-security-message';
            settingsPanel.append(fields, reveal, button, message);
            button.onclick = async () => {
                try {
                    const result = await request('setup', {setup_token: token.value, passphrase: pass.value});
                    pass.value = ''; token.value = '';
                    await refresh();
                    const codes = document.createElement('p'); codes.className = 'apollo-security-codes';
                    codes.textContent = `Save these one-time recovery codes offline. They will not be shown again: ${result.recovery_codes.join('  ')}`;
                    settingsPanel.prepend(codes);
                } catch (error) { message.textContent = error.message; }
            };
            return;
        }
        const note = document.createElement('p');
        note.textContent = 'Locks are off by default. On Apple devices, a passkey can use Face ID or Touch ID through the system prompt.';
        settingsPanel.append(note);
        const verify = document.createElement('button');
        verify.textContent = state.unlocked?.settings ? 'Security settings unlocked' : 'Verify to change settings';
        verify.onclick = () => showLock('settings', 'settings');
        settingsPanel.append(verify);
        if (!state.unlocked?.settings) return;
        const form = document.createElement('form');
        form.innerHTML = `<fieldset><legend>Individual tab locks</legend></fieldset>
            <label>Protect personal information in Chat
                <select name="privacy"><option value="standard">Standard</option>
                <option value="enhanced">Enhanced Privacy</option><option value="maximum">Maximum Privacy</option></select></label>
            <label><input type="checkbox" name="protect_spotify">Protect private Spotify history</label>
            <button type="submit">Save privacy settings</button>
            <button type="button" id="apolloRegisterPasskey">Add a passkey</button>
            <div id="apolloPasskeyList"></div>
            <fieldset><legend>Passphrase and recovery</legend>
                <input id="apolloCurrentPassphrase" type="password" autocomplete="current-password" placeholder="Current passphrase" aria-label="Current security passphrase">
                <input id="apolloNewPassphrase" type="password" autocomplete="new-password" placeholder="New passphrase (16+ characters)" aria-label="New security passphrase">
                <div class="apollo-security-row"><button type="button" id="apolloChangePassphrase">Change passphrase</button>
                <button type="button" id="apolloNewRecovery">New recovery codes</button></div>
            </fieldset>
            <p class="apollo-security-message" role="status"></p>`;
        const fieldset = form.querySelector('fieldset');
        for (const [resource, label] of Object.entries(labels)) {
            const row = document.createElement('label');
            const check = document.createElement('input'); check.type = 'checkbox'; check.checked = !!state.tabs?.[resource];
            check.dataset.resource = resource;
            const text = document.createElement('span'); text.textContent = label;
            const duration = document.createElement('select'); duration.dataset.resource = resource;
            for (const [value, caption] of [['leave','Relock on leave'],['5m','5 minutes'],['15m','15 minutes']]) {
                const option = document.createElement('option'); option.value = value; option.textContent = caption; duration.append(option);
            }
            duration.value = state.tabs?.[resource] || '5m';
            row.append(check, text, duration); fieldset.append(row);
        }
        form.elements.privacy.value = state.privacy;
        form.elements.protect_spotify.checked = state.protect_spotify;
        const message = form.querySelector('.apollo-security-message');
        form.onsubmit = async event => {
            event.preventDefault();
            const tabs = {};
            for (const check of form.querySelectorAll('input[data-resource]')) if (check.checked) {
                tabs[check.dataset.resource] = form.querySelector(`select[data-resource="${check.dataset.resource}"]`).value;
            }
            try {
                await request('policy', {tabs, privacy: form.elements.privacy.value,
                    protect_spotify: form.elements.protect_spotify.checked});
                await refresh(); routeTo(current);
            } catch (error) { message.textContent = error.message; }
        };
        form.querySelector('#apolloRegisterPasskey').onclick = async () => {
            if (!window.PublicKeyCredential || !window.isSecureContext) {
                message.textContent = 'Passkeys require a secure browser and supported device.'; return;
            }
            try {
                const challenge = await request('passkey/register/options', {});
                const publicKey = challenge.options;
                publicKey.challenge = decode(publicKey.challenge);
                publicKey.user.id = decode(publicKey.user.id);
                publicKey.excludeCredentials = (publicKey.excludeCredentials || []).map(item => ({...item, id: decode(item.id)}));
                const credential = await navigator.credentials.create({publicKey});
                if (!credential) throw new Error('Passkey registration was canceled');
                await request('passkey/register/finish', {challenge_id: challenge.challenge_id,
                    credential: {id: credential.id, rawId: encode(credential.rawId), type: credential.type,
                        response: {attestationObject: encode(credential.response.attestationObject),
                            clientDataJSON: encode(credential.response.clientDataJSON)}}});
                await refresh();
                settingsPanel.querySelector('.apollo-security-message').textContent = 'Passkey added.';
            } catch (error) { message.textContent = error.message; }
        };
        form.querySelector('#apolloChangePassphrase').onclick = async () => {
            try {
                await request('passphrase/change', {
                    current_passphrase: form.querySelector('#apolloCurrentPassphrase').value,
                    new_passphrase: form.querySelector('#apolloNewPassphrase').value});
                await refresh();
                settingsPanel.querySelector('.apollo-security-message').textContent = 'Passphrase changed. Protected tabs require a new unlock.';
            } catch (error) { message.textContent = error.message; }
        };
        form.querySelector('#apolloNewRecovery').onclick = async () => {
            try {
                const result = await request('recovery/regenerate', {
                    current_passphrase: form.querySelector('#apolloCurrentPassphrase').value});
                form.querySelector('#apolloCurrentPassphrase').value = '';
                const codes = document.createElement('p'); codes.className = 'apollo-security-codes';
                codes.textContent = `Save these new one-time codes offline. Earlier codes are invalid: ${result.recovery_codes.join('  ')}`;
                form.querySelector('#apolloPasskeyList').before(codes);
            } catch (error) { message.textContent = error.message; }
        };
        settingsPanel.append(form);
        request('passkeys').then(result => {
            const list = form.querySelector('#apolloPasskeyList');
            for (const [index, item] of result.passkeys.entries()) {
                const row = document.createElement('div'); row.className = 'apollo-security-row';
                const label = document.createElement('span');
                label.textContent = `Passkey ${index + 1} · ${new Date(item.created_at * 1000).toLocaleDateString()}`;
                const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove';
                remove.setAttribute('aria-label', `Remove passkey ${index + 1}`);
                remove.onclick = async () => {
                    try { await request('passkey/delete', {id: item.id}); await refresh(); }
                    catch (error) { message.textContent = error.message; }
                };
                row.append(label, remove); list.append(row);
            }
        }).catch(error => { message.textContent = error.message; });
    }
})();
