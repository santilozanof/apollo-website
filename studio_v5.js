(() => {
    const view = document.getElementById("studioView");
    if (!view || view.dataset.studioV5 === "1") return;
    view.dataset.studioV5 = "1";

    const state = {
        projects: [],
        project: null,
        tab: "overview",
        expandedTracks: new Set(),
        source: null,
        playingTrackId: null,
        playingVersionId: null
    };

    const esc = value => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

    const fmtType = value => {
        const v = String(value || "single").toLowerCase();
        if (v === "ep") return "EP";
        if (v === "album") return "Album";
        if (v === "single") return "Single";
        return "Project";
    };

    const fmtStatus = value => String(value || "idea")
        .replaceAll("_", " ")
        .replace(/\b\w/g, c => c.toUpperCase());

    const fmtDate = value => {
        if (!value) return "";
        const date = new Date(String(value).replace(" ", "T") + (String(value).includes("Z") ? "" : "Z"));
        if (Number.isNaN(date.getTime())) return "";
        return date.toLocaleDateString(undefined, {month: "short", day: "numeric", year: date.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined});
    };

    const fmtTime = seconds => {
        const n = Number(seconds);
        if (!Number.isFinite(n) || n < 0) return "0:00";
        const m = Math.floor(n / 60);
        const s = Math.floor(n % 60);
        return `${m}:${String(s).padStart(2, "0")}`;
    };

    const api = async (url, options = {}) => {
        const response = await fetch(url, options);
        let data = {};
        try { data = await response.json(); } catch (_) {}
        if (!response.ok) throw new Error(data.error || "Studio request failed");
        return data;
    };

    const postJSON = (url, body) => api(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
    });

    const displayVersionLabel = version => {
        const raw = String(version?.label || "").trim();
        if (raw && raw.toLowerCase() !== "current") return raw;
        const file = String(version?.audio_name || "").replace(/\.[^.]+$/, "");
        const suffix = file.match(/(?:\s[-–—]\s)([^–—]+)$/);
        if (suffix && suffix[1].trim().length <= 36) return suffix[1].trim();
        return "Main mix";
    };

    const primaryVersion = track => {
        const versions = Array.isArray(track?.versions) ? track.versions : [];
        return versions.find(v => v.is_current) || versions[0] || null;
    };

    const playableUrl = version => version?.playback_audio_url || version?.audio_url || version?.original_audio_url || "";

    const icon = name => {
        const icons = {
            play: '<svg viewBox="0 0 24 24"><path d="M9 7.2 17 12 9 16.8Z" fill="currentColor"/></svg>',
            pause: '<svg viewBox="0 0 24 24"><rect x="8" y="7" width="2.7" height="10" rx="1" fill="currentColor"/><rect x="13.3" y="7" width="2.7" height="10" rx="1" fill="currentColor"/></svg>',
            plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
            more: '<svg viewBox="0 0 24 24"><circle cx="6" cy="12" r="1.4" fill="currentColor"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/><circle cx="18" cy="12" r="1.4" fill="currentColor"/></svg>',
            back: '<svg viewBox="0 0 24 24"><path d="M15 6 9 12l6 6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
            wave: '<svg viewBox="0 0 24 24"><path d="M5 12h2M8.5 8.5v7M12 5.5v13M15.5 8v8M19 10.5v3" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
            file: '<svg viewBox="0 0 24 24"><path d="M7 3.8h6.5L18 8.3v11.9H7z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M13.5 3.8v4.5H18" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>',
            link: '<svg viewBox="0 0 24 24"><path d="M9.2 14.8 14.8 9.2M8.3 17.2l-1 .9a3.4 3.4 0 0 1-4.8-4.8l3.1-3.1a3.4 3.4 0 0 1 4.8 0M15.7 6.8l1-.9a3.4 3.4 0 0 1 4.8 4.8l-3.1 3.1a3.4 3.4 0 0 1-4.8 0" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
            image: '<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="9" cy="10" r="1.4" fill="currentColor"/><path d="m6 17 4.1-4 2.8 2.6 2.1-2 3 3.4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        };
        return icons[name] || "";
    };

    view.innerHTML = `
        <div class="studio5-shell">
            <header class="studio5-topbar">
                <div class="studio5-brandcopy">
                    <div class="studio5-eyebrow">APOLLO</div>
                    <h1>Studio</h1>
                    <p>Your music, versions, notes and visual world — organized around the work.</p>
                </div>
                <div class="studio5-top-actions">
                    <button class="studio5-ghost" type="button" data-studio-ask>Ask Apollo</button>
                    <button class="studio5-primary" type="button" data-new-project>${icon("plus")}<span>New Project</span></button>
                </div>
            </header>
            <main id="studio5Stage" class="studio5-stage"></main>
            <section id="studio5Transport" class="studio5-transport" aria-hidden="true">
                <div class="studio5-transport-art" id="studio5TransportArt">${icon("wave")}</div>
                <div class="studio5-transport-copy">
                    <div class="studio5-transport-title" id="studio5TransportTitle">Studio</div>
                    <div class="studio5-transport-sub" id="studio5TransportSub">—</div>
                </div>
                <button class="studio5-transport-toggle" id="studio5TransportToggle" type="button" aria-label="Play">${icon("play")}</button>
                <div class="studio5-transport-progress">
                    <input id="studio5TransportRange" type="range" min="0" max="1000" value="0" aria-label="Playback position">
                    <div id="studio5TransportTime">0:00 / 0:00</div>
                </div>
                <button class="studio5-transport-close" id="studio5TransportClose" type="button" aria-label="Close">×</button>
                <audio id="studio5Audio" preload="metadata"></audio>
            </section>
        </div>
        <div id="studio5ModalRoot"></div>
    `;

    const stage = document.getElementById("studio5Stage");
    const modalRoot = document.getElementById("studio5ModalRoot");
    const transport = document.getElementById("studio5Transport");
    const audio = document.getElementById("studio5Audio");
    const transportArt = document.getElementById("studio5TransportArt");
    const transportTitle = document.getElementById("studio5TransportTitle");
    const transportSub = document.getElementById("studio5TransportSub");
    const transportToggle = document.getElementById("studio5TransportToggle");
    const transportRange = document.getElementById("studio5TransportRange");
    const transportTime = document.getElementById("studio5TransportTime");
    const transportClose = document.getElementById("studio5TransportClose");

    const projectArtwork = project => project?.artwork_url || "";

    function artworkMarkup(project, className = "") {
        const src = projectArtwork(project);
        if (src) return `<img class="${className}" src="${esc(src)}" alt="">`;
        return `<div class="studio5-art-fallback ${className}">${icon("wave")}</div>`;
    }

    function setBusy(value) {
        view.classList.toggle("is-busy", Boolean(value));
    }

    async function loadProjects() {
        const data = await api("/api/studio/projects");
        state.projects = data.projects || [];
        return state.projects;
    }

    async function loadProject(projectId) {
        const data = await api(`/api/studio/projects/${Number(projectId)}`);
        state.project = data.project;
        sessionStorage.setItem("apollo.studio.project", String(projectId));
        return state.project;
    }

    function libraryCard(project, index) {
        const meta = [fmtType(project.project_type), fmtStatus(project.status)].filter(Boolean).join(" · ");
        return `
            <article class="studio5-project-card" style="--i:${index}" data-open-project="${project.id}">
                <div class="studio5-project-art">
                    ${artworkMarkup(project)}
                    <button class="studio5-project-play" type="button" data-play-project="${project.id}" aria-label="Play ${esc(project.title)}">${icon("play")}</button>
                    <div class="studio5-project-shade"></div>
                </div>
                <div class="studio5-project-body">
                    <div class="studio5-project-title">${esc(project.title)}</div>
                    <div class="studio5-project-meta">${esc(meta)}</div>
                    <div class="studio5-project-foot">
                        <span>${project.track_count || 0} ${Number(project.track_count) === 1 ? "track" : "tracks"}</span>
                        <span>${fmtDate(project.updated_at)}</span>
                    </div>
                </div>
            </article>
        `;
    }

    function renderLibrary() {
        state.project = null;
        sessionStorage.removeItem("apollo.studio.project");
        stage.className = "studio5-stage studio5-enter";
        stage.innerHTML = `
            <section class="studio5-library-head">
                <div>
                    <div class="studio5-section-kicker">Projects</div>
                    <h2>Your work</h2>
                </div>
                <div class="studio5-library-count">${state.projects.length} ${state.projects.length === 1 ? "project" : "projects"}</div>
            </section>
            ${state.projects.length ? `
                <div class="studio5-project-grid">
                    ${state.projects.map(libraryCard).join("")}
                </div>
            ` : `
                <div class="studio5-empty studio5-empty-large">
                    <div class="studio5-empty-icon">${icon("wave")}</div>
                    <h3>Start something worth keeping.</h3>
                    <p>Create a Single, EP or Album. Studio will keep the tracks, versions, notes and references together.</p>
                    <button class="studio5-primary" type="button" data-new-project>${icon("plus")}<span>New Project</span></button>
                </div>
            `}
        `;
    }

    function trackMeta(track) {
        return [
            track.bpm ? `${track.bpm} BPM` : null,
            track.musical_key || null,
            `${track.versions?.length || 0} ${(track.versions?.length || 0) === 1 ? "version" : "versions"}`
        ].filter(Boolean).join(" · ");
    }

    function compactTrackRow(track, index, project) {
        const version = primaryVersion(track);
        const url = playableUrl(version);
        return `
            <div class="studio5-track-row" data-track-id="${track.id}">
                <div class="studio5-track-index">${String(track.track_number ?? index + 1).padStart(2, "0")}</div>
                <button class="studio5-track-play" type="button" ${url ? `data-play-version="${version.id}" data-track-id="${track.id}"` : "disabled"} aria-label="Play ${esc(track.title)}">${icon(state.playingVersionId === version?.id && !audio.paused ? "pause" : "play")}</button>
                <div class="studio5-track-copy">
                    <div class="studio5-track-title">${esc(track.title)}</div>
                    <div class="studio5-track-meta">${esc(trackMeta(track))}</div>
                </div>
                <div class="studio5-track-version" data-runtime-url="${url ? esc(url) : ""}">${version ? esc(displayVersionLabel(version)) : "No audio yet"}${url ? '<span class="studio5-track-runtime"> · --:--</span>' : ""}</div>
                <button class="studio5-row-more" type="button" data-track-menu="${track.id}" aria-label="Track actions">${icon("more")}</button>
            </div>
        `;
    }

    function overviewMarkup(project) {
        const notes = (project.notes || []).slice(0, 3);
        const media = (project.media || []).slice(0, 6);
        return `
            <div class="studio5-overview-grid">
                <section class="studio5-panel studio5-panel-tracks">
                    <div class="studio5-panel-head">
                        <div>
                            <div class="studio5-section-kicker">In the room</div>
                            <h3>${project.tracks.length === 1 ? "Track" : "Tracklist"}</h3>
                        </div>
                        <button class="studio5-text-action" type="button" data-add-track>${icon("plus")}<span>Add track</span></button>
                    </div>
                    <div class="studio5-tracklist">
                        ${project.tracks.length ? project.tracks.map((track, index) => compactTrackRow(track, index, project)).join("") : `
                            <button class="studio5-empty-line" type="button" data-add-track>${icon("plus")}<span>Add the first track</span></button>
                        `}
                    </div>
                </section>

                <section class="studio5-panel studio5-panel-notes">
                    <div class="studio5-panel-head">
                        <div>
                            <div class="studio5-section-kicker">Notes</div>
                            <h3>Recent thoughts</h3>
                        </div>
                        <button class="studio5-text-action" type="button" data-add-note>${icon("plus")}<span>New note</span></button>
                    </div>
                    <div class="studio5-note-stack">
                        ${notes.length ? notes.map(note => `
                            <button class="studio5-note-mini" type="button" data-edit-note="${note.id}">
                                <span class="studio5-note-kind">${esc(note.kind || "general")}</span>
                                ${note.title ? `<strong>${esc(note.title)}</strong>` : ""}
                                <span>${esc(note.body)}</span>
                            </button>
                        `).join("") : `
                            <button class="studio5-empty-line" type="button" data-add-note>${icon("plus")}<span>Write down what matters</span></button>
                        `}
                    </div>
                </section>

                <section class="studio5-panel studio5-panel-world">
                    <div class="studio5-panel-head">
                        <div>
                            <div class="studio5-section-kicker">World</div>
                            <h3>References & media</h3>
                        </div>
                        <button class="studio5-text-action" type="button" data-add-media>${icon("plus")}<span>Add media</span></button>
                    </div>
                    ${media.length ? `<div class="studio5-world-strip">${media.map(mediaThumb).join("")}</div>` : `
                        <button class="studio5-empty-world" type="button" data-add-media>
                            <span>${icon("image")}</span>
                            <div><strong>Build the project's world.</strong><small>Artwork, references, PDFs, images, video, audio and links.</small></div>
                        </button>
                    `}
                </section>
            </div>
        `;
    }

    function versionRow(version, track) {
        const isPrimary = Boolean(version.is_current);
        const ext = String(version.audio_name || "").split(".").pop()?.toUpperCase() || "AUDIO";
        return `
            <div class="studio5-version-row ${isPrimary ? "is-primary" : ""}" data-version-id="${version.id}">
                <button class="studio5-version-play" type="button" data-play-version="${version.id}" data-track-id="${track.id}" aria-label="Play ${esc(displayVersionLabel(version))}">${icon(state.playingVersionId === version.id && !audio.paused ? "pause" : "play")}</button>
                <div class="studio5-version-copy">
                    <div class="studio5-version-title">${esc(displayVersionLabel(version))}${isPrimary ? '<span class="studio5-primary-dot" title="Primary version"></span>' : ""}</div>
                    <div class="studio5-version-meta">${esc(ext)}${version.notes ? ` · ${esc(version.notes)}` : ""}</div>
                </div>
                <div class="studio5-version-date">${fmtDate(version.updated_at || version.created_at)}</div>
                <button class="studio5-row-more" type="button" data-version-menu="${version.id}" aria-label="Version actions">${icon("more")}</button>
            </div>
        `;
    }


    function compactTrackMeta(track) {

        const parts = [];

        const bpm =
            Number(track?.bpm);

        if (
            Number.isFinite(bpm)
            && bpm > 0
        ) {
            parts.push(
                `${Math.round(bpm)} BPM`
            );
        }

        if (track?.musical_key) {
            parts.push(
                String(track.musical_key)
            );
        }

        return parts.join(
            " · "
        );

    }

    function tracksMarkup(project) {
        return `
            <section class="studio5-section-page">
                <div class="studio5-page-head">
                    <div><div class="studio5-section-kicker">Tracks</div><h3>${project.tracks.length ? `${project.tracks.length} ${project.tracks.length === 1 ? "track" : "tracks"}` : "No tracks yet"}</h3></div>
                    <button class="studio5-primary studio5-primary-small" type="button" data-add-track>${icon("plus")}<span>Add Track</span></button>
                </div>
                <div class="studio5-track-cards">
                    ${project.tracks.length ? project.tracks.map((track, index) => {
                        const expanded = state.expandedTracks.has(track.id);
                        const version = primaryVersion(track);
                        return `
                            <article class="studio5-track-card ${expanded ? "is-expanded" : ""}" data-track-id="${track.id}">
                                <div class="studio5-track-card-head">
                                    <div class="studio5-track-card-number">${String(track.track_number ?? index + 1).padStart(2, "0")}</div>
                                    <button class="studio5-track-play studio5-track-play-large" type="button" ${version && playableUrl(version) ? `data-play-version="${version.id}" data-track-id="${track.id}"` : "disabled"}>${icon(state.playingVersionId === version?.id && !audio.paused ? "pause" : "play")}</button>
                                    <button class="studio5-track-card-main" type="button" data-toggle-track="${track.id}">
                                        <strong>${esc(track.title)}</strong>
                                        ${(() => {
                                            const meta =
                                                compactTrackMeta(track);

                                            return meta
                                                ? `<span>${esc(meta)}</span>`
                                                : "";
                                        })()}
                                    </button>
                                    
                                    <button class="studio5-row-more" type="button" data-track-menu="${track.id}">${icon("more")}</button>
                                </div>
                                <div class="studio5-track-card-body">
                                    <div class="studio5-version-head"><span>Versions</span><button type="button" class="studio5-text-action" data-add-version="${track.id}">${icon("plus")}<span>Add version</span></button></div>
                                    <div class="studio5-version-list">
                                        ${track.versions?.length ? track.versions.map(version => versionRow(version, track)).join("") : `<button class="studio5-empty-line" type="button" data-add-version="${track.id}">${icon("plus")}<span>Upload the first version</span></button>`}
                                    </div>
                                </div>
                            </article>
                        `;
                    }).join("") : `<div class="studio5-empty"><div class="studio5-empty-icon">${icon("wave")}</div><h3>No tracks yet.</h3><p>Add the first song, demo or idea to this project.</p><button class="studio5-primary studio5-primary-small" type="button" data-add-track>${icon("plus")}<span>Add Track</span></button></div>`}
                </div>
            </section>
        `;
    }

    function noteCard(note, index) {
        return `
            <article class="studio5-note-card" style="--i:${index}">
                <div class="studio5-note-card-top"><span>${esc(note.kind || "general")}</span><button type="button" class="studio5-row-more" data-note-menu="${note.id}">${icon("more")}</button></div>
                ${note.title ? `<h4>${esc(note.title)}</h4>` : ""}
                <p>${esc(note.body)}</p>
                <div class="studio5-note-date">${fmtDate(note.updated_at || note.created_at)}</div>
            </article>
        `;
    }

    function notesMarkup(project) {
        return `
            <section class="studio5-section-page">
                <div class="studio5-page-head"><div><div class="studio5-section-kicker">Notes</div><h3>Thoughts, lyrics, mix notes and ideas</h3></div><button class="studio5-primary studio5-primary-small" type="button" data-add-note>${icon("plus")}<span>New Note</span></button></div>
                ${project.notes?.length ? `<div class="studio5-notes-grid">${project.notes.map(noteCard).join("")}</div>` : `<div class="studio5-empty"><div class="studio5-empty-icon">${icon("file")}</div><h3>Nothing written down yet.</h3><p>Keep lyrics, production thoughts, mix notes and visual ideas attached to the project.</p><button class="studio5-primary studio5-primary-small" type="button" data-add-note>${icon("plus")}<span>New Note</span></button></div>`}
            </section>
        `;
    }

    function mediaThumb(item) {
        const target = item.external_url || item.file_url || "#";
        if (item.media_type === "image" && item.file_url) {
            return `<a class="studio5-media-thumb is-image" href="${esc(target)}" target="_blank" rel="noopener"><img src="${esc(item.file_url)}" alt=""><span>${esc(item.title || item.file_name || "Image")}</span></a>`;
        }
        return `<a class="studio5-media-thumb" href="${esc(target)}" target="_blank" rel="noopener"><div>${item.media_type === "link" ? icon("link") : icon("file")}</div><span>${esc(item.title || item.file_name || "Reference")}</span></a>`;
    }

    function mediaCard(item, index) {
        const target = item.external_url || item.file_url || "#";
        const isImage = item.media_type === "image" && item.file_url;

        const visual = isImage
            ? `<div class="studio5-media-visual"><img src="${esc(item.file_url)}" alt=""></div>`
            : `<div class="studio5-media-visual studio5-media-glyph">${item.media_type === "link" ? icon("link") : icon("file")}<span>${esc(String(item.media_type || "file").toUpperCase())}</span></div>`;

        if (isImage) {
            return `
                <article class="studio5-media-card is-image" style="--i:${index}">
                    <a href="${esc(target)}" target="_blank" rel="noopener">${visual}</a>
                    <button
                        type="button"
                        class="studio5-row-more studio5-media-more"
                        data-media-menu="${item.id}"
                        aria-label="Media actions"
                    >${icon("more")}</button>
                </article>
            `;
        }

        return `
            <article class="studio5-media-card" style="--i:${index}">
                <a href="${esc(target)}" target="_blank" rel="noopener">${visual}</a>
                <div class="studio5-media-body">
                    <div>
                        <strong>${esc(item.title || item.file_name || "Untitled")}</strong>
                        <span>${esc(item.file_name || item.external_url || item.media_type || "")}</span>
                    </div>
                    <button type="button" class="studio5-row-more" data-media-menu="${item.id}">${icon("more")}</button>
                </div>
            </article>
        `;
    }

    function worldMarkup(project) {
        return `
            <section class="studio5-section-page">
                <div class="studio5-page-head"><div><div class="studio5-section-kicker">World</div><h3>Everything around the music</h3></div><div class="studio5-page-actions"><button class="studio5-ghost" type="button" data-add-link>${icon("link")}<span>Add Link</span></button><button class="studio5-primary studio5-primary-small" type="button" data-add-media>${icon("plus")}<span>Add Media</span></button></div></div>
                ${project.media?.length ? `<div class="studio5-media-grid">${project.media.map(mediaCard).join("")}</div>` : `<div class="studio5-empty studio5-world-empty" data-drop-media><div class="studio5-empty-icon">${icon("image")}</div><h3>Build the project's world.</h3><p>Drop in artwork, references, PDFs, images, video, audio, documents — or save a link.</p><div class="studio5-empty-actions"><button class="studio5-primary studio5-primary-small" type="button" data-add-media>${icon("plus")}<span>Add Media</span></button><button class="studio5-ghost" type="button" data-add-link>${icon("link")}<span>Add Link</span></button></div></div>`}
            </section>
        `;
    }

    function renderProject() {
        const project = state.project;
        if (!project) return renderLibrary();
        const firstTrack = project.tracks?.[0] || null;
        const firstVersion = primaryVersion(firstTrack);
        const tabs = [
            ["overview", "Overview"],
            ["tracks", "Tracks"],
            ["notes", "Notes"],
            ["world", "World"]
        ];
        stage.className = "studio5-stage studio5-enter";
        stage.innerHTML = `
            <button class="studio5-back" type="button" data-back-library>${icon("back")}<span>All projects</span></button>
            <section class="studio5-hero">
                <div class="studio5-hero-art">${artworkMarkup(project)}</div>
                <div class="studio5-hero-copy">
                    <div class="studio5-hero-meta"><span>${esc(fmtType(project.project_type))}</span><i></i><span>${esc(fmtStatus(project.status))}</span>${project.updated_at ? `<i></i><span>Updated ${esc(fmtDate(project.updated_at))}</span>` : ""}</div>
                    <h2>${esc(project.title)}</h2>
                    <p>${project.description ? esc(project.description) : "Add a short concept so the project has a point of view."}</p>
                    <div class="studio5-hero-actions">
                        ${firstVersion && playableUrl(firstVersion) ? `<button class="studio5-primary studio5-play-primary" type="button" data-play-version="${firstVersion.id}" data-track-id="${firstTrack.id}">${icon(state.playingVersionId === firstVersion.id && !audio.paused ? "pause" : "play")}<span>${state.playingVersionId === firstVersion.id && !audio.paused ? "Pause" : "Play"}</span></button>` : ""}
                        <button class="studio5-ghost" type="button" data-project-ask>Ask Apollo</button>
                        <button class="studio5-icon-action" type="button" data-project-menu aria-label="Project actions">${icon("more")}</button>
                    </div>
                </div>
            </section>
            <nav class="studio5-tabs">${tabs.map(([id, label]) => `<button type="button" class="${state.tab === id ? "active" : ""}" data-tab="${id}">${label}${id === "tracks" ? `<span>${project.tracks?.length || 0}</span>` : id === "notes" ? `<span>${project.notes?.length || 0}</span>` : id === "world" ? `<span>${project.media?.length || 0}</span>` : ""}</button>`).join("")}</nav>
            <div class="studio5-tab-content">
                ${state.tab === "overview" ? overviewMarkup(project) : state.tab === "tracks" ? tracksMarkup(project) : state.tab === "notes" ? notesMarkup(project) : worldMarkup(project)}
            </div>
        `;
    }

    async function refreshProject() {
        if (!state.project?.id) return;
        await loadProject(state.project.id);
        renderProject();
        await loadProjects();
    }

    function openMenu(anchor, items) {
        document.querySelectorAll(".studio5-menu").forEach(el => el.remove());
        const rect = anchor.getBoundingClientRect();
        const menu = document.createElement("div");
        menu.className = "studio5-menu";
        menu.innerHTML = items.map(item => item.separator ? '<div class="studio5-menu-separator"></div>' : `<button type="button" ${item.danger ? 'class="danger"' : ""} data-menu-action="${esc(item.id)}">${esc(item.label)}</button>`).join("");
        document.body.appendChild(menu);
        const width = 180;
        const left = Math.min(window.innerWidth - width - 12, Math.max(12, rect.right - width));
        const top = Math.min(window.innerHeight - menu.offsetHeight - 12, rect.bottom + 7);
        menu.style.left = `${left}px`;
        menu.style.top = `${top}px`;
        const close = () => menu.remove();
        const outside = event => { if (!menu.contains(event.target) && event.target !== anchor) { close(); document.removeEventListener("pointerdown", outside, true); } };
        document.addEventListener("pointerdown", outside, true);
        menu.addEventListener("click", async event => {
            const button = event.target.closest("[data-menu-action]");
            if (!button) return;
            const item = items.find(x => x.id === button.dataset.menuAction);
            close();
            document.removeEventListener("pointerdown", outside, true);
            if (item?.run) await item.run();
        });
    }

    function formModal({title, subtitle = "", fields = [], submitLabel = "Save", danger = false, onSubmit}) {
        const id = `studio5-modal-${Date.now()}`;
        const fieldMarkup = field => {
            const value = field.value ?? "";
            if (field.type === "textarea") return `<label class="studio5-field"><span>${esc(field.label)}</span><textarea name="${esc(field.name)}" placeholder="${esc(field.placeholder || "")}">${esc(value)}</textarea></label>`;
            if (field.type === "select") return `<label class="studio5-field"><span>${esc(field.label)}</span><select name="${esc(field.name)}">${field.options.map(opt => `<option value="${esc(opt.value)}" ${String(opt.value) === String(value) ? "selected" : ""}>${esc(opt.label)}</option>`).join("")}</select></label>`;
            return `<label class="studio5-field"><span>${esc(field.label)}</span><input type="${esc(field.type || "text")}" name="${esc(field.name)}" value="${field.type === "file" ? "" : esc(value)}" placeholder="${esc(field.placeholder || "")}" ${field.accept ? `accept="${esc(field.accept)}"` : ""} ${field.multiple ? "multiple" : ""}></label>`;
        };
        modalRoot.innerHTML = `
            <div class="studio5-modal-backdrop" id="${id}">
                <div class="studio5-modal-card" role="dialog" aria-modal="true">
                    <div class="studio5-modal-head"><div><h3>${esc(title)}</h3>${subtitle ? `<p>${esc(subtitle)}</p>` : ""}</div><button type="button" data-modal-close>×</button></div>
                    <form>${fields.map(fieldMarkup).join("")}<div class="studio5-modal-foot"><button type="button" class="studio5-ghost" data-modal-close>Cancel</button><button type="submit" class="${danger ? "studio5-danger" : "studio5-primary studio5-primary-small"}">${esc(submitLabel)}</button></div></form>
                </div>
            </div>
        `;
        const backdrop = document.getElementById(id);
        const form = backdrop.querySelector("form");
        const close = () => { modalRoot.innerHTML = ""; };
        backdrop.addEventListener("click", event => { if (event.target === backdrop || event.target.closest("[data-modal-close]")) close(); });
        form.addEventListener("submit", async event => {
            event.preventDefault();
            const submit = form.querySelector('[type="submit"]');
            submit.disabled = true;
            try {
                const data = Object.fromEntries(new FormData(form).entries());
                await onSubmit(data, form);
                close();
            } catch (error) {
                submit.disabled = false;
                showToast(error.message || "Studio action failed", true);
            }
        });
        requestAnimationFrame(() => backdrop.querySelector("input, textarea, select")?.focus());
    }

    function confirmModal({title, body, confirmLabel = "Delete", onConfirm}) {
        formModal({
            title,
            subtitle: body,
            fields: [],
            submitLabel: confirmLabel,
            danger: true,
            onSubmit: onConfirm
        });
    }

    function showToast(message, error = false) {
        document.querySelectorAll(".studio5-toast").forEach(el => el.remove());
        const toast = document.createElement("div");
        toast.className = `studio5-toast${error ? " is-error" : ""}`;
        toast.textContent = message;
        document.body.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add("visible"));
        setTimeout(() => { toast.classList.remove("visible"); setTimeout(() => toast.remove(), 220); }, 2200);
    }

    function newProject() {
        formModal({
            title: "New project",
            subtitle: "Start with the container. Add tracks and versions when you're ready.",
            fields: [
                {name: "title", label: "Name", placeholder: "Untitled project"},
                {name: "project_type", label: "Type", type: "select", value: "single", options: [{value:"single",label:"Single"},{value:"ep",label:"EP"},{value:"album",label:"Album"},{value:"other",label:"Other"}]},
                {name: "status", label: "Stage", type: "select", value: "idea", options: [{value:"idea",label:"Idea"},{value:"writing",label:"Writing"},{value:"recording",label:"Recording"},{value:"mixing",label:"Mixing"},{value:"finished",label:"Finished"},{value:"released",label:"Released"}]},
                {name: "description", label: "Concept", type: "textarea", placeholder: "What is this project trying to feel like?"},
                {name: "artwork", label: "Artwork", type: "file", accept: ".jpg,.jpeg,.png,.webp,.gif"}
            ],
            submitLabel: "Create Project",
            onSubmit: async (values, form) => {
                const result = await postJSON("/api/studio/projects/create", {title: values.title, project_type: values.project_type, status: values.status, description: values.description});
                const file = form.querySelector('[name="artwork"]')?.files?.[0];
                if (file) {
                    const fd = new FormData(); fd.append("project_id", result.project_id); fd.append("artwork", file);
                    await api("/api/studio/projects/artwork", {method: "POST", body: fd});
                }
                await loadProjects();
                await loadProject(result.project_id);
                state.tab = "overview";
                renderProject();
                showToast("Project created");
            }
        });
    }

    function editProject() {
        const project = state.project;
        formModal({
            title: "Project details",
            fields: [
                {name: "title", label: "Name", value: project.title},
                {name: "project_type", label: "Type", type: "select", value: project.project_type, options: [{value:"single",label:"Single"},{value:"ep",label:"EP"},{value:"album",label:"Album"},{value:"other",label:"Other"}]},
                {name: "status", label: "Stage", type: "select", value: project.status, options: [{value:"idea",label:"Idea"},{value:"writing",label:"Writing"},{value:"recording",label:"Recording"},{value:"mixing",label:"Mixing"},{value:"finished",label:"Finished"},{value:"released",label:"Released"},{value:"in_progress",label:"In progress"}]},
                {name: "description", label: "Concept", type: "textarea", value: project.description || ""}
            ],
            onSubmit: async values => { await postJSON("/api/studio/projects/update", {project_id: project.id, ...values}); await refreshProject(); showToast("Project updated"); }
        });
    }

    function changeArtwork() {
        formModal({
            title: "Project artwork",
            fields: [{name:"artwork",label:"Image",type:"file",accept:".jpg,.jpeg,.png,.webp,.gif"}],
            submitLabel: "Use Artwork",
            onSubmit: async (_, form) => {
                const file = form.querySelector('[name="artwork"]')?.files?.[0];
                if (!file) throw new Error("Choose an image");
                const fd = new FormData(); fd.append("project_id", state.project.id); fd.append("artwork", file);
                await api("/api/studio/projects/artwork", {method:"POST", body:fd});
                await refreshProject(); showToast("Artwork updated");
            }
        });
    }


    async function uploadStudioVersionChunked({
        trackId,
        file,
        label = "",
        notes = "",
        onProgress = null
    }) {

        if (!file) {
            throw new Error(
                "Choose an audio file"
            );
        }


        const started =
            await postJSON(
                "/api/studio/versions/upload/start",
                {
                    track_id:
                        trackId,

                    filename:
                        file.name,

                    size:
                        file.size,

                    label:
                        label || "",

                    notes:
                        notes || ""
                }
            );


        const uploadId =
            started.upload_id;


        const chunkSize =
            Number(
                started.chunk_size
            )
            || (
                2
                * 1024
                * 1024
            );


        if (!uploadId) {
            throw new Error(
                "Apollo couldn't start the upload"
            );
        }


        let offset = 0;


        try {

            while (
                offset
                < file.size
            ) {

                const end =
                    Math.min(
                        file.size,
                        offset
                        + chunkSize
                    );


                const blob =
                    file.slice(
                        offset,
                        end
                    );


                const result =
                    await api(
                        "/api/studio/versions/upload/chunk",
                        {
                            method:
                                "POST",

                            headers: {
                                "Content-Type":
                                    "application/octet-stream",

                                "X-Apollo-Upload-ID":
                                    uploadId,

                                "X-Apollo-Upload-Offset":
                                    String(
                                        offset
                                    )
                            },

                            body:
                                blob
                        }
                    );


                offset =
                    Number(
                        result.received
                    );


                if (
                    !Number.isFinite(
                        offset
                    )
                    || offset <= 0
                ) {
                    throw new Error(
                        "Upload stopped unexpectedly"
                    );
                }


                if (
                    typeof onProgress
                    === "function"
                ) {

                    onProgress(
                        Math.min(
                            99,
                            Math.round(
                                (
                                    offset
                                    / file.size
                                )
                                * 100
                            )
                        )
                    );

                }

            }


            const finished =
                await postJSON(
                    "/api/studio/versions/upload/finish",
                    {
                        upload_id:
                            uploadId
                    }
                );


            if (
                typeof onProgress
                === "function"
            ) {
                onProgress(
                    100
                );
            }


            return finished;

        }
        catch (error) {

            try {

                await postJSON(
                    "/api/studio/versions/upload/abort",
                    {
                        upload_id:
                            uploadId
                    }
                );

            }
            catch (_) {}


            throw error;

        }

    }


    function addTrack() {

        formModal({

            title: "Add track",

            subtitle:
                "Add the song and its first playable version.",

            fields: [

                {
                    name:
                        "title",

                    label:
                        "Track name",

                    placeholder:
                        "Untitled track"
                },

                {
                    name:
                        "audio",

                    label:
                        "Audio",

                    type:
                        "file",

                    accept:
                        ".wav,.mp3,.flac,.m4a,.aac"
                },

                {
                    name:
                        "version_label",

                    label:
                        "Version",

                    placeholder:
                        "First mix"
                },

                {
                    name:
                        "bpm",

                    label:
                        "BPM",

                    type:
                        "number"
                },

                {
                    name:
                        "musical_key",

                    label:
                        "Key",

                    placeholder:
                        "F minor"
                }

            ],

            submitLabel:
                "Add Track",

            onSubmit:
                async (
                    values,
                    form
                ) => {

                    const file =
                        form.querySelector(
                            '[name="audio"]'
                        )
                        ?.files?.[0];


                    if (!file) {

                        throw new Error(
                            "Choose an audio file"
                        );

                    }


                    /*
                     * If the user leaves the track name blank,
                     * use the audio filename instead.
                     */
                    const inferredTitle =
                        file.name
                            .replace(
                                /\.[^.]+$/,
                                ""
                            )
                            .trim();


                    const title =
                        String(
                            values.title
                            || ""
                        ).trim()
                        || inferredTitle
                        || "Untitled track";


                    let trackId =
                        null;


                    try {

                        /*
                         * 1. Create the track container.
                         */
                        const result =
                            await postJSON(
                                "/api/studio/tracks/create",
                                {
                                    project_id:
                                        state.project.id,

                                    title,

                                    bpm:
                                        values.bpm
                                        || "",

                                    musical_key:
                                        values.musical_key
                                        || ""
                                }
                            );


                        trackId =
                            result.track_id;


                        if (!trackId) {

                            throw new Error(
                                "Apollo couldn't create the track"
                            );

                        }


                        /*
                         * 2. Upload the actual audio as
                         *    the track's first version.
                         */
                        const submit =
                            form.querySelector(
                                '[type="submit"]'
                            );


                        await uploadStudioVersionChunked(
                            {
                                trackId,

                                file,

                                label:
                                    String(
                                        values.version_label
                                        || ""
                                    ).trim()
                                    || "First mix",

                                notes:
                                    "",

                                onProgress:
                                    progress => {

                                        if (!submit) {
                                            return;
                                        }


                                        submit.textContent =
                                            progress >= 100
                                                ? "Finishing…"
                                                : (
                                                    "Uploading "
                                                    + progress
                                                    + "%"
                                                );

                                    }
                            }
                        );


                        /*
                         * Open the new track immediately.
                         */
                        state.expandedTracks.add(
                            trackId
                        );


                        state.tab =
                            "tracks";


                        await refreshProject();


                        showToast(
                            "Track added"
                        );

                    }
                    catch (error) {

                        /*
                         * Don't leave an empty track behind if
                         * the audio upload failed.
                         */
                        if (trackId) {

                            try {

                                await postJSON(
                                    "/api/studio/tracks/delete",
                                    {
                                        track_id:
                                            trackId
                                    }
                                );

                            }
                            catch (_) {}

                        }


                        throw error;

                    }

                }

        });

    }

    function editTrack(track) {
        formModal({
            title: "Track details",
            fields: [{name:"title",label:"Track name",value:track.title},{name:"track_number",label:"Track number",type:"number",value:track.track_number ?? ""},{name:"bpm",label:"BPM",type:"number",value:track.bpm ?? ""},{name:"musical_key",label:"Key",value:track.musical_key || ""}],
            onSubmit: async values => { await postJSON("/api/studio/tracks/update", {track_id: track.id, ...values}); await refreshProject(); showToast("Track updated"); }
        });
    }

    function addVersion(track) {
        formModal({
            title: `Add version — ${track.title}`,
            fields: [{name:"label",label:"Version name",placeholder:"v2, final, car test..."},{name:"audio",label:"Audio",type:"file",accept:".wav,.mp3,.flac,.m4a,.aac"},{name:"notes",label:"Version note",type:"textarea",placeholder:"What changed in this version?"}],
            submitLabel: "Upload Version",
            onSubmit: async (values, form) => {
                const file = form.querySelector('[name="audio"]')?.files?.[0];
                if (!file) throw new Error("Choose an audio file");
                const submit =
                    form.querySelector(
                        '[type="submit"]'
                    );


                await uploadStudioVersionChunked(
                    {
                        trackId:
                            track.id,

                        file,

                        label:
                            values.label
                            || "",

                        notes:
                            values.notes
                            || "",

                        onProgress:
                            progress => {

                                if (!submit) {
                                    return;
                                }


                                submit.textContent =
                                    progress >= 100
                                        ? "Finishing…"
                                        : (
                                            "Uploading "
                                            + progress
                                            + "%"
                                        );

                            }
                    }
                );
                state.expandedTracks.add(track.id); await refreshProject(); showToast("Version uploaded");
            }
        });
    }

    function editVersion(version) {
        formModal({
            title: "Version details",
            fields: [{name:"label",label:"Name",value:displayVersionLabel(version)},{name:"notes",label:"Notes",type:"textarea",value:version.notes || ""}],
            onSubmit: async values => { await postJSON("/api/studio/versions/update", {version_id: version.id, ...values}); await refreshProject(); showToast("Version updated"); }
        });
    }

    function addNote() {
        formModal({
            title: "New note",
            fields: [{name:"kind",label:"Type",type:"select",value:"general",options:[{value:"general",label:"General"},{value:"lyrics",label:"Lyrics"},{value:"production",label:"Production"},{value:"mix",label:"Mix"},{value:"visual",label:"Visual"},{value:"idea",label:"Idea"}]},{name:"title",label:"Title",placeholder:"Optional"},{name:"body",label:"Note",type:"textarea",placeholder:"Write it down before it disappears."}],
            submitLabel: "Add Note",
            onSubmit: async values => { await postJSON("/api/studio/notes/create", {project_id:state.project.id, ...values}); await refreshProject(); showToast("Note added"); }
        });
    }

    function editNote(note) {
        formModal({
            title: "Edit note",
            fields: [{name:"kind",label:"Type",type:"select",value:note.kind,options:[{value:"general",label:"General"},{value:"lyrics",label:"Lyrics"},{value:"production",label:"Production"},{value:"mix",label:"Mix"},{value:"visual",label:"Visual"},{value:"idea",label:"Idea"}]},{name:"title",label:"Title",value:note.title || ""},{name:"body",label:"Note",type:"textarea",value:note.body}],
            onSubmit: async values => { await postJSON("/api/studio/notes/update", {note_id:note.id, ...values}); await refreshProject(); showToast("Note updated"); }
        });
    }

    function addMedia() {
        formModal({
            title: "Add media",
            subtitle: "Artwork, screenshots, PDFs, documents, audio, video — anything that belongs to the project's world.",
            fields: [{name:"title",label:"Title",placeholder:"Optional"},{name:"file",label:"File",type:"file"},{name:"notes",label:"Notes",type:"textarea"}],
            submitLabel: "Add Media",
            onSubmit: async (values, form) => {
                const file = form.querySelector('[name="file"]')?.files?.[0];
                if (!file) throw new Error("Choose a file");
                const fd = new FormData(); fd.append("project_id", state.project.id); fd.append("title", values.title || ""); fd.append("notes", values.notes || ""); fd.append("file", file);
                await api("/api/studio/media/upload", {method:"POST", body:fd}); await refreshProject(); showToast("Media added");
            }
        });
    }

    function addLink() {
        formModal({
            title: "Add reference link",
            fields: [{name:"title",label:"Title",placeholder:"Reference"},{name:"url",label:"URL",placeholder:"https://..."},{name:"notes",label:"Notes",type:"textarea"}],
            submitLabel: "Add Link",
            onSubmit: async values => { await postJSON("/api/studio/media/link", {project_id:state.project.id, ...values}); await refreshProject(); showToast("Link added"); }
        });
    }

    function editMedia(item) {
        formModal({
            title: "Media details",
            fields: [{name:"title",label:"Title",value:item.title || ""},{name:"url",label:"URL",value:item.external_url || "",placeholder:item.external_url ? "https://..." : "Only used for links"},{name:"notes",label:"Notes",type:"textarea",value:item.notes || ""}],
            onSubmit: async values => { await postJSON("/api/studio/media/update", {media_id:item.id, ...values}); await refreshProject(); showToast("Media updated"); }
        });
    }

    async function playVersion(track, version, projectForArt = state.project) {
        const url = playableUrl(version);
        if (!url) return showToast("This version has no playable audio", true);
        if (state.playingVersionId === version.id && state.source === url) {
            if (audio.paused) await audio.play().catch(() => {}); else audio.pause();
            syncPlaybackUI();
            return;
        }
        state.source = url;
        state.playingTrackId = track.id;
        state.playingVersionId = version.id;
        audio.src = url;
        transportTitle.textContent = track.title;
        transportSub.textContent = displayVersionLabel(version);
        const art = projectArtwork(projectForArt);
        transportArt.innerHTML = art ? `<img src="${esc(art)}" alt="">` : icon("wave");
        transport.classList.add("visible");
        transport.setAttribute("aria-hidden", "false");
        audio.load();
        await audio.play().catch(() => {});
        syncPlaybackUI();
    }

    function syncPlaybackUI() {
        const playing = !audio.paused && !audio.ended;
        transportToggle.innerHTML = icon(playing ? "pause" : "play");
        transportToggle.setAttribute("aria-label", playing ? "Pause" : "Play");
        const duration = Number(audio.duration);
        const current = Number(audio.currentTime);
        const ratio = Number.isFinite(duration) && duration > 0 ? current / duration : 0;
        const value = Math.max(0, Math.min(1000, Math.round(ratio * 1000)));
        transportRange.value = String(value);
        transportRange.style.setProperty("--progress", `${value / 10}%`);
        transportTime.textContent = `${fmtTime(current)} / ${fmtTime(duration)}`;
        view.querySelectorAll('[data-play-version]').forEach(button => {
            const id = Number(button.dataset.playVersion);
            if (id === state.playingVersionId) button.innerHTML = icon(playing ? "pause" : "play");
            else button.innerHTML = icon("play");
        });
    }

    function askApollo(project = state.project) {
        if (project) {
            window.apolloPendingStudioContext = {
                project_id: project.id,
                title: project.title,
                project_type: project.project_type,
                status: project.status,
                description: project.description,
                tracks: (project.tracks || []).map(track => ({id:track.id,title:track.title,track_number:track.track_number,bpm:track.bpm,musical_key:track.musical_key,versions:(track.versions||[]).map(version => ({id:version.id,label:displayVersionLabel(version),is_primary:Boolean(version.is_current),notes:version.notes}))})),
                notes: project.notes || [],
                media: (project.media || []).map(item => ({id:item.id,type:item.media_type,title:item.title,url:item.external_url || item.file_url || null,notes:item.notes || null}))
            };
        } else {
            window.apolloPendingStudioContext = {scope:"studio",projects:state.projects.map(project => ({id:project.id,title:project.title,type:project.project_type,status:project.status}))};
        }
        if (typeof window.openApollo === "function") window.openApollo();
        setTimeout(() => {
            if (typeof apolloInput !== "undefined" && apolloInput) {
                apolloInput.value = "";
                apolloInput.placeholder = project ? `Ask about ${project.title}...` : "Ask Apollo about Studio...";
                apolloInput.focus();
            }
        }, 240);
    }

    stage.addEventListener("click", async event => {
        const button = event.target.closest("button, [data-open-project]");
        if (!button) return;
        if (button.matches("[data-open-project]") && !event.target.closest("button")) {
            setBusy(true); try { await loadProject(button.dataset.openProject); state.tab = sessionStorage.getItem("apollo.studio.tab") || "overview"; renderProject(); } finally { setBusy(false); }
            return;
        }
        if (button.matches("[data-play-project]")) {
            event.stopPropagation();
            setBusy(true); try { const data = await api(`/api/studio/projects/${button.dataset.playProject}`); const project = data.project; const track = project.tracks?.[0]; const version = primaryVersion(track); if (!track || !version) return showToast("No playable track yet", true); await playVersion(track, version, project); } finally { setBusy(false); }
            return;
        }
        if (button.matches("[data-back-library]")) { await loadProjects(); renderLibrary(); return; }
        if (button.matches("[data-tab]")) { state.tab = button.dataset.tab; sessionStorage.setItem("apollo.studio.tab", state.tab); renderProject(); return; }
        if (button.matches("[data-play-version]")) {
            const track = state.project?.tracks?.find(t => Number(t.id) === Number(button.dataset.trackId));
            const version = track?.versions?.find(v => Number(v.id) === Number(button.dataset.playVersion));
            if (track && version) await playVersion(track, version);
            return;
        }
        if (button.matches("[data-toggle-track]")) { const id = Number(button.dataset.toggleTrack); if (state.expandedTracks.has(id)) state.expandedTracks.delete(id); else state.expandedTracks.add(id); renderProject(); return; }
        if (button.matches("[data-add-track]")) return addTrack();
        if (button.matches("[data-add-version]")) { const track = state.project.tracks.find(t => Number(t.id) === Number(button.dataset.addVersion)); if (track) addVersion(track); return; }
        if (button.matches("[data-add-note]")) return addNote();
        if (button.matches("[data-add-media]")) return addMedia();
        if (button.matches("[data-add-link]")) return addLink();
        if (button.matches("[data-edit-note]")) { const note = state.project.notes.find(n => Number(n.id) === Number(button.dataset.editNote)); if (note) editNote(note); return; }
        if (button.matches("[data-project-ask]")) return askApollo(state.project);
        if (button.matches("[data-project-menu]")) {
            openMenu(button, [
                {id:"edit",label:"Edit project",run:editProject},
                {id:"art",label:"Change artwork",run:changeArtwork},
                {separator:true},
                {id:"delete",label:"Delete project",danger:true,run:() => confirmModal({title:"Delete project?",body:"This removes the project from Studio. Legacy source files are preserved for migrated WIPs.",onConfirm:async()=>{await postJSON("/api/studio/projects/delete",{project_id:state.project.id}); state.project=null; await loadProjects(); renderLibrary(); showToast("Project deleted");}})}
            ]); return;
        }
        if (button.matches("[data-track-menu]")) {
            const track = state.project.tracks.find(t => Number(t.id) === Number(button.dataset.trackMenu)); if (!track) return;
            openMenu(button, [
                {id:"edit",label:"Edit track",run:()=>editTrack(track)},
                {id:"version",label:"Add version",run:()=>addVersion(track)},
                {separator:true},
                {id:"delete",label:"Delete track",danger:true,run:()=>confirmModal({title:"Delete track?",body:`Delete ${track.title} and its Studio versions?`,onConfirm:async()=>{await postJSON("/api/studio/tracks/delete",{track_id:track.id}); await refreshProject(); showToast("Track deleted");}})}
            ]); return;
        }
        if (button.matches("[data-version-menu]")) {
            let version = null, track = null;
            for (const t of state.project.tracks) { const found = t.versions?.find(v => Number(v.id) === Number(button.dataset.versionMenu)); if (found) { version = found; track = t; break; } }
            if (!version) return;
            const items = [
                {id:"edit",label:"Edit version",run:()=>editVersion(version)}
            ];
            if (!version.is_current) items.push({id:"primary",label:"Use as primary mix",run:async()=>{await postJSON("/api/studio/versions/current",{version_id:version.id}); await refreshProject(); showToast("Primary mix updated");}});
            if (version.original_audio_url) items.push({id:"open",label:"Open original file",run:()=>window.open(version.original_audio_url,"_blank","noopener")});
            items.push({separator:true},{id:"delete",label:"Delete version",danger:true,run:()=>confirmModal({title:"Delete version?",body:`Delete ${displayVersionLabel(version)} from ${track.title}?`,onConfirm:async()=>{await postJSON("/api/studio/versions/delete",{version_id:version.id}); await refreshProject(); showToast("Version deleted");}})});
            openMenu(button, items); return;
        }
        if (button.matches("[data-note-menu]")) {
            const note = state.project.notes.find(n => Number(n.id) === Number(button.dataset.noteMenu)); if (!note) return;
            openMenu(button,[{id:"edit",label:"Edit note",run:()=>editNote(note)},{separator:true},{id:"delete",label:"Delete note",danger:true,run:()=>confirmModal({title:"Delete note?",body:"This note will be removed from the project.",onConfirm:async()=>{await postJSON("/api/studio/notes/delete",{note_id:note.id});await refreshProject();showToast("Note deleted");}})}]); return;
        }
        if (button.matches("[data-media-menu]")) {
            const item = state.project.media.find(m => Number(m.id) === Number(button.dataset.mediaMenu)); if (!item) return;
            openMenu(button,[{id:"edit",label:"Edit details",run:()=>editMedia(item)},{separator:true},{id:"delete",label:"Remove media",danger:true,run:()=>confirmModal({title:"Remove media?",body:"The item will be removed from this project.",onConfirm:async()=>{await postJSON("/api/studio/media/delete",{media_id:item.id});await refreshProject();showToast("Media removed");}})}]); return;
        }
    });

    view.addEventListener("click", event => {
        if (event.target.closest("[data-new-project]")) newProject();
        if (event.target.closest("[data-studio-ask]")) askApollo(state.project);
    });

    transportToggle.addEventListener("click", async () => { if (!state.source) return; if (audio.paused) await audio.play().catch(()=>{}); else audio.pause(); syncPlaybackUI(); });
    transportRange.addEventListener("input", () => { const duration = Number(audio.duration); if (!Number.isFinite(duration) || duration <= 0) return; audio.currentTime = Number(transportRange.value)/1000*duration; syncPlaybackUI(); });
    transportClose.addEventListener("click", () => { audio.pause(); transport.classList.remove("visible"); transport.setAttribute("aria-hidden","true"); });
    ["play","pause","ended","timeupdate","loadedmetadata","durationchange"].forEach(name => audio.addEventListener(name, syncPlaybackUI));

    view.addEventListener("dragover", event => { if (!state.project) return; event.preventDefault(); view.classList.add("is-dragging"); });
    view.addEventListener("dragleave", event => { if (!view.contains(event.relatedTarget)) view.classList.remove("is-dragging"); });
    view.addEventListener("drop", async event => {
        if (!state.project) return;
        event.preventDefault(); view.classList.remove("is-dragging");
        const files = Array.from(event.dataTransfer?.files || []);
        if (!files.length) return;
        setBusy(true);
        try {
            for (const file of files) {
                const fd = new FormData(); fd.append("project_id", state.project.id); fd.append("title", ""); fd.append("notes", ""); fd.append("file", file);
                await api("/api/studio/media/upload", {method:"POST",body:fd});
            }
            await refreshProject(); state.tab = "world"; renderProject(); showToast(files.length === 1 ? "Media added" : `${files.length} files added`);
        } catch (error) { showToast(error.message || "Upload failed", true); }
        finally { setBusy(false); }
    });

    const previousOpenStudio = window.openStudio;
    window.openStudio = function(...args) {
        const result = typeof previousOpenStudio === "function" ? previousOpenStudio.apply(this,args) : undefined;
        requestAnimationFrame(async () => {
            try {
                setBusy(true);
                await loadProjects();
                const saved = sessionStorage.getItem("apollo.studio.project");
                if (saved && state.projects.some(project => String(project.id) === String(saved))) {
                    await loadProject(saved);
                    state.tab = sessionStorage.getItem("apollo.studio.tab") || "overview";
                    renderProject();
                } else {
                    renderLibrary();
                }
            } catch (error) {
                stage.innerHTML = `<div class="studio5-empty"><h3>Studio couldn't load.</h3><p>${esc(error.message || "Try again in a moment.")}</p></div>`;
            } finally { setBusy(false); }
        });
        return result;
    };

    (async () => {
        try {
            await loadProjects();
            const saved = sessionStorage.getItem("apollo.studio.project");
            if (saved && state.projects.some(project => String(project.id) === String(saved))) {
                await loadProject(saved);
                state.tab = sessionStorage.getItem("apollo.studio.tab") || "overview";
                renderProject();
            } else renderLibrary();
        } catch (error) {
            stage.innerHTML = `<div class="studio5-empty"><h3>Studio couldn't load.</h3><p>${esc(error.message || "Try again in a moment.")}</p></div>`;
        }
    })();
})();



/* ==========================================================
   APOLLO STUDIO V5 — TRACK RUNTIMES + AUTO-NEXT V1
   ========================================================== */

(() => {

    const runtimePromises = new Map();


    function formatRuntime(seconds) {

        seconds = Number(seconds);

        if (
            !Number.isFinite(seconds)
            || seconds < 0
        ) {
            return "";
        }

        const minutes =
            Math.floor(seconds / 60);

        const secs =
            Math.floor(seconds % 60);

        return (
            minutes
            + ":"
            + String(secs).padStart(2, "0")
        );

    }


    function getRuntime(url) {

        if (runtimePromises.has(url)) {
            return runtimePromises.get(url);
        }

        const promise =
            new Promise(resolve => {

                const probe =
                    new Audio();

                let finished = false;


                function finish(value) {

                    if (finished) {
                        return;
                    }

                    finished = true;

                    probe.removeAttribute(
                        "src"
                    );

                    try {
                        probe.load();
                    }
                    catch (_) {}

                    resolve(value);

                }


                probe.preload =
                    "metadata";


                probe.addEventListener(
                    "loadedmetadata",
                    () => {

                        const duration =
                            Number(
                                probe.duration
                            );

                        finish(
                            Number.isFinite(duration)
                                ? duration
                                : null
                        );

                    },
                    {
                        once: true
                    }
                );


                probe.addEventListener(
                    "error",
                    () => finish(null),
                    {
                        once: true
                    }
                );


                probe.src =
                    url;

            });


        runtimePromises.set(
            url,
            promise
        );

        return promise;

    }


    async function hydrateRuntime(element) {

        if (
            element.dataset
                .runtimeHydrating === "1"
        ) {
            return;
        }

        const url =
            element.dataset.runtimeUrl;

        const runtime =
            element.querySelector(
                ".studio5-track-runtime"
            );

        if (
            !url
            || !runtime
        ) {
            return;
        }

        element.dataset
            .runtimeHydrating = "1";


        const duration =
            await getRuntime(url);


        if (!element.isConnected) {
            return;
        }


        const formatted =
            formatRuntime(duration);


        runtime.textContent =
            formatted
                ? " · " + formatted
                : "";

    }


    function hydrateRuntimes() {

        document
            .querySelectorAll(
                ".studio5-track-version[data-runtime-url]"
            )
            .forEach(
                hydrateRuntime
            );

    }


    /*
     * Runtime styling:
     * keep it attached to "First mix" without adding
     * another visual column to the tracklist.
     */
    if (
        !document.getElementById(
            "studio5RuntimeStyle"
        )
    ) {

        const style =
            document.createElement(
                "style"
            );

        style.id =
            "studio5RuntimeStyle";

        style.textContent = `
            .studio5-track-runtime {
                font-variant-numeric:
                    tabular-nums;
                opacity: .78;
                white-space: nowrap;
            }
        `;

        document.head.appendChild(
            style
        );

    }


    const runtimeRoot =
        document.getElementById(
            "studioView"
        )
        || document.body;


    const runtimeObserver =
        new MutationObserver(
            hydrateRuntimes
        );


    runtimeObserver.observe(
        runtimeRoot,
        {
            childList: true,
            subtree: true
        }
    );


    hydrateRuntimes();


    /*
     * Remember which project track owns the currently
     * playing version.
     *
     * Capture phase means this runs before Studio's
     * normal playback handler.
     */
    document.addEventListener(
        "click",
        event => {

            const button =
                event.target.closest(
                    "[data-play-version][data-track-id]"
                );

            if (!button) {
                return;
            }

            const audio =
                document.getElementById(
                    "studio5Audio"
                );

            if (!audio) {
                return;
            }

            audio.dataset.apolloTrackId =
                button.dataset.trackId
                || "";

        },
        true
    );


    function orderedTrackButtons() {

        const buttons =
            document.querySelectorAll(
                [
                    ".studio5-track-row .studio5-track-play[data-play-version][data-track-id]",
                    ".studio5-track-card .studio5-track-play[data-play-version][data-track-id]"
                ].join(",")
            );


        const seen =
            new Set();

        const ordered = [];


        buttons.forEach(
            button => {

                const trackId =
                    button.dataset.trackId;

                if (
                    !trackId
                    || seen.has(trackId)
                ) {
                    return;
                }

                seen.add(trackId);

                ordered.push(
                    button
                );

            }
        );


        return ordered;

    }


    function bindAutoNext() {

        const audio =
            document.getElementById(
                "studio5Audio"
            );


        if (
            !audio
            || audio.dataset
                .apolloAutoNextReady === "1"
        ) {
            return;
        }


        audio.dataset
            .apolloAutoNextReady = "1";


        audio.addEventListener(
            "ended",
            () => {

                const currentTrackId =
                    audio.dataset
                        .apolloTrackId;

                if (!currentTrackId) {
                    return;
                }


                const tracks =
                    orderedTrackButtons();


                const currentIndex =
                    tracks.findIndex(
                        button =>
                            button.dataset.trackId
                            === currentTrackId
                    );


                if (
                    currentIndex < 0
                    || currentIndex
                        >= tracks.length - 1
                ) {
                    return;
                }


                const next =
                    tracks[
                        currentIndex + 1
                    ];


                if (!next) {
                    return;
                }


                audio.dataset.apolloTrackId =
                    next.dataset.trackId
                    || "";


                requestAnimationFrame(
                    () => {
                        next.click();
                    }
                );

            }
        );

    }


    bindAutoNext();


    /*
     * Defensive bind in case Studio recreates its
     * transport/audio element later.
     */
    const audioObserver =
        new MutationObserver(
            bindAutoNext
        );


    audioObserver.observe(
        document.body,
        {
            childList: true,
            subtree: true
        }
    );

})();
