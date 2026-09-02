from pathlib import Path
import mimetypes
import shutil
import uuid


_db = None
_wip_dir = None
_ensure_playback = None
_read_multipart = None


def configure(
    db_factory,
    wip_dir,
    ensure_playback,
    read_multipart,
):
    global _db
    global _wip_dir
    global _ensure_playback
    global _read_multipart

    _db = db_factory
    _wip_dir = Path(wip_dir)
    _ensure_playback = ensure_playback
    _read_multipart = read_multipart


def _conn():
    if _db is None:
        raise RuntimeError("Studio backend is not configured")
    return _db()


def _clean(value):
    return str(value or "").strip()


def _project(project_id):
    conn = _conn()

    row = conn.execute(
        """
        SELECT *
        FROM studio_projects
        WHERE id = ?
        """,
        (int(project_id),),
    ).fetchone()

    conn.close()

    if not row:
        raise ValueError("Studio project not found")

    return dict(row)


def _track(track_id):
    conn = _conn()

    row = conn.execute(
        """
        SELECT *
        FROM studio_tracks
        WHERE id = ?
        """,
        (int(track_id),),
    ).fetchone()

    conn.close()

    if not row:
        raise ValueError("Studio track not found")

    return dict(row)


def _version(version_id):
    conn = _conn()

    row = conn.execute(
        """
        SELECT
            v.*,
            t.project_id
        FROM studio_versions v
        JOIN studio_tracks t
            ON t.id = v.track_id
        WHERE v.id = ?
        """,
        (int(version_id),),
    ).fetchone()

    conn.close()

    if not row:
        raise ValueError("Studio version not found")

    return dict(row)


def _studio_project_dir(project_id):
    folder = (
        _wip_dir
        / "studio"
        / f"project-{int(project_id)}"
    )

    folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    return folder


def _safe_unlink(path):
    if not path:
        return

    try:
        candidate = Path(path).resolve()
        studio_root = (
            _wip_dir
            / "studio"
        ).resolve()

        candidate.relative_to(studio_root)

        if candidate.is_file():
            candidate.unlink(missing_ok=True)

    except Exception:
        pass


# =========================================================
# PROJECTS
# =========================================================

def create_project(data):
    title = _clean(data.get("title"))

    if not title:
        raise ValueError("Project name is required")

    project_type = _clean(
        data.get("project_type")
        or "single"
    ).lower()

    if project_type not in {
        "single",
        "ep",
        "album",
        "other",
    }:
        project_type = "other"

    status = _clean(
        data.get("status")
        or "idea"
    ).lower()

    allowed_statuses = {
        "idea",
        "writing",
        "recording",
        "mixing",
        "finished",
        "released",
        "in_progress",
    }

    if status not in allowed_statuses:
        status = "idea"

    description = _clean(
        data.get("description")
    ) or None

    conn = _conn()

    cursor = conn.execute(
        """
        INSERT INTO studio_projects (
            title,
            project_type,
            status,
            description
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            title,
            project_type,
            status,
            description,
        ),
    )

    project_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "project_id": project_id,
    }


def update_project(data):
    project_id = int(data.get("project_id"))

    existing = _project(project_id)

    title = _clean(
        data.get("title")
        if "title" in data
        else existing.get("title")
    )

    if not title:
        raise ValueError("Project name is required")

    project_type = _clean(
        data.get("project_type")
        if "project_type" in data
        else existing.get("project_type")
    ).lower()

    if project_type not in {
        "single",
        "ep",
        "album",
        "other",
    }:
        project_type = "other"

    status = _clean(
        data.get("status")
        if "status" in data
        else existing.get("status")
    ).lower()

    description = (
        _clean(data.get("description"))
        if "description" in data
        else existing.get("description")
    )

    description = description or None

    conn = _conn()

    conn.execute(
        """
        UPDATE studio_projects

        SET
            title = ?,
            project_type = ?,
            status = ?,
            description = ?,
            updated_at = CURRENT_TIMESTAMP

        WHERE id = ?
        """,
        (
            title,
            project_type,
            status,
            description,
            project_id,
        ),
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "project_id": project_id,
    }


def delete_project(data):
    project_id = int(data.get("project_id"))

    project = _project(project_id)

    conn = _conn()

    version_paths = conn.execute(
        """
        SELECT v.audio_path
        FROM studio_versions v
        JOIN studio_tracks t
            ON t.id = v.track_id
        WHERE t.project_id = ?
        """,
        (project_id,),
    ).fetchall()

    media_paths = conn.execute(
        """
        SELECT file_path
        FROM studio_media
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchall()

    conn.execute(
        """
        DELETE FROM studio_versions
        WHERE track_id IN (
            SELECT id
            FROM studio_tracks
            WHERE project_id = ?
        )
        """,
        (project_id,),
    )

    conn.execute(
        "DELETE FROM studio_notes WHERE project_id = ?",
        (project_id,),
    )

    conn.execute(
        "DELETE FROM studio_media WHERE project_id = ?",
        (project_id,),
    )

    conn.execute(
        "DELETE FROM studio_tracks WHERE project_id = ?",
        (project_id,),
    )

    conn.execute(
        "DELETE FROM studio_projects WHERE id = ?",
        (project_id,),
    )

    conn.commit()
    conn.close()

    # Never remove legacy WIP files.
    if not project.get("legacy_wip_id"):

        for row in version_paths:
            _safe_unlink(row["audio_path"])

        for row in media_paths:
            _safe_unlink(row["file_path"])

        try:
            folder = (
                _wip_dir
                / "studio"
                / f"project-{project_id}"
            )

            if folder.exists():
                shutil.rmtree(folder)

        except Exception:
            pass

    return {
        "ok": True,
        "project_id": project_id,
    }


def upload_artwork(handler):
    fields, files = _read_multipart(handler)

    project_id = int(
        fields.get("project_id")
    )

    project = _project(project_id)

    artwork = files.get("artwork")

    if not artwork:
        raise ValueError("Choose an image")

    original_name = (
        artwork.get("filename")
        or "artwork"
    )

    ext = (
        Path(original_name)
        .suffix
        .lower()
    )

    allowed = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }

    if ext not in allowed:
        raise ValueError(
            "Artwork must be JPG, PNG, WebP, or GIF"
        )

    folder = (
        _studio_project_dir(project_id)
        / "artwork"
    )

    folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        folder
        / (
            uuid.uuid4().hex
            + ext
        )
    )

    path.write_bytes(
        artwork["data"]
    )

    conn = _conn()

    conn.execute(
        """
        UPDATE studio_projects

        SET
            artwork_name = ?,
            artwork_path = ?,
            artwork_mime = ?,
            updated_at = CURRENT_TIMESTAMP

        WHERE id = ?
        """,
        (
            original_name,
            str(path),
            allowed[ext],
            project_id,
        ),
    )

    conn.commit()
    conn.close()

    old_path = project.get(
        "artwork_path"
    )

    if (
        old_path
        and not project.get(
            "legacy_wip_id"
        )
    ):
        _safe_unlink(old_path)

    return {
        "ok": True,
        "project_id": project_id,
    }


# =========================================================
# TRACKS
# =========================================================

def create_track(data):
    project_id = int(
        data.get("project_id")
    )

    _project(project_id)

    title = _clean(
        data.get("title")
    )

    if not title:
        raise ValueError("Track name is required")

    bpm = data.get("bpm")
    musical_key = _clean(
        data.get("musical_key")
    ) or None

    conn = _conn()

    next_number = conn.execute(
        """
        SELECT
            COALESCE(
                MAX(track_number),
                0
            ) + 1 AS n

        FROM studio_tracks
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()["n"]

    track_number = (
        int(data.get("track_number"))
        if data.get("track_number")
        not in (None, "")
        else int(next_number)
    )

    cursor = conn.execute(
        """
        INSERT INTO studio_tracks (
            project_id,
            title,
            track_number,
            bpm,
            musical_key
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            project_id,
            title,
            track_number,
            (
                float(bpm)
                if bpm not in (None, "")
                else None
            ),
            musical_key,
        ),
    )

    track_id = cursor.lastrowid

    conn.execute(
        """
        UPDATE studio_projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (project_id,),
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "project_id": project_id,
        "track_id": track_id,
    }


def update_track(data):
    track_id = int(
        data.get("track_id")
    )

    existing = _track(track_id)

    title = _clean(
        data.get("title")
        if "title" in data
        else existing.get("title")
    )

    if not title:
        raise ValueError("Track name is required")

    bpm = (
        data.get("bpm")
        if "bpm" in data
        else existing.get("bpm")
    )

    musical_key = (
        _clean(data.get("musical_key"))
        if "musical_key" in data
        else existing.get("musical_key")
    )

    musical_key = musical_key or None

    track_number = (
        data.get("track_number")
        if "track_number" in data
        else existing.get("track_number")
    )

    conn = _conn()

    conn.execute(
        """
        UPDATE studio_tracks

        SET
            title = ?,
            track_number = ?,
            bpm = ?,
            musical_key = ?,
            updated_at = CURRENT_TIMESTAMP

        WHERE id = ?
        """,
        (
            title,
            (
                int(track_number)
                if track_number
                not in (None, "")
                else None
            ),
            (
                float(bpm)
                if bpm not in (None, "")
                else None
            ),
            musical_key,
            track_id,
        ),
    )

    conn.execute(
        """
        UPDATE studio_projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (existing["project_id"],),
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "project_id":
            existing["project_id"],
        "track_id":
            track_id,
    }


def delete_track(data):
    track_id = int(
        data.get("track_id")
    )

    track = _track(track_id)

    conn = _conn()

    version_rows = conn.execute(
        """
        SELECT
            audio_path,
            legacy_wip_id
        FROM studio_versions
        WHERE track_id = ?
        """,
        (track_id,),
    ).fetchall()

    conn.execute(
        "DELETE FROM studio_versions WHERE track_id = ?",
        (track_id,),
    )

    conn.execute(
        "DELETE FROM studio_notes WHERE track_id = ?",
        (track_id,),
    )

    conn.execute(
        "DELETE FROM studio_media WHERE track_id = ?",
        (track_id,),
    )

    conn.execute(
        "DELETE FROM studio_tracks WHERE id = ?",
        (track_id,),
    )

    conn.execute(
        """
        UPDATE studio_projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (track["project_id"],),
    )

    conn.commit()
    conn.close()

    for row in version_rows:
        if not row["legacy_wip_id"]:
            _safe_unlink(
                row["audio_path"]
            )

    return {
        "ok": True,
        "project_id":
            track["project_id"],
    }


# =========================================================
# VERSIONS
# =========================================================

def upload_version(handler):
    fields, files = _read_multipart(handler)

    track_id = int(
        fields.get("track_id")
    )

    track = _track(track_id)

    audio = files.get("audio")

    if not audio:
        raise ValueError("Choose an audio file")

    original_name = (
        audio.get("filename")
        or "audio"
    )

    ext = (
        Path(original_name)
        .suffix
        .lower()
    )

    allowed = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
    }

    if ext not in allowed:
        raise ValueError(
            "Audio must be WAV, MP3, FLAC, M4A, or AAC"
        )

    folder = (
        _studio_project_dir(
            track["project_id"]
        )
        / "tracks"
        / f"track-{track_id}"
    )

    folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        folder
        / (
            uuid.uuid4().hex
            + ext
        )
    )

    path.write_bytes(
        audio["data"]
    )

    conn = _conn()

    count = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM studio_versions
        WHERE track_id = ?
        """,
        (track_id,),
    ).fetchone()["n"]

    label = (
        _clean(fields.get("label"))
        or f"Version {int(count) + 1}"
    )

    notes = (
        _clean(fields.get("notes"))
        or None
    )

    conn.execute(
        """
        UPDATE studio_versions
        SET is_current = 0
        WHERE track_id = ?
        """,
        (track_id,),
    )

    cursor = conn.execute(
        """
        INSERT INTO studio_versions (
            track_id,
            label,
            audio_name,
            audio_path,
            audio_mime,
            notes,
            is_current
        )
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (
            track_id,
            label,
            original_name,
            str(path),
            allowed[ext],
            notes,
        ),
    )

    version_id = cursor.lastrowid

    conn.execute(
        """
        UPDATE studio_tracks
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (track_id,),
    )

    conn.execute(
        """
        UPDATE studio_projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (track["project_id"],),
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "project_id":
            track["project_id"],
        "track_id":
            track_id,
        "version_id":
            version_id,
    }


def update_version(data):
    version_id = int(
        data.get("version_id")
    )

    existing = _version(version_id)

    label = (
        _clean(data.get("label"))
        if "label" in data
        else existing.get("label")
    )

    if not label:
        label = "Version"

    notes = (
        _clean(data.get("notes"))
        if "notes" in data
        else existing.get("notes")
    )

    notes = notes or None

    conn = _conn()

    conn.execute(
        """
        UPDATE studio_versions
        SET
            label = ?,
            notes = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            label,
            notes,
            version_id,
        ),
    )

    conn.execute(
        """
        UPDATE studio_projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (existing["project_id"],),
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "project_id":
            existing["project_id"],
    }


def set_current_version(data):
    version_id = int(
        data.get("version_id")
    )

    existing = _version(version_id)

    conn = _conn()

    conn.execute(
        """
        UPDATE studio_versions
        SET is_current = 0
        WHERE track_id = ?
        """,
        (existing["track_id"],),
    )

    conn.execute(
        """
        UPDATE studio_versions
        SET
            is_current = 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (version_id,),
    )

    conn.execute(
        """
        UPDATE studio_projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (existing["project_id"],),
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "project_id":
            existing["project_id"],
    }


def delete_version(data):
    version_id = int(
        data.get("version_id")
    )

    existing = _version(version_id)

    conn = _conn()

    conn.execute(
        """
        DELETE FROM studio_versions
        WHERE id = ?
        """,
        (version_id,),
    )

    if existing.get("is_current"):

        replacement = conn.execute(
            """
            SELECT id
            FROM studio_versions
            WHERE track_id = ?
            ORDER BY
                updated_at DESC,
                id DESC
            LIMIT 1
            """,
            (existing["track_id"],),
        ).fetchone()

        if replacement:

            conn.execute(
                """
                UPDATE studio_versions
                SET is_current = 1
                WHERE id = ?
                """,
                (replacement["id"],),
            )

    conn.execute(
        """
        UPDATE studio_projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (existing["project_id"],),
    )

    conn.commit()
    conn.close()

    if not existing.get(
        "legacy_wip_id"
    ):
        _safe_unlink(
            existing.get(
                "audio_path"
            )
        )

    return {
        "ok": True,
        "project_id":
            existing["project_id"],
    }


# =========================================================
# NOTES
# =========================================================

def create_note(data):
    project_id = int(
        data.get("project_id")
    )

    _project(project_id)

    track_id = data.get(
        "track_id"
    )

    if track_id in (
        "",
        None,
    ):
        track_id = None
    else:
        track_id = int(track_id)
        track = _track(track_id)

        if (
            int(track["project_id"])
            != project_id
        ):
            raise ValueError(
                "Track does not belong to project"
            )

    body = _clean(
        data.get("body")
    )

    if not body:
        raise ValueError("Note cannot be empty")

    kind = (
        _clean(data.get("kind"))
        or "general"
    ).lower()

    if kind not in {
        "general",
        "lyrics",
        "production",
        "mix",
        "visual",
        "idea",
    }:
        kind = "general"

    title = (
        _clean(data.get("title"))
        or None
    )

    conn = _conn()

    cursor = conn.execute(
        """
        INSERT INTO studio_notes (
            project_id,
            track_id,
            kind,
            title,
            body
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            project_id,
            track_id,
            kind,
            title,
            body,
        ),
    )

    note_id = cursor.lastrowid

    conn.execute(
        """
        UPDATE studio_projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (project_id,),
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "project_id":
            project_id,
        "note_id":
            note_id,
    }


def update_note(data):
    note_id = int(
        data.get("note_id")
    )

    conn = _conn()

    existing = conn.execute(
        """
        SELECT *
        FROM studio_notes
        WHERE id = ?
        """,
        (note_id,),
    ).fetchone()

    if not existing:
        conn.close()
        raise ValueError(
            "Studio note not found"
        )

    existing = dict(existing)

    body = (
        _clean(data.get("body"))
        if "body" in data
        else existing.get("body")
    )

    if not body:
        conn.close()
        raise ValueError(
            "Note cannot be empty"
        )

    title = (
        _clean(data.get("title"))
        if "title" in data
        else existing.get("title")
    )

    title = title or None

    kind = (
        _clean(data.get("kind"))
        if "kind" in data
        else existing.get("kind")
    ) or "general"

    conn.execute(
        """
        UPDATE studio_notes

        SET
            title = ?,
            body = ?,
            kind = ?,
            updated_at = CURRENT_TIMESTAMP

        WHERE id = ?
        """,
        (
            title,
            body,
            kind,
            note_id,
        ),
    )

    conn.execute(
        """
        UPDATE studio_projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (existing["project_id"],),
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "project_id":
            existing["project_id"],
    }


def delete_note(data):
    note_id = int(
        data.get("note_id")
    )

    conn = _conn()

    existing = conn.execute(
        """
        SELECT project_id
        FROM studio_notes
        WHERE id = ?
        """,
        (note_id,),
    ).fetchone()

    if not existing:
        conn.close()
        raise ValueError(
            "Studio note not found"
        )

    project_id = existing[
        "project_id"
    ]

    conn.execute(
        """
        DELETE FROM studio_notes
        WHERE id = ?
        """,
        (note_id,),
    )

    conn.execute(
        """
        UPDATE studio_projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (project_id,),
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "project_id":
            project_id,
    }


# =========================================================
# MEDIA
# =========================================================

def _media_type(
    mime,
    filename,
):
    mime = _clean(mime).lower()

    if mime.startswith("image/"):
        return "image"

    if mime.startswith("audio/"):
        return "audio"

    if mime.startswith("video/"):
        return "video"

    suffix = (
        Path(filename or "")
        .suffix
        .lower()
    )

    if suffix in {
        ".pdf",
        ".doc",
        ".docx",
        ".txt",
        ".rtf",
        ".md",
        ".pages",
    }:
        return "document"

    return "file"


def upload_media(handler):
    fields, files = _read_multipart(handler)

    project_id = int(
        fields.get("project_id")
    )

    _project(project_id)

    track_id = fields.get(
        "track_id"
    )

    if track_id in (
        "",
        None,
    ):
        track_id = None
    else:
        track_id = int(track_id)

    upload = files.get("file")

    if not upload:
        raise ValueError("Choose a file")

    original_name = (
        upload.get("filename")
        or "file"
    )

    ext = (
        Path(original_name)
        .suffix
    )

    mime = (
        upload.get("content_type")
        or mimetypes.guess_type(
            original_name
        )[0]
        or "application/octet-stream"
    )

    folder = (
        _studio_project_dir(
            project_id
        )
        / "media"
    )

    folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        folder
        / (
            uuid.uuid4().hex
            + ext
        )
    )

    path.write_bytes(
        upload["data"]
    )

    media_type = _media_type(
        mime,
        original_name,
    )

    title = (
        _clean(fields.get("title"))
        or Path(
            original_name
        ).stem
    )

    notes = (
        _clean(fields.get("notes"))
        or None
    )

    conn = _conn()

    cursor = conn.execute(
        """
        INSERT INTO studio_media (
            project_id,
            track_id,
            media_type,
            title,
            file_name,
            file_path,
            file_mime,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            track_id,
            media_type,
            title,
            original_name,
            str(path),
            mime,
            notes,
        ),
    )

    media_id = cursor.lastrowid

    conn.execute(
        """
        UPDATE studio_projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (project_id,),
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "project_id":
            project_id,
        "media_id":
            media_id,
    }


def create_media_link(data):
    project_id = int(
        data.get("project_id")
    )

    _project(project_id)

    url = _clean(
        data.get("url")
    )

    if not url:
        raise ValueError("URL is required")

    title = (
        _clean(data.get("title"))
        or url
    )

    notes = (
        _clean(data.get("notes"))
        or None
    )

    track_id = data.get(
        "track_id"
    )

    track_id = (
        int(track_id)
        if track_id
        not in (None, "")
        else None
    )

    conn = _conn()

    cursor = conn.execute(
        """
        INSERT INTO studio_media (
            project_id,
            track_id,
            media_type,
            title,
            external_url,
            notes
        )
        VALUES (?, ?, 'link', ?, ?, ?)
        """,
        (
            project_id,
            track_id,
            title,
            url,
            notes,
        ),
    )

    media_id = cursor.lastrowid

    conn.execute(
        """
        UPDATE studio_projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (project_id,),
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "project_id":
            project_id,
        "media_id":
            media_id,
    }


def update_media(data):
    media_id = int(
        data.get("media_id")
    )

    conn = _conn()

    existing = conn.execute(
        """
        SELECT *
        FROM studio_media
        WHERE id = ?
        """,
        (media_id,),
    ).fetchone()

    if not existing:
        conn.close()
        raise ValueError(
            "Studio media not found"
        )

    existing = dict(existing)

    title = (
        _clean(data.get("title"))
        if "title" in data
        else existing.get("title")
    )

    title = title or None

    notes = (
        _clean(data.get("notes"))
        if "notes" in data
        else existing.get("notes")
    )

    notes = notes or None

    external_url = (
        _clean(data.get("url"))
        if "url" in data
        else existing.get("external_url")
    )

    external_url = (
        external_url
        or None
    )

    conn.execute(
        """
        UPDATE studio_media

        SET
            title = ?,
            external_url = ?,
            notes = ?,
            updated_at = CURRENT_TIMESTAMP

        WHERE id = ?
        """,
        (
            title,
            external_url,
            notes,
            media_id,
        ),
    )

    conn.execute(
        """
        UPDATE studio_projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (existing["project_id"],),
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "project_id":
            existing["project_id"],
    }


def delete_media(data):
    media_id = int(
        data.get("media_id")
    )

    conn = _conn()

    existing = conn.execute(
        """
        SELECT *
        FROM studio_media
        WHERE id = ?
        """,
        (media_id,),
    ).fetchone()

    if not existing:
        conn.close()
        raise ValueError(
            "Studio media not found"
        )

    existing = dict(existing)

    conn.execute(
        """
        DELETE FROM studio_media
        WHERE id = ?
        """,
        (media_id,),
    )

    conn.execute(
        """
        UPDATE studio_projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (existing["project_id"],),
    )

    conn.commit()
    conn.close()

    _safe_unlink(
        existing.get(
            "file_path"
        )
    )

    return {
        "ok": True,
        "project_id":
            existing["project_id"],
    }

# =========================================================
# APOLLO STUDIO — CHUNKED AUDIO UPLOAD V2
# =========================================================

import json as _studio_json
import time as _studio_time


def _studio_upload_root():

    root = (
        _wip_dir
        / ".studio_uploads"
    )

    root.mkdir(
        parents=True,
        exist_ok=True
    )

    return root


def _studio_upload_folder(
    upload_id
):

    upload_id = _clean(
        upload_id
    ).lower()


    if (
        len(upload_id) != 32
        or not all(
            char in
            "0123456789abcdef"
            for char in upload_id
        )
    ):
        raise ValueError(
            "Invalid upload"
        )


    return (
        _studio_upload_root()
        / upload_id
    )


def _studio_audio_info(
    filename
):

    filename = (
        Path(
            _clean(filename)
        ).name
    )


    extension = (
        Path(filename)
        .suffix
        .lower()
    )


    allowed = {
        ".wav":
            "audio/wav",

        ".mp3":
            "audio/mpeg",

        ".flac":
            "audio/flac",

        ".m4a":
            "audio/mp4",

        ".aac":
            "audio/aac"
    }


    if extension not in allowed:

        raise ValueError(
            "Audio must be WAV, MP3, FLAC, M4A, or AAC"
        )


    return (
        filename,
        extension,
        allowed[
            extension
        ]
    )


def studio_version_upload_start(
    data
):

    track_id = int(
        data.get(
            "track_id"
        )
    )


    track = _track(
        track_id
    )


    (
        filename,
        extension,
        mime
    ) = _studio_audio_info(
        data.get(
            "filename"
        )
    )


    try:

        size = int(
            data.get(
                "size"
            )
        )

    except Exception:

        raise ValueError(
            "Invalid audio size"
        )


    if size <= 0:

        raise ValueError(
            "Audio file is empty"
        )


    if size > (
        700
        * 1024
        * 1024
    ):

        raise ValueError(
            "Audio file is too large"
        )


    label = (
        _clean(
            data.get(
                "label"
            )
        )
        or "First mix"
    )


    notes = (
        _clean(
            data.get(
                "notes"
            )
        )
        or None
    )


    # Remove abandoned uploads older than a day.


    root = _studio_upload_root()

    cutoff = (
        _studio_time.time()
        - 86400
    )


    for candidate in root.iterdir():

        try:

            if (
                candidate.is_dir()
                and candidate.stat().st_mtime
                < cutoff
            ):

                shutil.rmtree(
                    candidate
                )

        except Exception:

            pass


    upload_id = (
        uuid.uuid4().hex
    )


    folder = (
        root
        / upload_id
    )


    folder.mkdir(
        parents=True,
        exist_ok=False
    )


    metadata = {
        "track_id":
            track_id,

        "project_id":
            int(
                track[
                    "project_id"
                ]
            ),

        "filename":
            filename,

        "extension":
            extension,

        "mime":
            mime,

        "size":
            size,

        "label":
            label,

        "notes":
            notes,

        "created_at":
            _studio_time.time()
    }


    (
        folder
        / "meta.json"
    ).write_text(
        _studio_json.dumps(
            metadata
        ),
        encoding="utf-8"
    )


    (
        folder
        / "audio.part"
    ).touch()


    return {
        "ok":
            True,

        "upload_id":
            upload_id,

        # Keep each request comfortably below the legacy
        # uploader's 8 MB ceiling.
        "chunk_size":
            2
            * 1024
            * 1024
    }


def studio_version_upload_chunk(
    handler
):

    upload_id = (
        handler.headers.get(
            "X-Apollo-Upload-ID",
            ""
        )
    )


    try:

        offset = int(
            handler.headers.get(
                "X-Apollo-Upload-Offset",
                "0"
            )
        )

    except Exception:

        raise ValueError(
            "Invalid upload offset"
        )


    folder = (
        _studio_upload_folder(
            upload_id
        )
    )


    metadata_path = (
        folder
        / "meta.json"
    )


    part_path = (
        folder
        / "audio.part"
    )


    if (
        not metadata_path.exists()
        or not part_path.exists()
    ):

        raise ValueError(
            "Upload not found"
        )


    metadata = _studio_json.loads(
        metadata_path.read_text(
            encoding="utf-8"
        )
    )


    expected_size = int(
        metadata[
            "size"
        ]
    )


    current_size = (
        part_path.stat()
        .st_size
    )


    if offset != current_size:

        raise ValueError(
            "Unexpected upload offset"
        )


    try:

        length = int(
            handler.headers.get(
                "Content-Length",
                "0"
            )
        )

    except Exception:

        raise ValueError(
            "Invalid chunk size"
        )


    if (
        length <= 0
        or length
        > (
            4
            * 1024
            * 1024
        )
    ):

        raise ValueError(
            "Invalid chunk size"
        )


    if (
        current_size
        + length
        > expected_size
    ):

        raise ValueError(
            "Chunk exceeds file size"
        )


    remaining = length


    with part_path.open(
        "ab"
    ) as output:

        while remaining > 0:

            chunk = (
                handler.rfile.read(
                    min(
                        1024
                        * 1024,
                        remaining
                    )
                )
            )


            if not chunk:

                raise ValueError(
                    "Upload ended early"
                )


            output.write(
                chunk
            )


            remaining -= len(
                chunk
            )


    received = (
        part_path.stat()
        .st_size
    )


    return {
        "ok":
            True,

        "received":
            received,

        "total":
            expected_size
    }


def studio_version_upload_finish(
    data
):

    upload_id = _clean(
        data.get(
            "upload_id"
        )
    )


    folder = (
        _studio_upload_folder(
            upload_id
        )
    )


    metadata_path = (
        folder
        / "meta.json"
    )


    part_path = (
        folder
        / "audio.part"
    )


    if (
        not metadata_path.exists()
        or not part_path.exists()
    ):

        raise ValueError(
            "Upload not found"
        )


    metadata = _studio_json.loads(
        metadata_path.read_text(
            encoding="utf-8"
        )
    )


    expected_size = int(
        metadata[
            "size"
        ]
    )


    actual_size = (
        part_path.stat()
        .st_size
    )


    if actual_size != expected_size:

        raise ValueError(
            "Audio upload is incomplete"
        )


    track_id = int(
        metadata[
            "track_id"
        ]
    )


    track = _track(
        track_id
    )


    project_id = int(
        track[
            "project_id"
        ]
    )


    if (
        project_id
        != int(
            metadata[
                "project_id"
            ]
        )
    ):

        raise ValueError(
            "Upload project mismatch"
        )


    destination_folder = (
        _studio_project_dir(
            project_id
        )
        / "tracks"
        / f"track-{track_id}"
    )


    destination_folder.mkdir(
        parents=True,
        exist_ok=True
    )


    destination = (
        destination_folder
        / (
            uuid.uuid4().hex
            + metadata[
                "extension"
            ]
        )
    )


    part_path.replace(
        destination
    )


    conn = _conn()


    try:

        conn.execute(
            """
            UPDATE studio_versions

            SET is_current = 0

            WHERE track_id = ?
            """,
            (
                track_id,
            )
        )


        cursor = conn.execute(
            """
            INSERT INTO studio_versions (
                track_id,
                label,

                audio_name,
                audio_path,
                audio_mime,

                notes,
                is_current
            )

            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                track_id,

                metadata[
                    "label"
                ],

                metadata[
                    "filename"
                ],

                str(
                    destination
                ),

                metadata[
                    "mime"
                ],

                metadata.get(
                    "notes"
                )
            )
        )


        version_id = (
            cursor.lastrowid
        )


        conn.execute(
            """
            UPDATE studio_tracks

            SET updated_at =
                CURRENT_TIMESTAMP

            WHERE id = ?
            """,
            (
                track_id,
            )
        )


        conn.execute(
            """
            UPDATE studio_projects

            SET updated_at =
                CURRENT_TIMESTAMP

            WHERE id = ?
            """,
            (
                project_id,
            )
        )


        conn.commit()


    except Exception:

        conn.rollback()

        try:

            destination.unlink(
                missing_ok=True
            )

        except Exception:

            pass

        raise


    finally:

        conn.close()


    try:

        metadata_path.unlink(
            missing_ok=True
        )

        folder.rmdir()

    except Exception:

        pass


    return {
        "ok":
            True,

        "project_id":
            project_id,

        "track_id":
            track_id,

        "version_id":
            version_id
    }


def studio_version_upload_abort(
    data
):

    upload_id = _clean(
        data.get(
            "upload_id"
        )
    )


    folder = (
        _studio_upload_folder(
            upload_id
        )
    )


    if folder.exists():

        shutil.rmtree(
            folder,
            ignore_errors=True
        )


    return {
        "ok":
            True
    }

