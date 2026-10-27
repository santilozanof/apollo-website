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
  function rankPanel(title, rows) {
    const panel = text('section', '', 'panel');
    panel.append(text('h3', title));
    const list = text('div', '', 'ranked');
    if (!rows.length) list.append(text('p', 'No recorded activity for this month.', 'muted'));
    rows.forEach((row, index) => {
      const item = text('div', '', 'ranked-row');
      item.append(text('span', String(index + 1).padStart(2, '0'), 'number'));
      if (title !== 'Top artists' && safeArt(row.artwork_url) && safeSpotify(row.spotify_url)) {
        const img = document.createElement('img');
        img.src = row.artwork_url;
        img.alt = '';
        img.loading = 'lazy';
        item.append(img);
      } else item.append(text('span', '', 'art-placeholder'));
      item.append(text('span', row.name, 'name'), text('span', `${row.plays} ${row.plays === 1 ? 'play' : 'plays'}`, 'plays'));
      const direct = safeSpotify(row.spotify_url);
      const link = text('a', direct ? 'Spotify' : 'Find on Spotify');
      link.href = direct ? row.spotify_url : `https://open.spotify.com/search/${encodeURIComponent(row.name)}`;
      link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.setAttribute('aria-label', `${direct ? 'Open' : 'Find'} ${row.name} on Spotify`);
      item.append(link);
      list.append(item);
    });
    panel.append(list);
    return panel;
  }
  function heading(title, month) {
    const top = text('div', '', 'topline');
    const left = text('div', '');
    left.append(text('div', 'APOLLO MUSIC', 'eyebrow'), text('h2', title));
    const input = document.createElement('input');
    input.type = 'month';
    input.value = month;
    input.max = localMonth();
    input.setAttribute('aria-label', 'Listening month');
    input.addEventListener('change', () => {
      if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(input.value)) return;
      state.month = input.value;
      state.recap = null;
      state.tab === 'recaps' ? loadRecap() : loadInsights();
    });
    top.append(left, input);
    return top;
  }
  async function loadInsights() {
    pane.replaceChildren(heading('Listening insights', state.month), text('p', 'Loading your listening history…', 'muted'));
    try {
      const params = new URLSearchParams({month: state.month, timezone: zone});
      const [summary, previous] = await Promise.all([
        request(`/api/music/insights?${params}`),
        request(`/api/music/insights?${new URLSearchParams({month: previousMonth(state.month), timezone: zone})}`)
      ]);
      if (state.tab !== 'insights' || summary.month !== state.month) return;
      state.summary = summary;
      pane.replaceChildren(heading('Listening insights', state.month));
      const status = text('div', '', 'statusline');
      status.append(text('span', summary.last_sync_at ? `Spotify synced ${new Date(summary.last_sync_at).toLocaleString()}` : 'No successful Spotify sync yet. Historical coverage may be limited.'));
      if (summary.sync_error) status.append(text('span', summary.sync_error));
      if (summary.coverage_warning) status.append(text('span', summary.coverage_warning));
      status.append(spotifyAttribution());
      const refresh = text('button', 'Sync Spotify');
      refresh.type = 'button';
      refresh.addEventListener('click', async () => {
        refresh.disabled = true;
        try {
          await request('/api/music/history/sync', {method: 'POST', headers: {'X-Apollo-Request': 'music'}});
          status.append(text('span', 'Sync started. Refresh shortly.'));
          setTimeout(() => { if (state.tab === 'insights') loadInsights(); }, 12000);
        } catch (error) { status.append(text('span', error.message)); }
        finally { refresh.disabled = false; }
      });
      status.append(refresh);
      pane.append(status);
      const stats = text('div', '', 'stats');
      [
        ['Verified listening', duration(summary.verified_ms), `${summary.duration_unknown_events} events have unknown duration`],
        ['Recorded plays', summary.events.toLocaleString(), 'Distinct listening events'],
        ['Artists', summary.unique_artists.toLocaleString(), 'Observed in Apollo history']
      ].forEach(([label, value, note]) => {
        const card = text('div', '', 'stat');
        card.append(text('div', label, 'eyebrow'), text('strong', value), text('span', note));
        stats.append(card);
      });
      pane.append(stats);
      if (!summary.events) {
        pane.append(text('p', 'No listening events are recorded for this month yet. Sync Spotify or import your official history below.', 'empty'));
      } else {
      const grid = text('div', '', 'grid');
      grid.append(rankPanel('Top artists', summary.top_artists), rankPanel('Top songs', summary.top_tracks), rankPanel('Top albums', summary.top_albums));
      const patterns = text('section', '', 'panel');
      patterns.append(text('h3', 'Listening pattern'));
      if (summary.events) {
        const chart = text('div', '', 'pattern');
        const counts = Array.from({length: 24}, (_, hour) => Number(summary.hours[String(hour)] || 0));
        const max = Math.max(1, ...counts);
        counts.forEach((count, hour) => {
          const bar = text('span', '');
          bar.style.height = `${Math.max(2, count / max * 100)}%`;
          bar.title = `${hour}:00 · ${count} plays`;
          if (count === max && count) bar.className = 'peak';
          chart.append(bar);
        });
        patterns.append(chart);
        const axis = text('div', '', 'pattern-axis');
        ['00:00', '06:00', '12:00', '18:00', '23:00'].forEach(label => axis.append(text('span', label)));
        patterns.append(axis);
      } else patterns.append(text('p', 'No listening pattern is available for this month.', 'muted'));
      const change = previous.events ? Math.round((summary.events - previous.events) / previous.events * 100) : null;
      patterns.append(text('p', !summary.events ? 'No recorded activity this month; comparison is unavailable.' : change === null ? 'No recorded plays in the previous month for comparison.' : `${Math.abs(change)}% ${change >= 0 ? 'more' : 'fewer'} recorded plays than ${monthLabel(previous.month)}. Coverage may differ.`, 'muted method'));
      grid.append(patterns);
      pane.append(grid);
      const discovery = text('section', '', 'panel method');
      discovery.append(text('h3', 'First seen in Apollo history'));
      discovery.append(text('p', summary.first_seen_artists.length ? summary.first_seen_artists.join(' · ') : 'No first-seen artists this month.', 'muted'));
      pane.append(discovery);
      const recent = text('section', '', 'panel method');
      recent.append(text('h3', 'Recent listening'));
      const recentList = text('div', '', 'recent-list');
      const recentItems = Array.isArray(summary.recent) ? summary.recent : [];
      if (!recentItems.length) recentList.append(text('p', 'No recorded listening activity for this month.', 'muted'));
      recentItems.forEach(item => {
        const row = text('div', '', 'recent-row');
        row.append(text('span', '', 'art-placeholder'));
        const identity = text('div', '', 'recent-identity');
        identity.append(text('strong', item.track_name), text('span', item.artist_name));
        row.append(identity);
        const search = text('a', 'Spotify', 'recent-spotify-link');
        search.href = `https://open.spotify.com/search/${encodeURIComponent(item.track_name + ' ' + item.artist_name)}`;
        search.target = '_blank'; search.rel = 'noopener noreferrer';
        search.setAttribute('aria-label', `Find ${item.track_name} on Spotify`);
        row.append(search);
        const played = new Date(item.event_at);
        row.append(text('time', Number.isNaN(played.valueOf()) ? 'Date unavailable' : played.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}), 'muted'));
        recentList.append(row);
      });
      recent.append(recentList);
      pane.append(recent);
      }
      const importBox = text('section', '', 'panel method');
      importBox.append(text('h3', 'Import Spotify history'), text('p', 'Use the JSON files from your official Spotify account or extended streaming-history export. Each file is imported once; overlapping records are merged where identifiable.', 'muted'));
      const row = text('div', '', 'import');
      const input = document.createElement('input');
      input.type = 'file'; input.accept = '.json,application/json'; input.multiple = true;
      input.setAttribute('aria-label', 'Spotify listening history JSON files');
      const progress = text('span', '', 'muted import-progress');
      input.addEventListener('change', async () => {
        for (const file of input.files || []) {
          if (file.size > 16 * 1024 * 1024) { progress.textContent = `${file.name}: file exceeds 16 MB`; continue; }
          progress.textContent = `Importing ${file.name}…`;
          try {
            const result = await upload(file, fraction => { progress.textContent = `Importing ${file.name}: ${Math.round(fraction * 100)}%`; });
            progress.textContent = `${file.name}: ${result.imported} new, ${result.duplicates} duplicates, ${result.skipped} nonmusic rows skipped.`;
          } catch (error) { progress.textContent = `${file.name}: ${error.message}`; break; }
        }
        input.value = '';
        setTimeout(() => { if (state.tab === 'insights') loadInsights(); }, 2400);
      });
      row.append(input, progress); importBox.append(row);
      const importHistory = await request('/api/music/imports').catch(() => ({imports: []}));
      if (Array.isArray(importHistory.imports) && importHistory.imports.length) {
        const latest = importHistory.imports[0];
        importBox.append(text('p', `Last import: ${latest.file_name} · ${latest.imported_count} new events · ${new Date(latest.created_at + 'Z').toLocaleDateString()}`, 'muted method'));
      }
      importBox.append(text('p', summary.methodology, 'muted method'));
      pane.append(importBox);
    } catch (error) { pane.replaceChildren(heading('Listening insights', state.month), text('p', error.message || 'Music history could not load.', 'empty')); }
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
    state.tab = tab;
    tabs.querySelectorAll('button').forEach(button => button.setAttribute('aria-selected', String(button.dataset.tab === tab)));
    player.hidden = tab !== 'player';
    pane.hidden = tab === 'player';
    if (tab === 'insights') loadInsights();
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
