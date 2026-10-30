/* Server-authorized tab step-up. No credentials or grants enter web storage. */
(() => {
    'use strict';
    const names = {home: 'Home', apollo: 'Chat', music: 'Music', calendar: 'Calendar',
        tasks: 'Tasks', routines: 'Routines', studio: 'Studio', settings: 'Settings'};
    const resources = {home: 'debrief', apollo: 'chat', music: 'music', calendar: 'calendar',
        tasks: 'tasks', routines: 'routines', studio: 'studio', settings: 'settings'};
    const opens = {home: 'openHome', apollo: 'openApollo', music: 'openMusic',
        calendar: 'openCalendar', tasks: 'openTasks', routines: 'openRoutines',
        studio: 'openStudio', settings: 'openSettings'};
    const original = Object.fromEntries(Object.entries(opens).map(([route, key]) => [route, window[key]]));
    const originalNavigate = window.apolloNavigate;
    let state = null, current = document.body.dataset.apolloRoute || 'home';
    let pending = null, stateAt = 0, lockBusy = false;
    const leaveRevocations = new Map();
    let refreshSequence = 0, routeSequence = 0, renderedSettingsKey = '';
    // Route markers are not credentials. Grants remain HttpOnly server-side cookies.
    const leftLocks = new Set((() => {
        try { return JSON.parse(sessionStorage.getItem('apollo-security-left-routes') || '[]'); }
        catch (_) { return []; }
    })());
    const rememberLeft = resource => {
        leftLocks.add(resource);
        try { sessionStorage.setItem('apollo-security-left-routes', JSON.stringify([...leftLocks])); } catch (_) {}
    };
    const forgetLeft = resource => {
        leftLocks.delete(resource);
        try { sessionStorage.setItem('apollo-security-left-routes', JSON.stringify([...leftLocks])); } catch (_) {}
    };
    const tabId = (() => {
        try { return [...globalThis.crypto.getRandomValues(new Uint8Array(16))]
            .map(value => value.toString(16).padStart(2, '0')).join(''); }
        catch (_) { return ''; }
    })();
    const presenceId = tabId || String(Math.random());
    const peers = new Map();
    const presence = typeof BroadcastChannel === 'function' ? new BroadcastChannel('apollo-security-presence') : null;
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
        <details id="apolloSecretMethods" class="apollo-security-methods">
            <summary id="apolloSecretSummary">Use a passphrase</summary>
            <label class="apollo-security-secret-label" for="apolloSecuritySecret">Passphrase</label>
            <input id="apolloSecuritySecret" type="password" autocomplete="current-password" placeholder="Enter passphrase" aria-label="Security passphrase">
            <button type="button" class="apollo-security-secondary" id="apolloPassphraseUnlock">Unlock with passphrase</button>
        </details>
        <button type="button" class="apollo-security-link" id="apolloRecoveryMode">Use a recovery code</button>
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
            cache: 'no-store', headers: {'Content-Type': 'application/json', 'X-Apollo-Request': 'security',
                'X-Apollo-Security-Tab': tabId},
            body: payload === undefined ? undefined : JSON.stringify(payload)
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(body.error || `Security request failed (${response.status})`);
            error.status = response.status;
            error.code = body.error;
            throw error;
        }
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
    const canShow = route => !protectedRoute(route) ||
        (!!state.unlocked?.[resourceFor(route)] && !leftLocks.has(resourceFor(route)));
    function announcePresence(resource = resourceFor(current)) {
        if (resource && state?.tabs?.[resource] === 'leave' && state.unlocked?.[resource] &&
                !pending && !leftLocks.has(resource)) {
            presence?.postMessage({kind:'present', resource, id:presenceId});
        }
    }
    if (presence) presence.onmessage = ({data}) => {
        if (!data || data.id === presenceId || !TABS_FOR_PRESENCE.has(data.resource)) return;
        if (data.kind === 'query') announcePresence(data.resource);
        if (data.kind === 'present') peers.set(data.id, {resource:data.resource, seen:Date.now()});
    };
    const TABS_FOR_PRESENCE = new Set(Object.values(resources));
    async function anotherTabUses(resource) {
        if (!presence) return false;
        presence.postMessage({kind:'query', resource, id:presenceId});
        await new Promise(resolve => setTimeout(resolve, 220));
        return [...peers.values()].some(peer => peer.resource === resource && Date.now() - peer.seen < 15000);
    }
    function conceal() { document.body.classList.add('apollo-security-conceal'); }
    function reveal() { document.body.classList.remove('apollo-security-conceal'); document.documentElement.classList.remove('apollo-security-pending'); }
    async function refresh() {
        const sequence = ++refreshSequence;
        const next = await request('state');
        if (sequence < refreshSequence) return state;
        const wasPrivateUnlocked = !!state?.unlocked?.private;
        const wasPrivateProtected = !!state?.protect_sensitive_chat;
        state = next;
        stateAt = Date.now();
        const historySearch = document.querySelector('#apolloHistorySearch');
        if (historySearch) {
            historySearch.disabled = !!(state.protect_history && !state.unlocked?.history);
            historySearch.placeholder = historySearch.disabled ? 'Unlock to search chats' : 'Search chats';
        }
        if (state.protect_sensitive_chat && !state.unlocked?.private &&
                (wasPrivateUnlocked || !wasPrivateProtected)) {
            window.apolloPulseClearPrivate?.();
        } else if (state.protect_sensitive_chat && state.unlocked?.private && !wasPrivateUnlocked) {
            window.apolloPulseUnlockRefresh?.();
        }
        if (state.protect_history && !state.unlocked?.history) {
            window.apolloClearHomeRecent?.();
            window.apolloClearJarvisHistory?.();
            document.querySelector('#apolloHistoryTrack')
                ?.querySelectorAll('.apollo-history-card, .apollo-history-group')
                .forEach(node => node.remove());
        }
        const key = JSON.stringify([state.enrolled, state.tabs, state.privacy,
            state.protect_spotify, state.protect_sensitive_chat, state.protect_history,
            state.private_relock, state.history_relock,
            state.unlocked?.settings, state.passkeys, state.recovery_available]);
        if (key !== renderedSettingsKey) {
            renderedSettingsKey = key;
            renderSettings();
        }
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
        secret.placeholder = 'Enter passphrase';
        secret.setAttribute('aria-label', 'Security passphrase');
        device.hidden = !(state?.passkeys > 0 && window.PublicKeyCredential && window.isSecureContext);
        lock.querySelector('#apolloSecretMethods').open = device.hidden;
        lock.querySelector('#apolloSecretSummary').textContent = 'Use a passphrase';
        lock.querySelector('.apollo-security-secret-label').textContent = 'Passphrase';
        lock.querySelector('#apolloPassphraseUnlock').textContent = 'Unlock with passphrase';
        lock.querySelector('#apolloPublicQuestion').hidden = route !== 'apollo';
        lock.querySelector('#apolloPublicAnswer').textContent = '';
        lock.querySelector('#apolloRecoveryMode').textContent = 'Use a recovery code';
        (device.hidden ? secret : device).focus({preventScroll: true});
    }
    function finishUnlock() {
        const target = pending;
        pending = null;
        if (target?.resource) forgetLeft(target.resource);
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
        announcePresence();
    }
    async function authenticate(method, value) {
        if (!pending || lockBusy) return;
        lockBusy = true;
        feedback.textContent = '';
        for (const button of lock.querySelectorAll('button')) button.disabled = true;
        try {
            await leaveRevocations.get(pending.resource);
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
    function passkeyFailure(error, action) {
        if (error?.name === 'NotAllowedError')
            return `Passkey ${action} did not complete. The prompt may have been dismissed, timed out, or blocked by this app’s permissions. Try again or use a passphrase.`;
        if (error?.name === 'SecurityError')
            return 'This app is not authorized to use passkeys for Apollo’s HTTPS domain. Use a passphrase or open Apollo in Safari.';
        if (error?.name === 'NotSupportedError' || error?.name === 'TypeError')
            return 'Passkeys are unavailable in this app or device context. Use a passphrase or open Apollo in Safari.';
        if (error?.name === 'InvalidStateError')
            return action === 'registration' ? 'This passkey is already registered on this device.'
                : 'The selected passkey cannot be used here. Try another passkey or use a passphrase.';
        if (error?.name === 'AbortError')
            return `Passkey ${action} was interrupted. Try again or use a passphrase.`;
        if (error?.status === 403 || error?.status === 409)
            return error.message || 'Apollo could not verify this passkey. Try again or use a passphrase.';
        return error?.message || `Passkey ${action} failed. Try again or use a passphrase.`;
    }
    async function passkey(resource) {
        const challenge = await request('passkey/authenticate/options', {resource});
        const publicKey = challenge.options;
        publicKey.challenge = decode(publicKey.challenge);
        publicKey.allowCredentials = (publicKey.allowCredentials || []).map(item => ({...item, id: decode(item.id)}));
        const credential = await navigator.credentials.get({publicKey});
        if (!credential) throw new Error('No passkey was returned by the device. Try again or use a passphrase.');
        await request('passkey/authenticate/finish', {challenge_id: challenge.challenge_id,
            credential: {id: credential.id, rawId: encode(credential.rawId), type: credential.type,
                response: {authenticatorData: encode(credential.response.authenticatorData),
                    clientDataJSON: encode(credential.response.clientDataJSON),
                    signature: encode(credential.response.signature),
                    userHandle: credential.response.userHandle ? encode(credential.response.userHandle) : null}}});
    }
    window.apolloSecurityUnlockInline = (resource, mount, signal) => new Promise((resolve, reject) => {
        if (!['private', 'history'].includes(resource) || !mount) {
            reject(new Error('Inline verification is unavailable'));
            return;
        }
        const old = mount.querySelector('.apollo-security-inline');
        old?.remove();
        const card = document.createElement('section');
        card.className = 'apollo-security-inline';
        card.setAttribute('role', 'group');
        card.setAttribute('aria-label', resource === 'history' ? 'Unlock History' : 'Verify private Chat access');
        const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        icon.setAttribute('viewBox', '0 0 24 24');
        icon.setAttribute('aria-hidden', 'true');
        icon.innerHTML = '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>';
        const title = document.createElement('h3');
        title.textContent = resource === 'history' ? 'Private history' : 'Private response';
        const description = document.createElement('p');
        description.textContent = resource === 'history'
            ? "Verify it's you to view your conversations."
            : "Verify it's you to reveal this information.";
        const passphrase = document.createElement('input');
        passphrase.type = 'password';
        passphrase.autocomplete = 'current-password';
        passphrase.placeholder = 'Passphrase';
        passphrase.setAttribute('aria-label', 'Security passphrase');
        const message = document.createElement('p');
        message.className = 'apollo-security-inline-feedback';
        message.setAttribute('role', 'status');
        const buttons = document.createElement('div');
        buttons.className = 'apollo-security-inline-actions';
        const confirm = document.createElement('button');
        confirm.type = 'button';
        confirm.textContent = 'Unlock with passphrase';
        const deviceButton = document.createElement('button');
        deviceButton.type = 'button';
        deviceButton.textContent = 'Unlock with passkey';
        deviceButton.hidden = !(state?.passkeys > 0 && window.PublicKeyCredential && window.isSecureContext);
        (deviceButton.hidden ? confirm : deviceButton).classList.add('is-primary');
        const recovery = document.createElement('button');
        recovery.type = 'button';
        recovery.textContent = 'Use recovery code';
        const cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.textContent = 'Cancel';
        buttons.append(deviceButton, confirm, recovery, cancel);
        card.append(icon, title, description, passphrase, buttons, message);
        mount.append(card);
        let done = false, recoveryMode = false;
        const finish = (error) => {
            if (done) return;
            done = true;
            card.remove();
            signal?.removeEventListener('abort', onAbort);
            if (error) reject(error); else resolve();
        };
        const onAbort = () => finish(new DOMException('Verification interrupted', 'AbortError'));
        signal?.addEventListener('abort', onAbort, {once: true});
        const verify = async method => {
            if (done) return;
            for (const button of buttons.querySelectorAll('button')) button.disabled = true;
            message.textContent = '';
            try {
                if (method === 'passkey') await passkey(resource);
                else await request('authenticate', method === 'recovery'
                    ? {resource, method, code: passphrase.value}
                    : {resource, method, passphrase: passphrase.value});
                passphrase.value = '';
                await refresh();
                if (!state.unlocked?.[resource]) throw new Error('Verification did not create an access grant');
                finish();
            } catch (error) {
                message.textContent = method === 'passkey' ? passkeyFailure(error, 'verification')
                    : error.message || 'Verification failed';
            } finally {
                for (const button of buttons.querySelectorAll('button')) button.disabled = false;
            }
        };
        confirm.onclick = () => verify(recoveryMode ? 'recovery' : 'passphrase');
        passphrase.onkeydown = event => { if (event.key === 'Enter') verify(recoveryMode ? 'recovery' : 'passphrase'); };
        deviceButton.onclick = () => verify('passkey');
        recovery.onclick = () => {
            recoveryMode = !recoveryMode;
            passphrase.value = '';
            passphrase.placeholder = recoveryMode ? 'Recovery code' : 'Passphrase';
            passphrase.setAttribute('aria-label', passphrase.placeholder);
            recovery.textContent = recoveryMode ? 'Use passphrase' : 'Use recovery code';
            passphrase.focus();
        };
        cancel.onclick = () => {
            const error = new Error('Verification canceled');
            error.name = 'SecurityVerificationCanceled';
            finish(error);
        };
        passphrase.focus({preventScroll: true});
    });
    window.apolloSecurityLockedInline = (mount, retry) => {
        if (!mount) return;
        mount.replaceChildren();
        const card = document.createElement('section');
        card.className = 'apollo-security-inline';
        card.setAttribute('role', 'group');
        card.setAttribute('aria-label', 'Private response remains locked');
        const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        icon.setAttribute('viewBox', '0 0 24 24');
        icon.setAttribute('aria-hidden', 'true');
        icon.innerHTML = '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>';
        const title = document.createElement('h3');
        title.textContent = 'Private response';
        const description = document.createElement('p');
        description.textContent = "This response remains locked. Verify when you're ready.";
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = 'Verify to continue';
        button.addEventListener('click', () => retry?.());
        card.append(icon, title, description, button);
        mount.append(card);
    };
    window.apolloSecurityHistoryClosed = () => {
        const track = document.querySelector('#apolloHistoryTrack');
        track?.querySelectorAll('.apollo-history-card, .apollo-history-group, .apollo-security-inline').forEach(node => node.remove());
        if (state?.history_relock === 'leave' && state.protect_history) {
            if (state.unlocked) state.unlocked.history = false;
            request('revoke', {resource: 'history'}).catch(error =>
                console.warn('[Apollo Security] History revocation failed:', error.message));
        }
    };
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
        } catch (error) { feedback.textContent = passkeyFailure(error, 'verification'); }
        finally { device.disabled = false; lockBusy = false; }
    });
    lock.querySelector('#apolloPassphraseUnlock').addEventListener('click', () => authenticate(recoveryMode ? 'recovery' : 'passphrase', secret.value));
    secret.addEventListener('keydown', event => {
        if (event.key === 'Enter') authenticate(recoveryMode ? 'recovery' : 'passphrase', secret.value);
    });
    lock.querySelector('#apolloRecoveryMode').addEventListener('click', event => {
        recoveryMode = !recoveryMode;
        secret.value = '';
        secret.placeholder = recoveryMode ? 'Enter recovery code' : 'Enter passphrase';
        secret.setAttribute('aria-label', recoveryMode ? 'Recovery code' : 'Security passphrase');
        lock.querySelector('.apollo-security-secret-label').textContent = recoveryMode ? 'Recovery code' : 'Passphrase';
        lock.querySelector('#apolloSecretSummary').textContent = recoveryMode ? 'Use a recovery code' : 'Use a passphrase';
        lock.querySelector('#apolloPassphraseUnlock').textContent = recoveryMode ? 'Unlock with recovery code' : 'Unlock with passphrase';
        lock.querySelector('#apolloSecretMethods').open = true;
        event.currentTarget.textContent = recoveryMode ? 'Use a passphrase' : 'Use a recovery code';
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
        const sequence = ++routeSequence;
        const fresh = state && Date.now() - stateAt <= 5000;
        if (!fresh) {
            document.body.classList.add('apollo-security-transition');
            conceal();
        }
        try {
            if (!fresh) await refresh();
            if (sequence !== routeSequence) return;
            const previous = resourceFor(current);
            if (previous === 'chat' && resourceFor(route) !== 'chat' &&
                    state.protect_sensitive_chat && state.private_relock === 'leave' &&
                    state.unlocked?.private) {
                state.unlocked.private = false;
                request('revoke', {resource: 'private'}).catch(error =>
                    console.warn('[Apollo Security] Private access revocation failed:', error.message));
            }
            if (previous && previous !== resourceFor(route) && state.tabs?.[previous] === 'leave') {
                // Invalidate this tab immediately. Server revocation can finish
                // after the destination is visible without exposing Studio.
                rememberLeft(previous);
                state.unlocked[previous] = false;
                const revokeLeaving = (async () => {
                    try {
                        if (!await anotherTabUses(previous)) await request('revoke', {resource: previous});
                    } catch (error) {
                        console.warn('[Apollo Security] Leave revocation failed:', error.message);
                    }
                })();
                leaveRevocations.set(previous, revokeLeaving);
                revokeLeaving.finally(() => {
                    if (leaveRevocations.get(previous) === revokeLeaving) leaveRevocations.delete(previous);
                });
            }
            if (sequence !== routeSequence) return;
            document.body.classList.remove('apollo-security-transition');
            if (!canShow(route)) { showLock(route); return; }
            pending = null;
            current = route;
            originalNavigate?.(route);
            reveal();
            announcePresence();
        } catch (error) {
            document.body.classList.remove('apollo-security-transition');
            showLock(route);
            feedback.textContent = error.message || 'Security state unavailable';
        }
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
        const sequence = routeSequence;
        refresh().then(() => {
            if (sequence !== routeSequence) return;
            if (pending) {
                if (!document.body.classList.contains('apollo-security-conceal')) showLock(pending.route, pending.resource);
            }
            else if (!canShow(current)) showLock(current);
            else { reveal(); announcePresence(); }
        }).catch(error => {
            if (sequence !== routeSequence) return;
            // Short network interruptions must not discard a still-valid server grant.
            if (!state || Date.now() - stateAt > 15000 || pending) {
                showLock(current);
                feedback.textContent = error.message || 'Security state unavailable';
            }
        });
    }
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) checkCurrent();
    });
    setInterval(() => { if (!document.hidden && (protectedRoute(current) || pending)) checkCurrent(); }, 5000);
    setInterval(() => {
        if (document.hidden || !state?.protect_history ||
                !document.querySelector('#apolloHistoryStrip.open')) return;
        refresh().then(() => {
            if (!state.unlocked?.history) {
                document.querySelector('#apolloHistoryTrack')
                    ?.querySelectorAll('.apollo-history-card, .apollo-history-group')
                    .forEach(node => node.remove());
                if (!document.querySelector('#apolloHistoryTrack .apollo-security-inline'))
                    window.apolloRefreshHistory?.();
            }
        }).catch(() => {});
    }, 5000);
    setInterval(() => {
        const resource = resourceFor(current);
        if (resource && state?.tabs?.[resource] === 'leave' && state.unlocked?.[resource] &&
                !pending && !leftLocks.has(resource)) {
            request('heartbeat', {resource}).catch(error => {
                if (error.status === 423) checkCurrent();
            });
            announcePresence(resource);
        }
    }, 10000);
    checkCurrent();

    const settings = document.querySelector('#settingsView .apollo-settings-inner');
    let settingsPanel;
    if (settings) {
        const section = document.createElement('section');
        section.className = 'apollo-settings-section';
        section.innerHTML = `<div class="apollo-settings-section-title">Privacy &amp; Security</div>
            <div class="apollo-settings-panel"><div class="apollo-security-settings" id="apolloSecuritySettings"></div></div>`;
        settings.append(section);
        settingsPanel = section.querySelector('#apolloSecuritySettings');
    }
    const labels = {chat:'Chat', music:'Music', calendar:'Calendar', tasks:'Tasks',
        routines:'Routines', debrief:'Daily Debrief', studio:'Studio', settings:'Settings & Security'};
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
        const overview = document.createElement('div');
        overview.className = 'apollo-security-group';
        overview.innerHTML = `<h3>Security overview</h3><p>Passphrase active · ${state.passkeys || 0} passkey${state.passkeys === 1 ? '' : 's'} enrolled${state.recovery_available == null ? '' : ` · ${state.recovery_available} recovery codes remaining`}</p>`;
        const verify = document.createElement('button');
        verify.type = 'button';
        verify.className = 'apollo-security-verify';
        verify.textContent = state.unlocked?.settings ? 'Verify again for changes' : 'Verify to manage security';
        verify.onclick = () => showLock('settings', 'settings');
        const scopeStatus = document.createElement('p');
        const statusText = scope => state.unlocked?.[scope]
            ? (state[scope + '_relock'] === 'leave' ? 'unlocked until you leave' :
                'unlocked until ' + new Date(state.scope_expires?.[scope] * 1000).toLocaleTimeString([], {hour:'numeric', minute:'2-digit'}))
            : 'locked';
        scopeStatus.textContent = 'Private Chat: ' + statusText('private') + ' · History: ' + statusText('history');
        overview.append(scopeStatus, verify);
        settingsPanel.append(overview);
        if (!state.unlocked?.settings) return;
        const form = document.createElement('form');
        form.innerHTML = `<section class="apollo-security-group apollo-security-tab-group">
                <h3>Tab Locks</h3>
                <p>Choose areas to protect. Relock on leave applies when you navigate away; timed locks expire after the selected elapsed time.</p>
                <fieldset><legend class="apollo-visually-hidden">Individual tab locks</legend></fieldset>
            </section>
            <section class="apollo-security-group apollo-security-privacy-group">
                <h3>Chat Privacy</h3>
                <label>Protect personal information in Chat
                <select name="privacy"><option value="standard">Standard</option>
                <option value="enhanced">Enhanced Privacy</option><option value="maximum">Maximum Privacy</option></select></label>
                <label><input type="checkbox" name="protect_spotify">Protect private Spotify history</label>
                <label><input type="checkbox" name="protect_sensitive_chat">Verify before private Chat answers</label>
                <label>Private Chat relock
                    <select name="private_relock"><option value="leave">On leave</option><option value="5m">5 minutes</option><option value="15m">15 minutes</option></select></label>
                <label><input type="checkbox" name="protect_history">Protect saved History and search</label>
                <label>History relock
                    <select name="history_relock"><option value="leave">On close</option><option value="5m">5 minutes</option><option value="15m">15 minutes</option></select></label>
                <button type="submit">Save security settings</button>
            </section>
            <section class="apollo-security-group apollo-security-credentials-group">
                <h3>Credentials &amp; Recovery</h3>
                <p>Changes to security settings require a recent verification. Keep your recovery codes somewhere private.</p>
                <button type="button" id="apolloRegisterPasskey">Add a passkey</button>
                <div id="apolloPasskeyList"></div>
                <fieldset><legend>Passphrase and recovery codes</legend>
                <input id="apolloCurrentPassphrase" type="password" autocomplete="current-password" placeholder="Current passphrase" aria-label="Current security passphrase">
                <input id="apolloNewPassphrase" type="password" autocomplete="new-password" placeholder="New passphrase (16+ characters)" aria-label="New security passphrase">
                <div class="apollo-security-row"><button type="button" id="apolloChangePassphrase">Change passphrase</button>
                <button type="button" id="apolloNewRecovery">New recovery codes</button></div>
                </fieldset>
            </section>
            <p class="apollo-security-message" role="status"></p>`;
        const fieldset = form.querySelector('.apollo-security-tab-group fieldset');
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
            duration.hidden = !check.checked;
            duration.setAttribute('aria-label', `${label} relock timing`);
            check.addEventListener('change', () => { duration.hidden = !check.checked; });
            row.append(check, text, duration); fieldset.append(row);
        }
        form.elements.privacy.value = state.privacy;
        form.elements.protect_spotify.checked = state.protect_spotify;
        form.elements.protect_sensitive_chat.checked = !!state.protect_sensitive_chat;
        form.elements.protect_history.checked = !!state.protect_history;
        form.elements.private_relock.value = state.private_relock || '5m';
        form.elements.history_relock.value = state.history_relock || '5m';
        const message = form.querySelector('.apollo-security-message');
        const settingsFailure = (error, passkeyAction) => {
            if (error.code === 'recent_verification_required') {
                message.textContent = 'Verify again, then repeat the change.';
                showLock('settings', 'settings');
            } else message.textContent = passkeyAction ? passkeyFailure(error, passkeyAction) : error.message;
        };
        form.onsubmit = async event => {
            event.preventDefault();
            const tabs = {};
            for (const check of form.querySelectorAll('input[data-resource]')) if (check.checked) {
                tabs[check.dataset.resource] = form.querySelector(`select[data-resource="${check.dataset.resource}"]`).value;
            }
            try {
                await request('policy', {tabs, privacy: form.elements.privacy.value,
                    protect_spotify: form.elements.protect_spotify.checked,
                    protect_sensitive_chat: form.elements.protect_sensitive_chat.checked,
                    protect_history: form.elements.protect_history.checked,
                    private_relock: form.elements.private_relock.value,
                    history_relock: form.elements.history_relock.value});
                await refresh(); routeTo(current);
            } catch (error) { settingsFailure(error); }
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
                if (!credential) throw new Error('No passkey was returned by the device. Try again or use a passphrase.');
                await request('passkey/register/finish', {challenge_id: challenge.challenge_id,
                    credential: {id: credential.id, rawId: encode(credential.rawId), type: credential.type,
                        response: {attestationObject: encode(credential.response.attestationObject),
                            clientDataJSON: encode(credential.response.clientDataJSON)}}});
                await refresh();
                settingsPanel.querySelector('.apollo-security-message').textContent = 'Passkey added.';
            } catch (error) { settingsFailure(error, 'registration'); }
        };
        form.querySelector('#apolloChangePassphrase').onclick = async () => {
            try {
                await request('passphrase/change', {
                    current_passphrase: form.querySelector('#apolloCurrentPassphrase').value,
                    new_passphrase: form.querySelector('#apolloNewPassphrase').value});
                await refresh();
                settingsPanel.querySelector('.apollo-security-message').textContent = 'Passphrase changed. Protected tabs require a new unlock.';
            } catch (error) { settingsFailure(error); }
        };
        form.querySelector('#apolloNewRecovery').onclick = async () => {
            try {
                const result = await request('recovery/regenerate', {
                    current_passphrase: form.querySelector('#apolloCurrentPassphrase').value});
                form.querySelector('#apolloCurrentPassphrase').value = '';
                const codes = document.createElement('p'); codes.className = 'apollo-security-codes';
                codes.textContent = `Save these new one-time codes offline. Earlier codes are invalid: ${result.recovery_codes.join('  ')}`;
                form.querySelector('#apolloPasskeyList').before(codes);
            } catch (error) { settingsFailure(error); }
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
                    catch (error) { settingsFailure(error); }
                };
                row.append(label, remove); list.append(row);
            }
        }).catch(settingsFailure);
    }
})();
