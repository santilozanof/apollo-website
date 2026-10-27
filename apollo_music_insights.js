/* Music history and recaps use persisted Spotify events, never playback polls. */
(() => {
  const view = document.getElementById('musicView');
  if (!view) return;
  const player = view.querySelector('.apollo-music-inner');
  const tabs = document.createElement('nav');
  tabs.className = 'apollo-music-tabs';
  tabs.setAttribute('aria-label', 'Music sections');
  tabs.innerHTML = '<button type="button" data-tab="player" aria-selected="true">Player</button><button type="button" data-tab="insights" aria-selected="false">Insights</button><button type="button" data-tab="recaps" aria-selected="false">Monthly recaps</button>';
  player.before(tabs);
  const pane = document.createElement('section');
  pane.className = 'apollo-music-data';
  pane.hidden = true;
  player.after(pane);

  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  function localMonth(date = new Date()) {
    const parts = new Intl.DateTimeFormat('en-US', {timeZone: zone, year: 'numeric', month: '2-digit'}).formatToParts(date);
    return `${parts.find(p => p.type === 'year').value}-${parts.find(p => p.type === 'month').value}`;
  }
  function previousMonth(month) {
    const [year, number] = month.split('-').map(Number);
    return number === 1 ? `${year - 1}-12` : `${year}-${String(number - 1).padStart(2, '0')}`;
  }
  const state = {tab: 'player', month: localMonth(), summary: null, recap: null, slide: 0, format: 'story', renderId: 0};
  const text = (tag, value, className) => {
    const node = document.createElement(tag);
    node.textContent = value;
    if (className) node.className = className;
    return node;
  };
  async function request(url, options = {}) {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
  }
  function safeArt(url) { return typeof url === 'string' && /^https:\/\/i\.scdn\.co\/image\//.test(url); }
  function safeSpotify(url) { return typeof url === 'string' && /^https:\/\/open\.spotify\.com\/(track|album|artist)\/[A-Za-z0-9]+$/.test(url); }
  function spotifyAttribution() {
    const anchor = document.createElement('a');
    anchor.href = 'https://open.spotify.com';
    anchor.target = '_blank'; anchor.rel = 'noopener noreferrer';
    anchor.className = 'spotify-attribution';
    anchor.setAttribute('aria-label', 'Open Spotify');
    for (const color of ['black', 'white']) {
      const logo = document.createElement('img');
      logo.src = `/vendor/spotify/full-logo-${color}.svg`;
      logo.alt = color === 'black' ? 'Spotify' : '';
      logo.className = `spotify-logo-${color}`;
      anchor.append(logo);
    }
    return anchor;
  }
  const playerAttribution = spotifyAttribution();
  playerAttribution.classList.add('spotify-player-attribution');
  player.append(playerAttribution);
  function monthLabel(month) {
    const [year, number] = month.split('-').map(Number);
    return new Intl.DateTimeFormat('en', {month: 'long', year: 'numeric'}).format(new Date(year, number - 1, 1));
  }
  function duration(ms) {
    const minutes = Math.round(ms / 60000);
    return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes} min`;
  }
  function initialDay() {
    return new Intl.DateTimeFormat('sv-SE', {timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
  }
  state.period = 'monthly';
  state.anchor = initialDay();
  state.expanded = null;
  state.metric = 'plays';
  state.search = '';
  state.offset = 0;
  function params(extra = {}) {
    return new URLSearchParams({period: state.period, anchor: state.anchor, timezone: zone, ...extra});
  }
  function periodStep(direction) {
    const [y, m, d] = state.anchor.split('-').map(Number);
    const date = new Date(Date.UTC(y, m - 1, d));
    if (state.period === 'daily') date.setUTCDate(date.getUTCDate() + direction);
    if (state.period === 'weekly') date.setUTCDate(date.getUTCDate() + direction * 7);
    if (state.period === 'monthly') { date.setUTCDate(1); date.setUTCMonth(date.getUTCMonth() + direction); }
    if (state.period === 'yearly') { date.setUTCMonth(0, 1); date.setUTCFullYear(date.getUTCFullYear() + direction); }
    const next = date.toISOString().slice(0, 10);
    if (next <= initialDay()) state.anchor = next;
  }
  function imageOrMonogram(row, entity) {
    const wrapper = text('span', '', `music-art music-art-${entity}`);
    if (safeArt(row.image_url || row.artwork_url)) {
      const img = document.createElement('img'); img.src = row.image_url || row.artwork_url;
      img.alt = entity === 'artists' ? `${row.name} artist portrait` : `${row.name || row.track_name} album artwork`;
      img.loading = 'lazy';
      img.onerror = () => { img.remove(); wrapper.textContent = (row.name || row.track_name || '♪').slice(0, 1).toUpperCase(); };
      wrapper.append(img);
    } else wrapper.textContent = (row.name || row.track_name || '♪').slice(0, 1).toUpperCase();
    return wrapper;
  }
  function timeLabel(row) {
    if (row.verified_events) return `${duration(row.verified_ms)} verified`;
    if (row.estimated_ms) return `${duration(row.estimated_ms)} estimated`;
    return 'Time unavailable';
  }
  function spotifyLink(row, label = 'Open on Spotify') {
    if (!safeSpotify(row.spotify_url)) return null;
    const link = text('a', label, 'spotify-source-link');
    link.href = row.spotify_url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    return link;
  }
  function musicRow(row, entity, index, onOpen) {
    const line = text('div', '', 'ranked-row music-explorer-row');
    if (index != null) line.append(text('span', String(index).padStart(2, '0'), 'number'));
    line.append(imageOrMonogram(row, entity));
    const body = text('div', '', 'music-row-body');
    const title = text('button', row.name || row.track_name, 'music-row-title'); title.type = 'button';
    title.addEventListener('click', onOpen); body.append(title);
    if (row.artist_name && entity !== 'artists') body.append(text('small', row.artist_name));
    line.append(body);
    const measure = text('div', '', 'music-row-measure');
    measure.append(text('strong', `${row.plays} ${row.plays === 1 ? 'play' : 'plays'}`), text('small', timeLabel(row)));
    line.append(measure);
    const source = spotifyLink(row, '↗'); if (source) { source.setAttribute('aria-label', `Open ${row.name} on Spotify`); line.append(source); }
    return line;
  }
  function heading(title, month, recap = false) {
    const top = text('header', '', 'topline music-heading');
    const left = text('div', '', 'music-heading-copy');
    left.append(text('div', 'APOLLO / MUSIC', 'eyebrow'), text('h2', title));
    top.append(left);
    if (recap) {
      const nav = text('div', '', 'music-period-nav');
      const back = text('button', '‹', 'music-period-arrow'); back.type = 'button'; back.setAttribute('aria-label', 'Previous month');
      back.onclick = () => { state.month = previousMonth(state.month); loadRecap(); };
      const picker = text('button', monthLabel(month), 'music-period-label'); picker.type = 'button';
      picker.setAttribute('aria-label', 'Choose recap month');
      picker.onclick = () => showMonthPicker(nav, picker, true);
      const next = text('button', '›', 'music-period-arrow'); next.type = 'button'; next.setAttribute('aria-label', 'Next month');
      next.disabled = month >= previousMonth(localMonth());
      next.onclick = () => { const [y, m] = state.month.split('-').map(Number); state.month = m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`; loadRecap(); };
      nav.append(back, picker, next); top.append(nav);
    }
    return top;
  }
  function showMonthPicker(container, trigger, recap = false) {
    container.querySelector('.music-month-popover')?.remove();
    const pop = text('div', '', 'music-month-popover');
    const year = recap ? Number(state.month.slice(0, 4)) : Number(state.anchor.slice(0, 4));
    const yearNav = text('div', '', 'music-picker-year');
    const previous = text('button', '‹'); previous.setAttribute('aria-label', 'Previous year'); previous.onclick = () => { if (recap) state.month = `${year - 1}-${state.month.slice(5)}`; else state.anchor = `${year - 1}${state.anchor.slice(4)}`; showMonthPicker(container, trigger, recap); };
    const current = text('strong', String(year));
    const next = text('button', '›'); next.setAttribute('aria-label', 'Next year'); next.disabled = year >= Number(initialDay().slice(0, 4)); next.onclick = () => { if (recap) state.month = `${year + 1}-${state.month.slice(5)}`; else state.anchor = `${year + 1}${state.anchor.slice(4)}`; showMonthPicker(container, trigger, recap); };
    yearNav.append(previous, current, next); pop.append(yearNav);
    const grid = text('div', '', 'music-picker-grid');
    for (let m = 1; m <= 12; m++) {
      const month = `${year}-${String(m).padStart(2, '0')}`;
      const button = text('button', new Intl.DateTimeFormat('en', {month: 'short'}).format(new Date(year, m - 1, 1)));
      button.disabled = month > (recap ? previousMonth(localMonth()) : localMonth());
      button.setAttribute('aria-current', String(month === (recap ? state.month : state.anchor.slice(0, 7))));
      button.onclick = () => { if (recap) { state.month = month; loadRecap(); } else { state.anchor = `${month}-01`; loadInsights(); } };
      grid.append(button);
    }
    pop.append(grid); container.append(pop); pop.querySelector('button')?.focus();
    pop.addEventListener('keydown', event => { if (event.key === 'Escape') { pop.remove(); trigger.focus(); } });
  }
  function selector(summary) {
    const wrapper = text('div', '', 'music-period-controls');
    const tabs = text('div', '', 'music-period-tabs'); tabs.setAttribute('role', 'group'); tabs.setAttribute('aria-label', 'Listening time frame');
    for (const kind of ['daily', 'weekly', 'monthly', 'yearly', 'lifetime']) {
      const button = text('button', kind[0].toUpperCase() + kind.slice(1)); button.type = 'button';
      button.setAttribute('aria-pressed', String(state.period === kind));
      button.onclick = () => { state.period = kind; state.expanded = null; loadInsights(); };
      tabs.append(button);
    }
    wrapper.append(tabs);
    if (state.period !== 'lifetime') {
      const nav = text('div', '', 'music-period-nav');
      const back = text('button', '‹', 'music-period-arrow'); back.type = 'button'; back.setAttribute('aria-label', 'Previous period'); back.onclick = () => { periodStep(-1); loadInsights(); };
      const label = text('button', summary.period.label, 'music-period-label'); label.type = 'button';
      label.setAttribute('aria-label', 'Choose listening period');
      label.onclick = () => {
        if (state.period === 'monthly') showMonthPicker(nav, label);
        else if (state.period === 'daily' || state.period === 'weekly') { const input = nav.querySelector('input') || document.createElement('input'); input.type = 'date'; input.max = initialDay(); input.value = state.anchor; input.setAttribute('aria-label', 'Choose date'); input.onchange = () => { if (input.value && input.value <= initialDay()) { state.anchor = input.value; loadInsights(); } }; nav.append(input); input.showPicker?.(); input.focus(); }
        else { const input = nav.querySelector('input') || document.createElement('input'); input.type = 'number'; input.min = '1970'; input.max = initialDay().slice(0, 4); input.value = state.anchor.slice(0, 4); input.setAttribute('aria-label', 'Choose year'); input.onchange = () => { const year = Number(input.value); if (year >= 1970 && year <= Number(input.max)) { state.anchor = `${year}-01-01`; loadInsights(); } }; nav.append(input); input.focus(); }
      };
      const next = text('button', '›', 'music-period-arrow'); next.type = 'button'; next.setAttribute('aria-label', 'Next period'); next.disabled = !summary.period.can_next; next.onclick = () => { periodStep(1); loadInsights(); };
      nav.append(back, label, next); wrapper.append(nav);
    } else wrapper.append(text('div', summary.coverage.earliest_event ? `Available history since ${new Date(summary.coverage.earliest_event).toLocaleDateString()}` : 'No recorded history yet', 'music-period-coverage'));
    return wrapper;
  }
  function stat(label, value, note) {
    const card = text('div', '', 'stat'); card.append(text('div', label, 'eyebrow'), text('strong', value), text('span', note)); return card;
  }
  function rankPanel(title, entity, rows) {
    const panel = text('section', '', 'panel music-ranking');
    const header = text('div', '', 'music-panel-head'); header.append(text('h3', title));
    const all = text('button', `View all ${entity}`, 'music-text-action'); all.type = 'button'; all.onclick = () => { state.returnScroll = view.scrollTop; state.expanded = entity; state.search = ''; state.offset = 0; loadExpanded(); view.scrollTop = 0; }; header.append(all); panel.append(header);
    const list = text('div', '', 'ranked');
    if (!rows.length) list.append(text('p', 'No recorded activity in this period.', 'muted'));
    rows.forEach((row, index) => list.append(musicRow(row, entity, index + 1, () => loadDetail(entity, row.entity_key))));
    panel.append(list); return panel;
  }
  function chart(summary) {
    const panel = text('section', '', 'panel music-chart-panel');
    panel.append(text('h3', summary.period.kind === 'daily' ? 'By hour' : summary.period.kind === 'weekly' ? 'This week' : summary.period.kind === 'monthly' ? 'By day' : summary.period.kind === 'yearly' ? 'By month' : 'Across the years'));
    const bars = text('div', '', 'music-chart'); bars.setAttribute('role', 'img');
    bars.setAttribute('aria-label', summary.chart.map(item => `${item.label}: ${item.plays} plays`).join(', '));
    const peak = Math.max(1, ...summary.chart.map(item => item.plays));
    summary.chart.forEach((item, index) => { const bar = text('span', '', item.plays === peak && item.plays ? 'peak' : ''); bar.style.height = `${Math.max(2, item.plays / peak * 100)}%`; bar.title = `${item.label}: ${item.plays} plays`; if (index % Math.max(1, Math.ceil(summary.chart.length / 7)) === 0) bar.dataset.label = item.label; bars.append(bar); });
    panel.append(bars);
    if (summary.insights?.length) summary.insights.slice(0, 3).forEach(finding => panel.append(text('p', finding, 'muted method')));
    return panel;
  }
  async function loadInsights() {
    state.expanded = null;
    if (state.period === 'monthly') state.month = state.anchor.slice(0, 7);
    pane.replaceChildren(heading('Listening insights'), text('p', 'Loading listening history…', 'muted'));
    try {
      const summary = await request(`/api/music/analytics?${params()}`);
      if (state.tab !== 'insights' || summary.period.kind !== state.period || summary.period.anchor !== state.anchor) return;
      state.summary = summary;
      pane.replaceChildren(heading('Listening insights'), selector(summary));
      const coverage = summary.coverage;
      const status = text('div', '', 'statusline music-status');
      status.append(text('span', coverage.syncing ? 'Spotify syncing…' : coverage.last_sync_at ? `Spotify updated ${new Date(coverage.last_sync_at).toLocaleString()}` : 'Spotify history not yet synchronized'));
      if (coverage.sync_error || coverage.coverage_warning) status.append(text('span', coverage.sync_error || coverage.coverage_warning, 'music-status-warning'));
      status.append(spotifyAttribution());
      const menu = text('details', '', 'music-sync-menu'); const summaryButton = text('summary', '···'); summaryButton.setAttribute('aria-label', 'Music history options'); menu.append(summaryButton);
      const sync = text('button', 'Sync now'); sync.type = 'button'; sync.onclick = async () => { sync.disabled = true; try { await request('/api/music/history/sync', {method: 'POST', headers: {'X-Apollo-Request': 'music'}}); status.append(text('span', 'Sync started')); } catch (error) { status.append(text('span', error.message)); } finally { sync.disabled = false; menu.open = false; } }; menu.append(sync); status.append(menu); pane.append(status);
      const stats = text('div', '', 'stats');
      const timeValue = summary.verified_ms ? duration(summary.verified_ms) : summary.estimated_ms ? duration(summary.estimated_ms) : 'Unavailable';
      const timeNote = summary.verified_ms ? `${summary.estimated_ms ? `+ ${duration(summary.estimated_ms)} estimated · ` : ''}${summary.duration_unknown_events} plays without verified duration` : summary.estimated_ms ? 'Estimated from observed playback; verified time available after import' : 'Import official history for verified listening time';
      stats.append(stat(summary.verified_ms ? 'Verified listening' : summary.estimated_ms ? 'Estimated listening' : 'Listening time', timeValue, timeNote), stat('Recorded plays', summary.events.toLocaleString(), 'Events in available history'), stat('Artists', summary.unique_artists.toLocaleString(), 'Credited in recorded plays'));
      pane.append(stats);
      if (!summary.events) pane.append(text('p', 'No recorded plays in this period. Choose another period or import your Spotify history below.', 'empty'));
      else { const grid = text('div', '', 'grid'); grid.append(rankPanel('Top artists', 'artists', summary.top.artists), rankPanel('Top songs', 'tracks', summary.top.tracks), rankPanel('Top albums', 'albums', summary.top.albums), chart(summary)); pane.append(grid); }
      const recent = text('section', '', 'panel music-recent');
      const recentHead = text('div', '', 'music-panel-head'); recentHead.append(text('h3', 'Recently played'));
      const allRecent = text('button', 'View all history', 'music-text-action'); allRecent.type = 'button'; allRecent.onclick = () => { state.returnScroll = view.scrollTop; state.expanded = 'history'; state.search = ''; state.offset = 0; loadExpanded(); view.scrollTop = 0; }; recentHead.append(allRecent); recent.append(recentHead);
      const history = await request(`/api/music/history?${params({limit: 6})}`);
      const list = text('div', '', 'recent-list');
      history.items.forEach(item => { const row = text('div', '', 'recent-row'); row.append(imageOrMonogram({...item, name: item.track_name}, 'tracks')); const body = text('div', '', 'recent-identity'); const title = text('button', item.track_name, 'music-row-title'); title.onclick = () => loadDetail('tracks', item.track_key); body.append(title, text('span', item.artist_name)); row.append(body); const link = spotifyLink(item, '↗'); if (link) row.append(link); const date = new Date(item.event_at); row.append(text('time', date.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}), 'muted')); list.append(row); });
      if (!history.items.length) list.append(text('p', 'Nothing recorded in this period.', 'muted')); recent.append(list); pane.append(recent);
      const importBox = text('section', '', 'panel music-import'); importBox.append(text('h3', 'Complete your listening history'), text('p', 'Import official Spotify StreamingHistory or Extended Streaming History JSON files. Files stay on Apollo; duplicates are skipped. Extended exports can add verified listening time.', 'muted'));
      const row = text('div', '', 'import'); const input = document.createElement('input'); input.type = 'file'; input.accept = '.json,application/json'; input.multiple = true; input.setAttribute('aria-label', 'Select Spotify listening history JSON files');
      const progress = text('div', '', 'muted import-progress'); progress.setAttribute('role', 'status');
      input.onchange = async () => { const results = []; for (const file of input.files || []) { if (file.size > 16 * 1024 * 1024) { results.push(`${file.name}: exceeds 16 MB`); continue; } progress.textContent = `Importing ${file.name}…`; try { const result = await upload(file, fraction => { progress.textContent = `Importing ${file.name}: ${Math.round(fraction * 100)}%`; }); const range = result.first_event_at && result.last_event_at ? ` · ${new Date(result.first_event_at).toLocaleDateString()}–${new Date(result.last_event_at).toLocaleDateString()}` : ''; results.push(`${file.name}: ${result.imported} new, ${result.duplicates} duplicates${range}`); } catch (error) { results.push(`${file.name}: ${error.message}`); } } progress.textContent = results.join('\n'); input.value = ''; setTimeout(() => { if (state.tab === 'insights') loadInsights(); }, 3500); };
      row.append(input, progress); importBox.append(row);
      const imports = await request('/api/music/imports').catch(() => ({imports: []}));
      if (imports.imports?.length) importBox.append(text('p', `${imports.imports.length} recent import file${imports.imports.length === 1 ? '' : 's'} · earliest imported ${imports.imports.at(-1).first_event_at ? new Date(imports.imports.at(-1).first_event_at).toLocaleDateString() : 'unknown'}`, 'muted method'));
      importBox.append(text('p', `Coverage: ${coverage.earliest_event ? new Date(coverage.earliest_event).toLocaleDateString() : 'no events'} to ${coverage.latest_event ? new Date(coverage.latest_event).toLocaleDateString() : 'now'} · ${coverage.import_files} official import files. ${summary.methodology}`, 'muted method'));
      pane.append(importBox);
    } catch (error) { pane.replaceChildren(heading('Listening insights'), text('p', error.message || 'Music history could not load.', 'empty')); }
  }
  async function loadExpanded() {
    const entity = state.expanded; const offset = state.offset; const query = entity === 'history' ? `/api/music/history?${params({search: state.search, offset, limit: 30})}` : `/api/music/rankings?${params({entity, metric: state.metric, search: state.search, offset, limit: 30})}`;
    pane.replaceChildren();
    const header = heading(entity === 'history' ? 'Listening history' : `All ${entity}`);
    const back = text('button', '← Insights', 'music-text-action'); back.type = 'button'; back.onclick = () => { state.expanded = null; loadInsights().then(() => { view.scrollTop = state.returnScroll || 0; }); }; header.append(back); pane.append(header);
    const controls = text('div', '', 'music-explorer-controls');
    const search = document.createElement('input'); search.type = 'search'; search.value = state.search; search.placeholder = 'Search your history'; search.setAttribute('aria-label', 'Search recorded music');
    let timer; search.oninput = () => { clearTimeout(timer); timer = setTimeout(() => { state.search = search.value; state.offset = 0; loadExpanded().then(() => pane.querySelector('input[type=search]')?.focus()); }, 350); }; controls.append(search);
    if (entity !== 'history') { const metric = document.createElement('select'); metric.setAttribute('aria-label', 'Ranking metric'); [['plays','Recorded plays'],['verified','Verified time'],['estimated','Estimated time']].forEach(([value,label]) => { const option = new Option(label, value); metric.append(option); }); metric.value = state.metric; metric.onchange = () => { state.metric = metric.value; state.offset = 0; loadExpanded(); }; controls.append(metric); } pane.append(controls);
    try { const data = await request(query); if (state.expanded !== entity || state.offset !== offset) return;
      const status = text('p', `${data.total} ${entity === 'history' ? 'recorded events' : `ranked ${entity}`} · ${data.period.label}`, 'muted method'); pane.append(status);
      if (entity !== 'history' && !data.metric_available) pane.append(text('p', `No ${state.metric} listening measurements are available in this period. Entries remain ordered by recorded plays.`, 'muted method'));
      const list = text('div', '', 'music-expanded-list');
      if (entity === 'history') data.items.forEach(item => { const row = text('div', '', 'recent-row'); row.append(imageOrMonogram({...item,name:item.track_name}, 'tracks')); const body = text('div', '', 'recent-identity'); const title = text('button', item.track_name, 'music-row-title'); title.onclick = () => loadDetail('tracks', item.track_key); body.append(title,text('span',item.artist_name)); row.append(body); const source = spotifyLink(item, '↗'); if (source) row.append(source); row.append(text('time', new Date(item.event_at).toLocaleString(), 'muted')); list.append(row); });
      else data.items.forEach(item => list.append(musicRow(item, entity, item.rank, () => loadDetail(entity, item.entity_key))));
      if (!data.items.length) list.append(text('p', 'No matches in this period.', 'empty')); pane.append(list);
      const pager = text('div', '', 'music-pager'); const previous = text('button', 'Previous'); previous.disabled = offset === 0; previous.onclick = () => { state.offset = Math.max(0, offset - 30); loadExpanded(); }; const next = text('button', 'Next'); next.disabled = offset + data.items.length >= data.total; next.onclick = () => { state.offset = offset + 30; loadExpanded(); }; pager.append(previous, text('span', `${Math.min(offset + 1, data.total)}–${Math.min(offset + data.items.length, data.total)} of ${data.total}`, 'muted'), next); pane.append(pager);
    } catch (error) { pane.append(text('p', error.message, 'empty')); }
  }
  async function loadDetail(entity, key) {
    if (!state.expanded) state.returnScroll = view.scrollTop;
    const prior = state.expanded; state.expanded = 'detail';
    pane.replaceChildren(heading('Listening detail'), text('p', 'Loading detail…', 'muted'));
    try { const data = await request(`/api/music/detail?${params({entity, key})}`); if (state.expanded !== 'detail') return;
      const back = text('button', prior && prior !== 'detail' ? `← All ${prior}` : '← Insights', 'music-text-action'); back.onclick = () => { state.expanded = prior && prior !== 'detail' ? prior : null; if (state.expanded) loadExpanded(); else loadInsights().then(() => { view.scrollTop = state.returnScroll || 0; }); };
      pane.replaceChildren(back); const hero = text('section', '', 'panel music-detail-hero'); hero.append(imageOrMonogram(data.item, entity)); const copy = text('div', '', 'music-detail-copy'); copy.append(text('div', entity.slice(0,-1).toUpperCase(), 'eyebrow'), text('h2', data.item.name)); if (data.item.artist_name) copy.append(text('p', data.item.artist_name, 'muted')); const link = spotifyLink(data.item); if (link) copy.append(link); hero.append(copy); pane.append(hero);
      const stats = text('div', '', 'stats'); stats.append(stat('Recorded plays', data.item.plays, `#${data.item.rank} in selected period`), stat('Verified listening', data.item.verified_events ? duration(data.item.verified_ms) : 'Unavailable', `${data.item.verified_events} plays with measured duration`), stat('Estimated listening', data.item.estimated_ms ? duration(data.item.estimated_ms) : 'Unavailable', 'Observed intervals, excluding verified overlap')); pane.append(stats);
      const info = text('section', '', 'panel'); info.append(text('h3', 'In your history'), text('p', `First recorded: ${new Date(data.item.first_at).toLocaleString()} · Most recent: ${new Date(data.item.last_at).toLocaleString()}. Lifetime available history: ${data.lifetime?.plays || 0} recorded plays.`, 'muted'));
      if (data.songs.length && entity !== 'tracks') { info.append(text('h3', 'Top songs')); data.songs.forEach(song => info.append(text('p', `${song.name} · ${song.plays} plays`, 'music-detail-line'))); }
      if (data.albums.length && entity === 'artists') { info.append(text('h3', 'Albums in your history')); data.albums.forEach(album => info.append(text('p', `${album.name} · ${album.plays} plays`, 'music-detail-line'))); }
      info.append(text('h3', 'Listening activity')); const activity = text('div', '', 'music-detail-activity'); data.activity.forEach(day => { const item = text('span', '', ''); item.title = `${day.day}: ${day.plays} plays`; item.style.opacity = String(Math.min(1, .2 + day.plays / 5)); activity.append(item); }); info.append(activity); pane.append(info);
    } catch (error) { pane.replaceChildren(text('p', error.message, 'empty')); }
  }
  function upload(file, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/music/history/import');
      xhr.setRequestHeader('Content-Type', 'application/json');
      xhr.setRequestHeader('X-Apollo-Request', 'music');
      xhr.setRequestHeader('X-File-Name', encodeURIComponent(file.name));
      xhr.upload.onprogress = event => { if (event.lengthComputable) onProgress(event.loaded / event.total); };
      xhr.onload = () => {
        let data;
        try { data = JSON.parse(xhr.responseText); } catch (_) { reject(new Error('Invalid server response')); return; }
        xhr.status >= 200 && xhr.status < 300 ? resolve(data) : reject(new Error(data.error || 'Import failed'));
      };
      xhr.onerror = () => reject(new Error('Network error during import'));
      xhr.send(file);
    });
  }
  const artworkCache = new Map();
  async function artImage(url) {
    if (!safeArt(url)) return null;
    if (!artworkCache.has(url)) artworkCache.set(url, (async () => {
      const image = new Image();
      image.crossOrigin = 'anonymous';
      image.src = url;
      try { await image.decode(); return image; } catch (_) { return null; }
    })());
    return artworkCache.get(url);
  }
  const brandCache = new Map();
  async function brandImage(dark) {
    const color = dark ? 'white' : 'black';
    if (!brandCache.has(color)) brandCache.set(color, (async () => {
      const image = new Image();
      image.src = `/vendor/spotify/full-logo-${color}.svg`;
      try { await image.decode(); return image; } catch (_) { return null; }
    })());
    return brandCache.get(color);
  }
  function fitted(ctx, value, x, y, maxWidth, size, weight = 600) {
    ctx.font = `${weight} ${size}px system-ui, -apple-system, sans-serif`;
    let content = String(value || '—');
    while (ctx.measureText(content).width > maxWidth && content.length > 2) content = content.slice(0, -2) + '…';
    ctx.fillText(content, x, y);
  }
  async function renderRecap(canvas) {
    const token = ++state.renderId;
    const summary = state.recap;
    if (!summary) return;
    const square = state.format === 'square';
    canvas.width = 1080; canvas.height = square ? 1080 : 1920;
    const ctx = canvas.getContext('2d');
    const h = canvas.height;
    ctx.fillStyle = state.slide === 0 ? '#eeeae2' : state.slide === 1 ? '#151719' : '#dce2d3';
    ctx.fillRect(0, 0, 1080, h);
    const dark = state.slide === 1;
    ctx.fillStyle = dark ? '#f1eee8' : '#131518';
    const side = 82;
    ctx.font = '700 30px system-ui, sans-serif';
    ctx.letterSpacing = '8px';
    ctx.fillText('APOLLO / MUSIC', side, 105);
    ctx.letterSpacing = '0px';
    ctx.fillRect(side, 130, 916, 2);
    const month = monthLabel(summary.month).toUpperCase();
    fitted(ctx, month, side, 200, 916, 38, 650);
    if (state.slide === 0) {
      ctx.font = `700 ${square ? 108 : 145}px system-ui, sans-serif`;
      ctx.fillText('IN', side - 7, square ? 350 : 390);
      ctx.fillText('ROTATION', side - 7, square ? 465 : 535);
      const artwork = summary.top_albums.find(item => safeArt(item.artwork_url) && safeSpotify(item.spotify_url))?.artwork_url;
      const image = await artImage(artwork);
      if (token !== state.renderId) return;
      const boxY = square ? 515 : 625;
      const boxSize = square ? 350 : 850;
      ctx.fillStyle = '#ccc8c0'; ctx.fillRect(side, boxY, boxSize, boxSize);
      if (image) {
        const ratio = Math.min(boxSize / image.width, boxSize / image.height);
        const width = image.width * ratio, height = image.height * ratio;
        const imageX = side + (boxSize - width) / 2, imageY = boxY + (boxSize - height) / 2;
        ctx.save();
        ctx.beginPath();
        ctx.roundRect(imageX, imageY, width, height, 8);
        ctx.clip();
        ctx.drawImage(image, imageX, imageY, width, height);
        ctx.restore();
      } else {
        ctx.fillStyle = '#151719'; ctx.fillRect(side, boxY, boxSize, boxSize);
        ctx.fillStyle = '#f1eee8';
        const names = summary.top_artists.slice(0, 3);
        names.forEach((item, index) => fitted(ctx, item.name.toUpperCase(), side + 35, boxY + 115 + index * (boxSize / 3.5), boxSize - 70, square ? 32 : 68, 700));
        if (!names.length) fitted(ctx, 'NO RECORDED PLAYS', side + 35, boxY + boxSize / 2, boxSize - 70, 55, 700);
      }
      const detailsX = square ? 485 : side;
      const detailsY = square ? 610 : 1590;
      ctx.fillStyle = '#131518';
      ctx.font = '600 28px system-ui'; ctx.fillText('01 / MOST PLAYED ARTIST', detailsX, detailsY);
      fitted(ctx, summary.top_artists[0]?.name || 'No recorded plays', detailsX, detailsY + 65, square ? 500 : 916, square ? 44 : 64, 700);
      ctx.font = '500 27px system-ui';
      ctx.fillText(`${summary.events} recorded plays`, detailsX, detailsY + 115);
      ctx.fillText(summary.duration_known_events ? `${duration(summary.verified_ms)} verified listening` : 'Listening time unavailable', detailsX, detailsY + 155);
    } else if (state.slide === 1) {
      ctx.font = `700 ${square ? 95 : 145}px system-ui, sans-serif`;
      ctx.fillText('THE', side - 7, square ? 345 : 385);
      ctx.fillText('TOP FIVE', side - 7, square ? 455 : 530);
      const top = summary.top_tracks.slice(0, 5);
      const start = square ? 555 : 670;
      const spacing = square ? 92 : 185;
      top.forEach((item, index) => {
        const y = start + index * spacing;
        ctx.fillStyle = '#62676b'; ctx.font = '700 34px system-ui';
        ctx.fillText(String(index + 1).padStart(2, '0'), side, y);
        ctx.fillStyle = '#f1eee8';
        fitted(ctx, item.name, side + 85, y, 770, square ? 34 : 48, 650);
        ctx.fillStyle = '#3d4348'; ctx.fillRect(side, y + 25, 916, 1);
      });
      if (!top.length) { ctx.font = '500 35px system-ui'; ctx.fillText('No recorded songs this month.', side, start); }
    } else {
      ctx.font = `700 ${square ? 93 : 143}px system-ui, sans-serif`;
      ctx.fillText('NEW', side - 7, square ? 335 : 390);
      ctx.fillText('FREQUENCIES', side - 7, square ? 430 : 535);
      ctx.fillStyle = '#173b32';
      ctx.font = `700 ${square ? 126 : 235}px system-ui, sans-serif`;
      ctx.fillText(String(summary.unique_artists), side - 7, square ? 570 : 820);
      ctx.fillStyle = '#293a34';
      ctx.font = '600 26px system-ui, sans-serif';
      ctx.fillText('ARTISTS IN ROTATION', side, square ? 610 : 875);
      const albums = summary.top_albums.slice(0, square ? 2 : 3);
      const listTop = square ? 770 : 1120;
      ctx.fillStyle = '#173b32';
      ctx.fillRect(side, listTop - 130, 916, 2);
      ctx.font = '700 28px system-ui, sans-serif';
      ctx.fillText('MOST PLAYED ALBUMS', side, listTop - 80);
      albums.forEach((album, index) => {
        const y = listTop + index * (square ? 80 : 130);
        ctx.fillStyle = '#6e8075';
        ctx.font = '700 27px system-ui, sans-serif';
        ctx.fillText(String(index + 1).padStart(2, '0'), side, y);
        ctx.fillStyle = '#131518';
        fitted(ctx, album.name, side + 70, y, 845, square ? 34 : 53, 650);
        ctx.fillStyle = '#9ca99b';
        ctx.fillRect(side, y + (square ? 17 : 28), 916, 1);
      });
      if (!albums.length) {
        ctx.fillStyle = '#293a34';
        ctx.font = '500 31px system-ui, sans-serif';
        ctx.fillText('No album metadata available.', side, listTop + 15);
      }
      const discoveryY = square ? 924 : 1610;
      ctx.fillStyle = '#173b32';
      ctx.font = '700 28px system-ui, sans-serif';
      ctx.fillText('FIRST SEEN THIS MONTH', side, discoveryY);
      ctx.fillStyle = '#131518';
      fitted(ctx, summary.first_seen_artists.length ? summary.first_seen_artists.slice(0, 3).join(' · ') : 'No new artists recorded', side, discoveryY + (square ? 42 : 65), 916, square ? 29 : 43, 600);
    }
    const brand = await brandImage(dark);
    if (token !== state.renderId) return;
    if (!brand) throw new Error('Spotify attribution could not load; recap export is unavailable.');
    ctx.fillStyle = dark ? '#9c9fa1' : '#666769';
    ctx.font = '500 22px system-ui';
    ctx.fillText('Personal history by Apollo', side, h - 78);
    if (brand) ctx.drawImage(brand, 808, h - 119, 190, 52);
    const link = state.slide === 0
      ? summary.top_albums.find(item => safeArt(item.artwork_url) && safeSpotify(item.spotify_url))?.spotify_url
      : state.slide === 1 ? summary.top_tracks.find(item => safeSpotify(item.spotify_url))?.spotify_url : null;
    fitted(ctx, link || 'https://open.spotify.com', side, h - 38, 730, 20, 500);
    ctx.fillText(`${state.slide + 1} / 3`, 925, h - 38);
  }
  function canvasBlob(canvas) {
    return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Could not create PNG')), 'image/png'));
  }
  function saveBlob(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = name;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
  async function zipPngs(entries) {
    const encoder = new TextEncoder();
    const pieces = [], central = [];
    let offset = 0, size = 0;
    function crc32(bytes) {
      let crc = -1;
      for (const byte of bytes) {
        crc ^= byte;
        for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
      }
      return (crc ^ -1) >>> 0;
    }
    for (const entry of entries) {
      const name = encoder.encode(entry.name);
      const bytes = new Uint8Array(await entry.blob.arrayBuffer());
      const checksum = crc32(bytes);
      const local = new Uint8Array(30 + name.length);
      const l = new DataView(local.buffer);
      l.setUint32(0, 0x04034b50, true); l.setUint16(4, 20, true);
      l.setUint16(12, 0x5c21, true);
      l.setUint32(14, checksum, true); l.setUint32(18, bytes.length, true);
      l.setUint32(22, bytes.length, true); l.setUint16(26, name.length, true);
      local.set(name, 30);
      pieces.push(local, bytes);
      const directory = new Uint8Array(46 + name.length);
      const d = new DataView(directory.buffer);
      d.setUint32(0, 0x02014b50, true); d.setUint16(4, 20, true); d.setUint16(6, 20, true);
      d.setUint16(14, 0x5c21, true);
      d.setUint32(16, checksum, true); d.setUint32(20, bytes.length, true);
      d.setUint32(24, bytes.length, true); d.setUint16(28, name.length, true);
      d.setUint32(42, offset, true);
      directory.set(name, 46);
      central.push(directory);
      offset += local.length + bytes.length;
      size += directory.length;
    }
    const end = new Uint8Array(22), e = new DataView(end.buffer);
    e.setUint32(0, 0x06054b50, true);
    e.setUint16(8, entries.length, true); e.setUint16(10, entries.length, true);
    e.setUint32(12, size, true); e.setUint32(16, offset, true);
    return new Blob([...pieces, ...central, end], {type: 'application/zip'});
  }
  async function loadRecap() {
    pane.replaceChildren(heading('Monthly recap', state.month), text('p', 'Loading recap…', 'muted'));
    try {
      if (state.month >= localMonth()) {
        pane.replaceChildren(heading('Monthly recap', state.month), text('p', 'This month is still in progress. Choose a completed month to generate a recap.', 'empty'));
        return;
      }
      const data = await request('/api/music/recaps', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Apollo-Request': 'music'}, body: JSON.stringify({month: state.month, timezone: zone})});
      if (state.tab !== 'recaps' || data.summary.month !== state.month) return;
      state.recap = data.summary;
      pane.replaceChildren(heading('Monthly recap', state.month));
      const status = text('div', '', 'statusline');
      status.append(text('span', `${data.summary.events} recorded plays · ${data.summary.duration_unknown_events} without duration · Coverage may be incomplete`));
      pane.append(status);
      const layout = text('div', '', 'recap-layout');
      const canvas = document.createElement('canvas');
      canvas.className = 'recap-preview';
      canvas.setAttribute('aria-label', `Apollo music recap for ${monthLabel(state.month)}, slide ${state.slide + 1}`);
      layout.append(canvas);
      const controls = text('div', '', 'panel');
      controls.append(text('h3', 'Make it yours'), text('p', 'Three editorial slides, composed from your recorded listening history. The preview is the exact canvas exported as PNG.', 'muted'));
      const actions = text('div', '', 'recap-actions');
      const slides = ['Overview', 'Top songs', 'Discoveries'];
      slides.forEach((label, index) => {
        const button = text('button', label); button.type = 'button';
        button.setAttribute('aria-pressed', String(state.slide === index));
        button.addEventListener('click', async () => {
          state.slide = index;
          actions.querySelectorAll('button[aria-pressed]').forEach((item, number) => item.setAttribute('aria-pressed', String(number === index)));
          canvas.setAttribute('aria-label', `Apollo music recap for ${monthLabel(state.month)}, slide ${index + 1}`);
          await renderRecap(canvas);
        });
        actions.append(button);
      });
      const format = text('button', state.format === 'story' ? 'Story · 1080 × 1920' : 'Square · 1080 × 1080');
      format.type = 'button';
      format.addEventListener('click', async () => { state.format = state.format === 'story' ? 'square' : 'story'; format.textContent = state.format === 'story' ? 'Story · 1080 × 1920' : 'Square · 1080 × 1080'; await renderRecap(canvas); });
      actions.append(format);
      controls.append(actions);
      const exportActions = text('div', '', 'recap-actions');
      const download = text('button', 'Download PNG', 'button-primary');
      download.type = 'button';
      download.addEventListener('click', async () => {
        download.disabled = true;
        try { await renderRecap(canvas); saveBlob(await canvasBlob(canvas), `apollo-${state.month}-${state.slide + 1}-${state.format}.png`); }
        catch (error) { controls.append(text('p', error.message, 'muted')); }
        finally { download.disabled = false; }
      });
      exportActions.append(download);
      const downloadAll = text('button', 'Download all · ZIP');
      downloadAll.type = 'button';
      downloadAll.addEventListener('click', async () => {
        downloadAll.disabled = true;
        const originalSlide = state.slide;
        try {
          const entries = [];
          for (let slide = 0; slide < slides.length; slide++) {
            state.slide = slide;
            await renderRecap(canvas);
            entries.push({name: `apollo-${state.month}-${slide + 1}-${state.format}.png`, blob: await canvasBlob(canvas)});
          }
          saveBlob(await zipPngs(entries), `apollo-${state.month}-${state.format}.zip`);
        } catch (error) { controls.append(text('p', error.message, 'muted')); }
        finally { state.slide = originalSlide; await renderRecap(canvas); downloadAll.disabled = false; }
      });
      exportActions.append(downloadAll);
      if (navigator.canShare) {
        const share = text('button', 'Share'); share.type = 'button';
        share.addEventListener('click', async () => {
          try {
            await renderRecap(canvas);
            const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
            const file = new File([blob], `apollo-${state.month}.png`, {type: 'image/png'});
            if (navigator.canShare({files: [file]})) await navigator.share({files: [file]});
          } catch (_) { /* Native share can be cancelled. */ }
        });
        exportActions.append(share);
      }
      const regenerate = text('button', 'Regenerate archive'); regenerate.type = 'button';
      regenerate.addEventListener('click', async () => {
        try {
          await request('/api/music/recaps', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Apollo-Request': 'music'}, body: JSON.stringify({month: state.month, timezone: zone, regenerate: true})});
          loadRecap();
        } catch (error) { controls.append(text('p', error.message, 'muted')); }
      });
      exportActions.append(regenerate);
      controls.append(exportActions);
      controls.append(spotifyAttribution());
      const featuredAlbum = data.summary.top_albums.find(item => safeArt(item.artwork_url) && safeSpotify(item.spotify_url));
      if (featuredAlbum) {
        const sourceLink = text('a', `Listen to ${featuredAlbum.name} on Spotify`, 'spotify-source-link');
        sourceLink.href = featuredAlbum.spotify_url;
        sourceLink.target = '_blank'; sourceLink.rel = 'noopener noreferrer';
        controls.append(sourceLink);
      }
      controls.append(text('p', data.summary.methodology, 'muted method'));
      controls.append(text('h3', 'Archive'));
      const archiveList = text('div', '', 'archive-list');
      const archive = await request('/api/music/recaps').catch(() => ({recaps: []}));
      archive.recaps.filter(item => item.timezone === zone).forEach(item => {
        const button = text('button', monthLabel(item.month)); button.type = 'button';
        button.addEventListener('click', () => { state.month = item.month; loadRecap(); });
        archiveList.append(button);
      });
      controls.append(archiveList);
      layout.append(controls);
      pane.append(layout);
      await renderRecap(canvas);
    } catch (error) { pane.replaceChildren(heading('Monthly recap', state.month), text('p', error.message || 'Recap could not load.', 'empty')); }
  }
  function activate(tab) {
    const previousTab = state.tab;
    state.tab = tab;
    tabs.querySelectorAll('button').forEach(button => button.setAttribute('aria-selected', String(button.dataset.tab === tab)));
    player.hidden = tab !== 'player';
    pane.hidden = tab === 'player';
    if (tab === 'insights') {
      if (previousTab === 'recaps' && state.period === 'monthly') state.anchor = `${state.month}-01`;
      loadInsights();
    }
    if (tab === 'recaps') {
      if (state.month === localMonth()) state.month = previousMonth(state.month);
      loadRecap();
    }
  }
  tabs.addEventListener('click', event => {
    const button = event.target.closest('button[data-tab]');
    if (button) activate(button.dataset.tab);
  });
  window.apolloOpenMusicInsights = () => { window.openMusic?.(); activate('insights'); };
  const destination = new URLSearchParams(location.search);
  const tab = destination.get('tab');
  const section = destination.get('view');
  if (tab === 'music' && (section === 'insights' || section === 'recaps')) {
    window.openMusic?.();
    activate(section);
  } else if (tab === 'home' && section === 'debrief') {
    window.openHome?.();
    requestAnimationFrame(() => document.querySelector('.debrief-box, #apolloDebriefText')?.scrollIntoView({block: 'start'}));
  }
})();
