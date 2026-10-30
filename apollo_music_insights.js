/* Music history and recaps use persisted Spotify events, never playback polls. */
(() => {
  const view = document.getElementById('musicView');
  if (!view) return;
  const player = view.querySelector('.apollo-music-inner');
  const tabs = document.createElement('nav');
  tabs.className = 'apollo-music-tabs';
  tabs.setAttribute('aria-label', 'Music sections');
  tabs.innerHTML = '<button type="button" data-tab="player" aria-selected="true">Player</button><button type="button" data-tab="insights" aria-selected="false">Insights</button><button type="button" data-tab="recaps" aria-selected="false">Recaps</button>';
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
  const state = {tab: 'player', month: localMonth(), recapPeriod: 'monthly', recapAnchor: `${previousMonth(localMonth())}-01`, summary: null, recap: null, slide: 0, theme: 'noir', format: 'story', renderId: 0};
  window.apolloMusicInsightsContext = () => ({
    section: state.tab,
    period: state.tab === 'recaps' ? state.recapPeriod : state.period,
    anchor: state.tab === 'recaps' ? state.recapAnchor : state.anchor,
  });
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
    return `${minutes.toLocaleString()} min`;
  }
  function initialDay() {
    return new Intl.DateTimeFormat('sv-SE', {timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
  }
  state.period = 'monthly';
  state.anchor = initialDay();
  state.expanded = null;
  state.metric = 'listening';
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
    if (row.verified_events && row.estimated_ms) return `${duration(row.listening_ms)} measured · ${duration(row.verified_ms)} verified + ${duration(row.estimated_ms)} estimated`;
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
    left.append(text('div', 'APOLLO / MUSIC', 'eyebrow'), text('h1', title));
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
    const measured = summary.chart.some(item => item.listening_ms > 0);
    const value = item => measured ? item.listening_ms || 0 : item.plays;
    const describe = item => measured ? `${duration(item.listening_ms || 0)} measured` : `${item.plays} recorded plays (minutes unavailable)`;
    bars.setAttribute('aria-label', summary.chart.map(item => `${item.label}: ${describe(item)}`).join(', '));
    const peak = Math.max(1, ...summary.chart.map(value));
    summary.chart.forEach((item, index) => { const amount = value(item); const bar = text('span', '', amount === peak && amount ? 'peak' : ''); bar.style.height = `${Math.max(2, amount / peak * 100)}%`; bar.title = `${item.label}: ${describe(item)}`; if (index % Math.max(1, Math.ceil(summary.chart.length / 7)) === 0) bar.dataset.label = item.label; bars.append(bar); });
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
      const timeValue = summary.verified_ms || summary.estimated_ms ? duration(summary.verified_ms + summary.estimated_ms) : 'Unavailable';
      const timeNote = `${duration(summary.verified_ms)} verified · ${duration(summary.estimated_ms)} estimated · ${summary.duration_unknown_events} plays without verified duration`;
      stats.append(stat('Measured listening', timeValue, timeNote), stat('Recorded plays', summary.events.toLocaleString(), 'Events in available history'), stat('Artists', summary.unique_artists.toLocaleString(), 'Credited in recorded plays'));
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
    if (entity !== 'history') { const metric = document.createElement('select'); metric.setAttribute('aria-label', 'Ranking metric'); [['listening','Listening minutes'],['plays','Recorded plays'],['verified','Verified time'],['estimated','Estimated time']].forEach(([value,label]) => { const option = new Option(label, value); metric.append(option); }); metric.value = state.metric; metric.onchange = () => { state.metric = metric.value; state.offset = 0; loadExpanded(); }; controls.append(metric); } pane.append(controls);
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
      let timer;
      try {
        await Promise.race([image.decode(), new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Artwork timed out')), 8000); })]);
        return image;
      } catch (_) {
        setTimeout(() => artworkCache.delete(url), 30000);
        return null;
      } finally { clearTimeout(timer); }
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
  const recapSizes = {story: 1920, portrait: 1350, square: 1080};
  const recapThemes = ['noir', 'atmosphere', 'editorial', 'after-hours'];
  function recapText(ctx, value, x, y, width, size, options = {}) {
    const {lines = 1, weight = 650, color = '#f7f5f0', family = 'system-ui, sans-serif', lineHeight = 1.13} = options;
    ctx.fillStyle = color;
    ctx.font = `${weight} ${size}px ${family}`;
    const words = String(value || '—').split(/\s+/);
    let line = '', used = 0;
    for (let i = 0; i < words.length; i++) {
      const candidate = line ? `${line} ${words[i]}` : words[i];
      if (ctx.measureText(candidate).width <= width) { line = candidate; continue; }
      if (line && used < lines - 1) { ctx.fillText(line, x, y + used++ * size * lineHeight); line = words[i]; continue; }
      line = candidate;
      while (ctx.measureText(line + (i < words.length - 1 ? '…' : '')).width > width && line.length > 1) line = line.slice(0, -1);
      if (i < words.length - 1 || line !== candidate) line += '…';
      break;
    }
    ctx.fillText(line, x, y + used * size * lineHeight);
    return used + 1;
  }
  function recapFitText(ctx, value, x, y, width, maxSize, maxLines, options = {}) {
    const words = String(value || '—').split(/\s+/);
    for (let size = maxSize; size >= 17; size--) {
      ctx.font = `${options.weight || 650} ${size}px ${options.family || 'system-ui, sans-serif'}`;
      const lines = [''];
      for (const word of words) {
        const candidate = lines.at(-1) ? `${lines.at(-1)} ${word}` : word;
        if (ctx.measureText(candidate).width <= width) lines[lines.length - 1] = candidate;
        else if (ctx.measureText(word).width <= width) lines.push(word);
        else {
          if (lines.at(-1)) lines.push('');
          let part = '';
          for (const letter of word) {
            if (ctx.measureText(part + letter).width > width && part) { lines[lines.length - 1] = part; lines.push(''); part = ''; }
            part += letter;
          }
          lines[lines.length - 1] = part;
        }
      }
      if (lines.length > maxLines) continue;
      ctx.fillStyle = options.color || '#f7f5f0';
      lines.forEach((line, index) => ctx.fillText(line, x, y + index * size * 1.12));
      return;
    }
    // Extremely long metadata gets an additional line at the smallest size.
    recapText(ctx, value, x, y, width, 17, {...options, lines: maxLines + 1});
  }
  function recapPalette(image) {
    if (!image) return [92, 72, 113];
    try {
      const sample = document.createElement('canvas'); sample.width = sample.height = 16;
      const context = sample.getContext('2d'); context.drawImage(image, 0, 0, 16, 16);
      const pixels = context.getImageData(0, 0, 16, 16).data;
      let r = 0, g = 0, b = 0, count = 0;
      for (let i = 0; i < pixels.length; i += 16) { r += pixels[i]; g += pixels[i + 1]; b += pixels[i + 2]; count++; }
      return [r / count, g / count, b / count].map(channel => Math.max(42, Math.min(190, Math.round(channel))));
    } catch (_) { return [92, 72, 113]; }
  }
  function recapImage(ctx, image, x, y, width, height, shape = 'square', fallback = '') {
    ctx.save();
    ctx.beginPath();
    if (shape === 'circle') ctx.arc(x + width / 2, y + height / 2, Math.min(width, height) / 2, 0, Math.PI * 2);
    else ctx.roundRect(x, y, width, height, shape === 'editorial' || shape === 'portrait' ? 2 : 17);
    ctx.clip();
    if (image) {
      // Portraits are contained when a square crop would cut off a face.
      const ratio = shape === 'circle' || shape === 'portrait' ? Math.min(width / image.width, height / image.height) : Math.max(width / image.width, height / image.height);
      const drawWidth = image.width * ratio, drawHeight = image.height * ratio;
      ctx.fillStyle = '#25252b'; ctx.fillRect(x, y, width, height);
      ctx.drawImage(image, x + (width - drawWidth) / 2, y + (height - drawHeight) / 2, drawWidth, drawHeight);
    } else {
      const gradient = ctx.createLinearGradient(x, y, x + width, y + height);
      gradient.addColorStop(0, '#383243'); gradient.addColorStop(1, '#181a20');
      ctx.fillStyle = gradient; ctx.fillRect(x, y, width, height);
      ctx.textAlign = 'center';
      recapText(ctx, (fallback || '♪').slice(0, 1).toUpperCase(), x + width / 2, y + height / 2 + Math.min(width, height) * .13, width * .8, Math.min(width, height) * .42, {color: '#e9e1ef'});
      ctx.textAlign = 'left';
    }
    ctx.restore();
  }
  function recapBackground(ctx, theme, h, palette) {
    const [r, g, b] = palette;
    const gradient = ctx.createLinearGradient(0, 0, theme === 'editorial' ? 0 : 1080, h);
    if (theme === 'editorial') { gradient.addColorStop(0, '#eeece7'); gradient.addColorStop(1, '#d8d5ce'); }
    else if (theme === 'noir') { gradient.addColorStop(0, '#101114'); gradient.addColorStop(1, '#050608'); }
    else if (theme === 'atmosphere') { gradient.addColorStop(0, `rgb(${Math.round(r*.55)},${Math.round(g*.55)},${Math.round(b*.65)})`); gradient.addColorStop(.55, '#192132'); gradient.addColorStop(1, `rgb(${Math.round(b*.36)},${Math.round(r*.28)},${Math.round(g*.35)})`); }
    else { gradient.addColorStop(0, '#0b0c1b'); gradient.addColorStop(.62, '#10101c'); gradient.addColorStop(1, '#05060b'); }
    ctx.fillStyle = gradient; ctx.fillRect(0, 0, 1080, h);
    if (theme === 'atmosphere' || theme === 'after-hours') {
      const glows = theme === 'atmosphere' ? [[800, h*.27, 640, `rgba(${r},${g},${b},.34)`], [140, h*.75, 500, 'rgba(64,143,172,.24)']] : [[840, h*.3, 600, 'rgba(119,60,159,.25)'], [170, h*.82, 480, 'rgba(197,75,100,.13)']];
      for (const [x, y, radius, color] of glows) { const glow = ctx.createRadialGradient(x, y, 0, x, y, radius); glow.addColorStop(0, color); glow.addColorStop(1, 'transparent'); ctx.fillStyle = glow; ctx.fillRect(0, 0, 1080, h); }
    }
  }
  function recapFrame(ctx, summary, theme, slide, h, brand) {
    const ink = theme === 'editorial' ? '#151515' : '#f7f5f0';
    const subdued = theme === 'editorial' ? '#5d5b56' : '#c0bdc5';
    ctx.fillStyle = ink; ctx.fillRect(68, 119, 944, theme === 'editorial' ? 3 : 1);
    recapText(ctx, 'APOLLO  /  MUSIC', 68, 91, 600, 28, {weight: 750, color: ink});
    ctx.textAlign = 'right'; recapText(ctx, `${slide + 1} / 3`, 1010, 91, 160, 25, {color: subdued}); ctx.textAlign = 'left';
    ctx.fillStyle = ink; ctx.fillRect(68, h - 117, 944, 1);
    recapText(ctx, 'PERSONAL LISTENING HISTORY', 68, h - 73, 620, 22, {weight: 600, color: subdued});
    if (brand) ctx.drawImage(brand, 811, h - 96, 198, 54);
    recapText(ctx, summary.period.label.toUpperCase(), 68, 173, 940, 26, {weight: 650, color: subdued});
  }
  function recapMetric(ctx, label, value, x, y, width, theme, compact) {
    const ink = theme === 'editorial' ? '#151515' : '#f7f5f0';
    const subdued = theme === 'editorial' ? '#5d5b56' : '#c0bdc5';
    recapText(ctx, label.toUpperCase(), x, y, width, 20, {weight: 700, color: subdued});
    recapText(ctx, value, x, y + (compact ? 51 : 66), width, compact ? 43 : 57, {weight: 680, color: ink});
  }
  async function renderRecap(canvas, choice = {}) {
    const summary = state.recap;
    if (!summary) return;
    const slide = choice.slide ?? state.slide, theme = choice.theme ?? state.theme, format = choice.format ?? state.format;
    const h = recapSizes[format], compact = h <= 1350, ink = theme === 'editorial' ? '#151515' : '#f7f5f0';
    if (!h || !recapThemes.includes(theme)) throw new Error('Unknown recap layout');
    const tracks = summary.top.tracks.slice(0, 5), artists = summary.top.artists.slice(0, 5);
    const images = await Promise.all([...tracks.map(item => artImage(item.image_url)), ...artists.map(item => artImage(item.image_url))]);
    const loadedTrack = images.slice(0, tracks.length).findIndex(Boolean);
    const loadedArtist = images.slice(tracks.length).findIndex(Boolean);
    const featuredTrack = tracks[loadedTrack >= 0 ? loadedTrack : 0];
    const featuredArtist = artists[loadedArtist >= 0 ? loadedArtist : 0];
    const albumImage = loadedTrack >= 0 ? images[loadedTrack] : null;
    const artistImage = loadedArtist >= 0 ? images[tracks.length + loadedArtist] : null;
    const brand = await brandImage(theme !== 'editorial');
    if (!brand) throw new Error('Spotify attribution could not load; recap export is unavailable.');
    canvas.width = 1080; canvas.height = h;
    const ctx = canvas.getContext('2d');
    recapBackground(ctx, theme, h, recapPalette(albumImage || artistImage));
    const serif = theme === 'editorial' ? 'Georgia, serif' : 'system-ui, sans-serif';
    if (slide === 0) {
      const artY = compact ? 287 : 350, artSize = h === 1080 ? 350 : compact ? 555 : 890;
      if (theme === 'editorial') {
        recapText(ctx, 'Overview', 68, compact ? 257 : 310, 940, compact ? 64 : 96, {weight: 500, family: serif, color: ink});
        recapImage(ctx, albumImage, 68, artY + (compact ? 37 : 65), artSize, artSize, 'editorial', featuredTrack?.name);
        recapImage(ctx, artistImage, compact ? 670 : 682, artY + (compact ? 70 : 105), compact ? 282 : 315, h === 1080 ? 335 : compact ? 460 : 560, 'portrait', featuredArtist?.name);
      } else if (theme === 'atmosphere') {
        recapText(ctx, 'Overview', 68, compact ? 260 : 317, 930, compact ? 72 : 102, {weight: 720, color: ink});
        recapImage(ctx, albumImage, 96, artY + 28, artSize - 45, artSize - 45, 'square', featuredTrack?.name);
        recapImage(ctx, artistImage, compact ? 668 : 676, artY + (compact ? 110 : 250), h === 1080 ? 270 : compact ? 365 : 330, h === 1080 ? 270 : compact ? 365 : 330, 'circle', featuredArtist?.name);
      } else if (theme === 'after-hours') {
        recapText(ctx, 'Overview', 68, compact ? 255 : 313, 940, compact ? 69 : 98, {weight: 650, color: ink});
        recapImage(ctx, albumImage, 68, artY + 37, artSize - 65, artSize - 65, 'square', featuredTrack?.name);
        recapImage(ctx, artistImage, compact ? 640 : 621, artY + (compact ? 115 : 380), h === 1080 ? 282 : compact ? 340 : 365, h === 1080 ? 282 : compact ? 340 : 365, 'square', featuredArtist?.name);
      } else {
        recapText(ctx, 'Overview', 68, compact ? 255 : 313, 940, compact ? 73 : 103, {weight: 700, color: ink});
        recapImage(ctx, albumImage, 68, artY + 37, artSize - 38, artSize - 38, 'square', featuredTrack?.name);
        recapImage(ctx, artistImage, compact ? 670 : 694, artY + (compact ? 115 : 295), h === 1080 ? 270 : compact ? 318 : 300, h === 1080 ? 270 : compact ? 318 : 300, 'circle', featuredArtist?.name);
      }
      const bottom = compact ? h - 255 : h - 330;
      recapText(ctx, `${String(loadedTrack >= 0 ? loadedTrack + 1 : 1).padStart(2, '0')}  /  FEATURED TRACK`, 68, bottom - (compact ? 105 : 135), 700, 24, {weight: 700, color: ink});
      recapFitText(ctx, featuredTrack?.name || 'Featured track unavailable', 68, bottom - (compact ? 47 : 61), 930, compact ? 45 : 60, 2, {weight: 700, family: serif, color: ink});
      recapText(ctx, featuredTrack?.artist_name || featuredArtist?.name || 'No recorded artist', 68, bottom, 920, compact ? 28 : 34, {color: ink});
      recapMetric(ctx, 'Recorded streams', summary.events.toLocaleString(), 68, h - (compact ? 212 : 260), 410, theme, compact);
      const listened = summary.verified_ms || summary.estimated_ms ? duration(summary.verified_ms + summary.estimated_ms) : 'Unavailable';
      recapMetric(ctx, 'Listening time', listened, 545, h - (compact ? 212 : 260), 455, theme, compact);
    } else {
      const isTrack = slide === 1, rows = isTrack ? tracks : artists;
      recapText(ctx, isTrack ? 'The tracks' : 'The artists', 68, compact ? 265 : 312, 940, compact ? 76 : 108, {weight: theme === 'editorial' ? 500 : 730, family: serif, color: ink});
      recapText(ctx, isTrack ? 'RANKED BY MEASURED LISTENING TIME' : 'RANKED BY MEASURED LISTENING TIME', 68, compact ? 309 : 364, 940, 23, {weight: 650, color: ink});
      const start = h === 1080 ? 340 : compact ? 365 : 445, gap = h === 1080 ? 123 : compact ? 155 : 232, art = h === 1080 ? 104 : compact ? 129 : 178;
      rows.forEach((item, index) => {
        const y = start + index * gap;
        if (theme === 'atmosphere' || theme === 'after-hours') {
          ctx.fillStyle = theme === 'atmosphere' ? 'rgba(255,255,255,.11)' : 'rgba(255,255,255,.065)';
          const stagger = theme === 'after-hours' && index % 2 ? 20 : 0;
          ctx.beginPath(); ctx.roundRect(68 + stagger, y - 15, 944 - stagger, gap - (compact ? 9 : 23), 19); ctx.fill();
          if (theme === 'after-hours') { ctx.fillStyle = index % 2 ? '#8b638e' : '#bb6779'; ctx.fillRect(68 + stagger, y + 4, 3, art - 8); }
        } else if (theme === 'editorial') {
          ctx.fillStyle = '#77736d'; ctx.fillRect(68, y + art + 13, 944, 1);
        } else { ctx.fillStyle = '#49494c'; ctx.fillRect(68, y + art + 13, 944, 1); }
        const stagger = theme === 'after-hours' && index % 2 ? 20 : 0;
        recapImage(ctx, images[isTrack ? index : tracks.length + index], theme === 'editorial' ? 844 : 84 + stagger, y, art, art, isTrack ? theme === 'editorial' ? 'editorial' : 'square' : theme === 'editorial' ? 'portrait' : 'circle', item.name);
        const left = theme === 'editorial' ? 70 : (compact ? 220 : 282) + stagger;
        recapText(ctx, String(index + 1).padStart(2, '0'), left, y + 29, 70, compact ? 25 : 32, {weight: 700, color: theme === 'editorial' ? '#77736d' : '#bdb8c0'});
        const width = theme === 'editorial' ? 730 : 1010 - left;
        recapFitText(ctx, item.name, left, y + (compact ? 62 : 88), width, h === 1080 ? 27 : compact ? 32 : 49, 2, {weight: theme === 'editorial' ? 500 : 690, family: serif, color: ink});
        if (isTrack) recapFitText(ctx, item.artist_name || 'Artist unavailable', left, y + (h === 1080 ? 115 : compact ? 129 : 170), width, compact ? 20 : 27, 2, {color: theme === 'editorial' ? '#55534f' : '#c5c0c9'});
      });
      if (!rows.length) recapText(ctx, 'No recorded listening in this period.', 68, start + 130, 900, 35, {color: ink});
      const listened = summary.verified_ms || summary.estimated_ms ? duration(summary.verified_ms + summary.estimated_ms) : 'Time unavailable';
      if (h > 1350) {
        const footerY = h - 230;
        recapMetric(ctx, 'Recorded streams', summary.events.toLocaleString(), 68, footerY, 410, theme, compact);
        recapMetric(ctx, 'Listening time', listened, 545, footerY, 455, theme, compact);
      }
    }
    recapFrame(ctx, summary, theme, slide, h, brand);
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
  function recapStep(direction) {
    const [year, month, day] = state.recapAnchor.split('-').map(Number);
    const date = new Date(Date.UTC(year, month - 1, day));
    if (state.recapPeriod === 'weekly') date.setUTCDate(date.getUTCDate() + 7 * direction);
    else { date.setUTCDate(1); date.setUTCMonth(date.getUTCMonth() + direction); }
    const next = date.toISOString().slice(0, 10);
    if (next <= initialDay()) state.recapAnchor = next;
  }
  async function loadRecap() {
    const period = state.recapPeriod, anchor = state.recapAnchor;
    pane.replaceChildren(heading('Music recaps'), text('p', 'Composing your recap…', 'muted'));
    try {
      const summary = await request(`/api/music/analytics?${new URLSearchParams({period, anchor, timezone: zone, recap: '1'})}`);
      if (state.tab !== 'recaps' || state.recapPeriod !== period || state.recapAnchor !== anchor) return;
      state.recap = summary;
      pane.replaceChildren(heading('Music recaps'));
      const navigation = text('div', '', 'recap-period-controls');
      const types = text('div', '', 'recap-segment');
      for (const kind of ['weekly', 'monthly']) {
        const button = text('button', kind === 'weekly' ? 'Weekly' : 'Monthly'); button.type = 'button';
        button.setAttribute('aria-pressed', String(period === kind));
        button.onclick = () => { state.recapPeriod = kind; state.recapAnchor = kind === 'monthly' ? `${state.month}-01` : initialDay(); loadRecap(); };
        types.append(button);
      }
      navigation.append(types);
      const dates = text('div', '', 'recap-date-controls');
      const previous = text('button', '‹'); previous.type = 'button'; previous.setAttribute('aria-label', 'Previous recap period');
      previous.onclick = () => { recapStep(-1); loadRecap(); };
      const picker = document.createElement('input'); picker.type = period === 'weekly' ? 'date' : 'month';
      picker.value = period === 'weekly' ? anchor : anchor.slice(0, 7);
      picker.max = period === 'weekly' ? initialDay() : localMonth();
      picker.setAttribute('aria-label', period === 'weekly' ? 'Choose recap week' : 'Choose recap month');
      picker.onchange = () => { if (picker.value && picker.value <= picker.max) { state.recapAnchor = period === 'weekly' ? picker.value : `${picker.value}-01`; state.month = state.recapAnchor.slice(0, 7); loadRecap(); } };
      const next = text('button', '›'); next.type = 'button'; next.setAttribute('aria-label', 'Next recap period');
      next.disabled = !summary.period.can_next; next.onclick = () => { recapStep(1); loadRecap(); };
      dates.append(previous, picker, next); navigation.append(dates); pane.append(navigation);
      pane.append(text('p', summary.period.label, 'recap-period-label'));
      const status = text('p', `${summary.events.toLocaleString()} recorded streams · ${summary.duration_unknown_events} without verified duration · Coverage may be incomplete`, 'muted recap-coverage');
      pane.append(status);
      if (!summary.events) { pane.append(text('p', 'No recorded music in this period. Choose another week or month.', 'empty')); return; }
      const layout = text('div', '', 'recap-layout');
      const preview = text('div', '', 'recap-preview-wrap');
      const canvas = document.createElement('canvas'); canvas.className = 'recap-preview'; preview.append(canvas); layout.append(preview);
      const controls = text('div', '', 'panel recap-panel');
      controls.append(text('h3', 'Your listening, beautifully told'), text('p', 'Choose a composition and format. Every PNG uses the same canvas as this preview.', 'muted'));
      const errorBox = text('p', '', 'recap-error'); errorBox.setAttribute('role', 'status');
      let renderToken = 0;
      async function previewRecap() {
        const token = ++renderToken, offscreen = document.createElement('canvas');
        await document.fonts?.ready;
        await renderRecap(offscreen);
        if (token !== renderToken || state.tab !== 'recaps' || state.recap !== summary) return;
        canvas.width = offscreen.width; canvas.height = offscreen.height;
        canvas.getContext('2d').drawImage(offscreen, 0, 0);
        canvas.setAttribute('aria-label', `Apollo ${period} music recap for ${summary.period.label}, ${state.theme} theme, slide ${state.slide + 1}`);
      }
      function updatePreview() { previewRecap().catch(error => { errorBox.textContent = error.message; }); }
      const themes = text('div', '', 'recap-theme-grid'); themes.setAttribute('role', 'group'); themes.setAttribute('aria-label', 'Recap theme');
      for (const theme of recapThemes) {
        const button = text('button', theme === 'after-hours' ? 'After Hours' : theme[0].toUpperCase() + theme.slice(1), `recap-theme recap-theme-${theme}`);
        button.type = 'button'; button.setAttribute('aria-pressed', String(state.theme === theme));
        button.onclick = () => { state.theme = theme; themes.querySelectorAll('button').forEach(item => item.setAttribute('aria-pressed', String(item === button))); updatePreview(); };
        themes.append(button);
      }
      controls.append(text('h4', 'Visual theme'), themes);
      const slides = ['Overview', 'Top Tracks', 'Top Artists'];
      const slideButtons = text('div', '', 'recap-actions');
      slides.forEach((label, index) => {
        const button = text('button', label); button.type = 'button'; button.setAttribute('aria-pressed', String(state.slide === index));
        button.onclick = () => { state.slide = index; slideButtons.querySelectorAll('button').forEach((item, position) => item.setAttribute('aria-pressed', String(position === index))); updatePreview(); };
        slideButtons.append(button);
      });
      controls.append(text('h4', 'Slide'), slideButtons);
      const formats = text('div', '', 'recap-actions');
      for (const [key, label] of [['story', 'Story · 1080 × 1920'], ['portrait', 'Portrait · 1080 × 1350'], ['square', 'Square · 1080 × 1080']]) {
        const button = text('button', label); button.type = 'button'; button.setAttribute('aria-pressed', String(state.format === key));
        button.onclick = () => { state.format = key; formats.querySelectorAll('button').forEach(item => item.setAttribute('aria-pressed', String(item === button))); updatePreview(); };
        formats.append(button);
      }
      controls.append(text('h4', 'Format'), formats);
      const exportActions = text('div', '', 'recap-actions');
      const fileStem = choice => `apollo-${period}-${summary.period.first_date}-${choice.theme}-${choice.format}`;
      const download = text('button', 'Download PNG', 'button-primary'); download.type = 'button';
      download.onclick = async () => {
        download.disabled = true; errorBox.textContent = '';
        try { const selected = {slide: state.slide, theme: state.theme, format: state.format}; const output = document.createElement('canvas'); await renderRecap(output, selected); saveBlob(await canvasBlob(output), `${fileStem(selected)}-${selected.slide + 1}.png`); }
        catch (error) { errorBox.textContent = error.message; }
        finally { download.disabled = false; }
      };
      exportActions.append(download);
      const downloadAll = text('button', 'Download all slides · ZIP'); downloadAll.type = 'button';
      downloadAll.onclick = async () => {
        downloadAll.disabled = true; errorBox.textContent = '';
        try {
          const selected = {theme: state.theme, format: state.format}; const entries = [];
          for (let slide = 0; slide < 3; slide++) { const output = document.createElement('canvas'); await renderRecap(output, {...selected, slide}); entries.push({name: `${fileStem(selected)}-${slide + 1}.png`, blob: await canvasBlob(output)}); }
          saveBlob(await zipPngs(entries), `${fileStem(selected)}.zip`);
        } catch (error) { errorBox.textContent = error.message; }
        finally { downloadAll.disabled = false; }
      };
      exportActions.append(downloadAll);
      if (navigator.canShare) {
        const share = text('button', 'Share'); share.type = 'button';
        share.onclick = async () => {
          try { const selected = {slide: state.slide, theme: state.theme, format: state.format}; const output = document.createElement('canvas'); await renderRecap(output, selected); const file = new File([await canvasBlob(output)], `${fileStem(selected)}-${selected.slide + 1}.png`, {type: 'image/png'}); if (navigator.canShare({files: [file]})) await navigator.share({files: [file]}); }
          catch (error) { if (error.name !== 'AbortError') errorBox.textContent = error.message; }
        };
        exportActions.append(share);
      }
      controls.append(text('h4', 'Export'), exportActions, errorBox, spotifyAttribution());
      const featured = summary.top.tracks.find(item => safeSpotify(item.spotify_url));
      if (featured) { const source = text('a', `Listen to ${featured.name} on Spotify`, 'spotify-source-link'); source.href = featured.spotify_url; source.target = '_blank'; source.rel = 'noopener noreferrer'; controls.append(source); }
      controls.append(text('p', summary.methodology, 'muted method'));
      if (period === 'monthly') {
        const archived = text('div', '', 'recap-archive');
        archived.append(text('h4', 'Saved months'));
        if (summary.period.end_date <= initialDay()) {
          const regenerate = text('button', 'Refresh saved recap'); regenerate.type = 'button';
          regenerate.onclick = async () => {
            regenerate.disabled = true; errorBox.textContent = '';
            try { await request('/api/music/recaps', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Apollo-Request': 'music'}, body: JSON.stringify({month: anchor.slice(0, 7), timezone: zone, regenerate: true})}); await loadRecap(); }
            catch (error) { errorBox.textContent = error.message; regenerate.disabled = false; }
          };
          archived.append(regenerate);
        }
        const archiveList = text('div', '', 'archive-list'); archived.append(archiveList); controls.append(archived);
        request('/api/music/recaps').then(archive => {
          if (state.recap !== summary) return;
          archive.recaps.filter(item => item.timezone === zone).forEach(item => {
            const button = text('button', monthLabel(item.month)); button.type = 'button';
            button.onclick = () => { state.month = item.month; state.recapAnchor = `${item.month}-01`; loadRecap(); };
            archiveList.append(button);
          });
        }).catch(() => { archiveList.append(text('p', 'Saved months are unavailable right now.', 'muted')); });
      }
      layout.append(controls); pane.append(layout); updatePreview();
    } catch (error) { if (state.tab === 'recaps' && state.recapPeriod === period && state.recapAnchor === anchor) pane.replaceChildren(heading('Music recaps'), text('p', error.message || 'Recap could not load.', 'empty')); }
  }
  function activate(tab) {
    const previousTab = state.tab;
    state.tab = tab;
    tabs.querySelectorAll('button').forEach(button => button.setAttribute('aria-selected', String(button.dataset.tab === tab)));
    player.hidden = tab !== 'player';
    pane.hidden = tab === 'player';
    if (tab === 'insights') {
      if (previousTab === 'recaps') { state.period = state.recapPeriod; state.anchor = state.recapAnchor; }
      loadInsights();
    }
    if (tab === 'recaps') {
      if (previousTab === 'insights' && ['weekly', 'monthly'].includes(state.period)) {
        state.recapPeriod = state.period; state.recapAnchor = state.anchor; state.month = state.anchor.slice(0, 7);
      }
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
