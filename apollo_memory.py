"""Private, source-backed personal memory on Apollo's existing SQLite database.

One database is one authenticated deployment/account. `owner` is server supplied,
never a value supplied by the model or an HTTP client. Embeddings stay local.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import fcntl
from datetime import datetime, timedelta, timezone

CATEGORIES = {'preference', 'background', 'goal', 'project', 'routine', 'relationship', 'decision'}
STOP = set('a an the i me my we our you your it that this was is are were do did does have had has what which where when about told tell remember previous earlier last week month year conversation chat continue working on in at to for of and with from please can could would'.split())
SENSITIVE = re.compile(r'\b(password|secret|api.?key|access.?token|ssn|social security|credit card|diagnos\w*|medication|sexual\w*|religion|political affiliation|bank account)\b', re.I)
RESTRICTED = re.compile(r'\b(?:password|passphrase|api.?key|access.?token|refresh.?token|'
                        r'recovery.?code|verification.?code|one.?time.?code|private.?key|session.?cookie)\b', re.I)
PRIVATE_FACT = re.compile(r'\b(?:diagnos\w*|medication|health|medical|financial|'
                          r'bank account|credit card|family|familia|relationship|relación|'
                          r'confidential|sexual\w*|religion|political affiliation)\b', re.I)
RESIDENCE_QUERY = re.compile(r'\b(?:where (?:do|did) i live|where is my home|'
                             r'(?:my|mi) (?:home|hometown|residence|city|address|casa|ciudad|domicilio)|'
                             r'donde vivo|dónde vivo|where am i based)\b', re.I)
RESIDENCE_FACT = re.compile(r'\b(?:live in|lives in|reside in|based in|home city|'
                            r'hometown|residence|address|vivo en|vive en|resido en|ciudad natal)\b', re.I)
TEMPORARY_LOCATION = re.compile(r'\b(?:visiting|travel(?:ing|ling)?|staying|trip to|'
                                r'vacation|de viaje|visitando|alojad[oa])\b', re.I)


def classify_memory(content, category):
    if RESTRICTED.search(content):
        return 'restricted'
    if category == 'relationship' or PRIVATE_FACT.search(content):
        return 'sensitive'
    if category == 'preference':
        return 'ordinary'
    return 'personal'


def now():
    return datetime.now(timezone.utc).isoformat()


def init_schema(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS memory_settings (
        owner TEXT PRIMARY KEY, auto_memory INTEGER NOT NULL DEFAULT 1,
        history_search INTEGER NOT NULL DEFAULT 1, retention_days INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS memory_chat_scope (
        chat_id INTEGER PRIMARY KEY, owner TEXT NOT NULL, excluded INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS personal_memories (
        id INTEGER PRIMARY KEY, owner TEXT NOT NULL, memory_key TEXT NOT NULL,
        content TEXT NOT NULL, category TEXT NOT NULL, confidence REAL NOT NULL,
        source_message_id INTEGER, source_quote TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active'
    );
    CREATE INDEX IF NOT EXISTS memory_owner_key ON personal_memories(owner, memory_key, status);
    CREATE TABLE IF NOT EXISTS memory_exclusions (
        owner TEXT NOT NULL, phrase TEXT NOT NULL, PRIMARY KEY(owner, phrase)
    );
    CREATE TABLE IF NOT EXISTS memory_hidden_messages (
        owner TEXT NOT NULL, message_id INTEGER NOT NULL, PRIMARY KEY(owner, message_id)
    );
    CREATE TABLE IF NOT EXISTS memory_jobs (
        message_id INTEGER PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0,
        indexed INTEGER NOT NULL DEFAULT 0, consolidated INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS memory_embeddings (
        memory_id INTEGER PRIMARY KEY, model TEXT NOT NULL, vector TEXT NOT NULL
    );
    CREATE TRIGGER IF NOT EXISTS memory_fact_delete AFTER DELETE ON personal_memories BEGIN
        DELETE FROM memory_embeddings WHERE memory_id=old.id;
    END;
    DROP TRIGGER IF EXISTS memory_fact_update;
    CREATE TRIGGER memory_fact_update AFTER UPDATE OF content,memory_key,category,source_quote,status ON personal_memories BEGIN
        DELETE FROM memory_embeddings WHERE memory_id=old.id;
    END;
    CREATE TABLE IF NOT EXISTS message_embeddings (
        message_id INTEGER NOT NULL, chunk_index INTEGER NOT NULL,
        model TEXT NOT NULL, vector TEXT NOT NULL, PRIMARY KEY(message_id,chunk_index)
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS message_search USING fts5(content, tokenize='unicode61');
    CREATE TRIGGER IF NOT EXISTS memory_message_insert AFTER INSERT ON messages BEGIN
        INSERT INTO message_search(rowid, content) VALUES(new.id, new.content);
        INSERT OR IGNORE INTO memory_jobs(message_id) VALUES(new.id);
    END;
    CREATE TRIGGER IF NOT EXISTS memory_message_delete AFTER DELETE ON messages BEGIN
        DELETE FROM message_search WHERE rowid=old.id;
        DELETE FROM message_embeddings WHERE message_id=old.id;
        DELETE FROM memory_jobs WHERE message_id=old.id;
        DELETE FROM personal_memories WHERE source_message_id=old.id;
        DELETE FROM memory_hidden_messages WHERE message_id=old.id;
    END;
    CREATE TRIGGER IF NOT EXISTS memory_message_update AFTER UPDATE OF content ON messages BEGIN
        DELETE FROM message_search WHERE rowid=old.id;
        INSERT INTO message_search(rowid, content) VALUES(new.id, new.content);
        DELETE FROM message_embeddings WHERE message_id=old.id;
        DELETE FROM personal_memories WHERE source_message_id=old.id;
        INSERT OR REPLACE INTO memory_jobs(message_id) VALUES(new.id);
    END;
    CREATE TRIGGER IF NOT EXISTS memory_chat_delete AFTER DELETE ON chats BEGIN
        DELETE FROM messages WHERE chat_id=old.id;
        DELETE FROM memory_chat_scope WHERE chat_id=old.id;
    END;
    ''')
    if 'sensitivity' not in {row[1] for row in conn.execute('PRAGMA table_info(personal_memories)')}:
        conn.execute("ALTER TABLE personal_memories ADD COLUMN sensitivity TEXT NOT NULL DEFAULT 'personal'")
        # Preserve existing facts. Reclassify on this additive migration without
        # logging or transferring their content.
        for row in conn.execute('SELECT id,content,source_quote,category FROM personal_memories').fetchall():
            conn.execute('UPDATE personal_memories SET sensitivity=? WHERE id=?',
                         (classify_memory(row['content'] + ' ' + row['source_quote'], row['category']), row['id']))
    if 'chunk_index' not in {row[1] for row in conn.execute('PRAGMA table_info(message_embeddings)')}:
        conn.execute('DROP TABLE message_embeddings')
        conn.execute('CREATE TABLE message_embeddings(message_id INTEGER NOT NULL,chunk_index INTEGER NOT NULL,model TEXT NOT NULL,vector TEXT NOT NULL,PRIMARY KEY(message_id,chunk_index))')
        conn.execute('UPDATE memory_jobs SET indexed=0,attempts=0')
    # Idempotent backfill: no historical conversation is silently left unsearchable.
    conn.execute('INSERT INTO message_search(rowid, content) SELECT id, content FROM messages WHERE id NOT IN (SELECT rowid FROM message_search)')
    conn.execute('INSERT OR IGNORE INTO memory_jobs(message_id) SELECT id FROM messages')


class LocalEmbeddings:
    """Optional real semantic embeddings; no network download or hosted data transfer."""
    def __init__(self, model_path=None):
        self.model_path = model_path or os.environ.get('APOLLO_EMBEDDING_MODEL', '')
        self.model = None
        self.lock = threading.Lock()
        self.error = None

    @property
    def name(self):
        return self.model_path

    def encode(self, texts):
        if not self.model_path:
            raise RuntimeError('semantic_not_configured')
        with self.lock:
            if self.model is None:
                if self.error:
                    raise RuntimeError(self.error)
                try:
                    from sentence_transformers import SentenceTransformer
                    self.model = SentenceTransformer(self.model_path, local_files_only=True)
                except Exception:
                    self.error = 'semantic_model_unavailable'
                    raise RuntimeError(self.error)
            return self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


class MemoryStore:
    def __init__(self, connect, owner='local', embeddings=None):
        self._connect, self.owner, self.embeddings = connect, owner, embeddings

    @contextmanager
    def connect(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def bind_chat(self, chat_id):
        with self.connect() as conn:
            conn.execute('INSERT OR IGNORE INTO memory_chat_scope(chat_id, owner) VALUES (?, ?)', (chat_id, self.owner))

    def settings(self):
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM memory_settings WHERE owner=?', (self.owner,)).fetchone()
        return dict(row) if row else dict(owner=self.owner, auto_memory=1, history_search=1, retention_days=0)

    def configure(self, data):
        settings = self.settings()
        for key in ('auto_memory', 'history_search'):
            if key in data:
                if type(data[key]) is not bool:
                    raise ValueError(key + ' must be a boolean')
                settings[key] = int(data[key])
        if 'retention_days' in data:
            value = data['retention_days']
            if type(value) is not int or not 0 <= value <= 36500:
                raise ValueError('retention_days must be 0 (unlimited) or 1–36500')
            settings['retention_days'] = value
        with self.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO memory_settings VALUES (?, ?, ?, ?)',
                         tuple(settings[k] for k in ('owner', 'auto_memory', 'history_search', 'retention_days')))
        self.enforce_retention()
        return self.settings()

    def enforce_retention(self):
        days = self.settings()['retention_days']
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            with self.connect() as conn:
                conn.execute('DELETE FROM messages WHERE julianday(created_at)<julianday(?) AND chat_id IN (SELECT chat_id FROM memory_chat_scope WHERE owner=?)', (cutoff, self.owner))

    def exclude_chat(self, chat_id, excluded=True):
        with self.connect() as conn:
            if not conn.execute('SELECT 1 FROM memory_chat_scope WHERE chat_id=? AND owner=?', (chat_id, self.owner)).fetchone():
                raise ValueError('Chat not found')
            conn.execute('UPDATE memory_chat_scope SET excluded=? WHERE chat_id=? AND owner=?', (int(excluded), chat_id, self.owner))
            if excluded:
                conn.execute('DELETE FROM personal_memories WHERE owner=? AND source_message_id IN (SELECT id FROM messages WHERE chat_id=?)', (self.owner, chat_id))
                conn.execute('DELETE FROM message_embeddings WHERE message_id IN (SELECT id FROM messages WHERE chat_id=?)', (chat_id,))
            else:
                conn.execute('UPDATE memory_jobs SET indexed=0, consolidated=0, attempts=0 WHERE message_id IN (SELECT id FROM messages WHERE chat_id=?)', (chat_id,))

    def _allowed(self, conn, text, message_id=None):
        if message_id and conn.execute('SELECT 1 FROM memory_hidden_messages WHERE owner=? AND message_id=?', (self.owner, message_id)).fetchone():
            return False
        return not any(row[0] in text.casefold() for row in conn.execute('SELECT phrase FROM memory_exclusions WHERE owner=?', (self.owner,)))

    def save(self, content, category='preference', memory_key=None, source_message_id=None,
             source_quote='', confidence=1.0, automatic=False):
        content = str(content).strip()
        if not content or len(content) > 2000 or category not in CATEGORIES:
            raise ValueError('Invalid memory content or category')
        if automatic and SENSITIVE.search(content + ' ' + source_quote):
            return None
        sensitivity = classify_memory(content + ' ' + source_quote, category)
        if sensitivity == 'restricted':
            raise ValueError('Authentication secrets cannot be saved as personal memories')
        memory_key = str(memory_key or hashlib.sha256(content.casefold().encode()).hexdigest())[:160]
        confidence = float(confidence)
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError('Invalid confidence')
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            privacy = conn.execute('SELECT auto_memory FROM memory_settings WHERE owner=?', (self.owner,)).fetchone()
            if automatic and privacy and not privacy['auto_memory']:
                return None
            source = None
            if source_message_id is not None:
                source = conn.execute('''SELECT m.* FROM messages m JOIN memory_chat_scope s ON s.chat_id=m.chat_id
                    WHERE m.id=? AND s.owner=? AND s.excluded=0''', (source_message_id, self.owner)).fetchone()
                if not source or source['role'] != 'user' or not source_quote or source_quote not in source['content']:
                    raise ValueError('Memory needs an exact quote from an accessible user message')
                if automatic and re.search(r'\b(don.t (?:save|remember)|do not (?:save|remember)|forget (?:this|that))\b', source['content'], re.I):
                    return None
                if not self._allowed(conn, source['content'], source_message_id):
                    return None
            elif automatic:
                raise ValueError('Automatic memories require a source')
            if not self._allowed(conn, content + ' ' + source_quote):
                return None
            previous = conn.execute("SELECT * FROM personal_memories WHERE owner=? AND memory_key=? AND status='active' ORDER BY id DESC LIMIT 1", (self.owner, memory_key)).fetchone()
            # Historical consolidation must never overwrite a newer explicit correction.
            if previous and source:
                if previous['source_message_id'] is None:
                    return previous['id']
                newer = conn.execute('SELECT 1 FROM messages WHERE id=? AND (julianday(created_at)>julianday(?) OR (julianday(created_at)=julianday(?) AND id>?))',
                                     (previous['source_message_id'], source['created_at'], source['created_at'], source_message_id)).fetchone()
                if newer:
                    return previous['id']
            if previous and previous['content'] == content:
                return previous['id']
            conn.execute("UPDATE personal_memories SET status='superseded' WHERE owner=? AND memory_key=? AND status='active'", (self.owner, memory_key))
            stamp = now()
            cursor = conn.execute('''INSERT INTO personal_memories(owner,memory_key,content,category,confidence,source_message_id,source_quote,created_at,updated_at,sensitivity)
                VALUES (?,?,?,?,?,?,?,?,?,?)''', (self.owner, memory_key, content, category, confidence, source_message_id, source_quote, stamp, stamp, sensitivity))
            return cursor.lastrowid

    def list_memories(self):
        with self.connect() as conn:
            rows = [dict(r) for r in conn.execute("SELECT p.*, m.chat_id, m.created_at AS source_created_at FROM personal_memories p LEFT JOIN messages m ON m.id=p.source_message_id WHERE p.owner=? AND p.status='active' ORDER BY p.id DESC", (self.owner,)) if self._allowed(conn, r['content'], r['source_message_id'])]
            for row in rows:
                row['provenance'] = 'user_statement' if row['source_message_id'] else 'explicitly_saved'
                if row['sensitivity'] == 'restricted':
                    row['content'] = '[Restricted secret — remove this memory in Settings]'
                    row['source_quote'] = ''
            return rows

    def forget(self, memory_id=None, phrase=None):
        with self.connect() as conn:
            if memory_id is not None:
                row = conn.execute('SELECT * FROM personal_memories WHERE id=? AND owner=?', (memory_id, self.owner)).fetchone()
                if not row:
                    raise ValueError('Memory not found')
                # Block all old versions and their source messages, including queued work.
                for old in conn.execute('SELECT * FROM personal_memories WHERE owner=? AND memory_key=?', (self.owner, row['memory_key'])).fetchall():
                    if old['source_message_id']:
                        conn.execute('INSERT OR IGNORE INTO memory_hidden_messages VALUES (?,?)', (self.owner, old['source_message_id']))
                    for value in (old['content'], old['source_quote']):
                        if value:
                            conn.execute('INSERT OR IGNORE INTO memory_exclusions VALUES (?,?)', (self.owner, value.casefold()))
                conn.execute('DELETE FROM personal_memories WHERE owner=? AND memory_key=?', (self.owner, row['memory_key']))
            if phrase is not None:
                phrase = str(phrase).strip().casefold()
                if not 2 <= len(phrase) <= 2000:
                    raise ValueError('Exclusion must be 2–2000 characters')
                conn.execute('INSERT OR IGNORE INTO memory_exclusions VALUES (?,?)', (self.owner, phrase))
                for row in conn.execute('SELECT id,content,source_quote FROM personal_memories WHERE owner=?', (self.owner,)).fetchall():
                    if phrase in (row['content'] + ' ' + row['source_quote']).casefold():
                        conn.execute('DELETE FROM personal_memories WHERE id=?', (row['id'],))
            conn.execute('DELETE FROM message_embeddings WHERE message_id IN (SELECT message_id FROM memory_hidden_messages WHERE owner=?)', (self.owner,))
            if phrase:
                for message in conn.execute('SELECT m.id,m.content FROM messages m JOIN memory_chat_scope s ON s.chat_id=m.chat_id WHERE s.owner=?', (self.owner,)).fetchall():
                    if phrase in message['content'].casefold():
                        conn.execute('DELETE FROM message_embeddings WHERE message_id=?', (message['id'],))

    def filter_working_history(self, rows, current_message_id=None, id_key='id'):
        with self.connect() as conn:
            return [row for row in rows if row[id_key] == current_message_id or self._allowed(conn, row['content'], row[id_key])]

    def search_memories(self, query, limit=8, semantic=False):
        terms = set(re.findall(r'\w+', query.casefold())) - STOP
        rows = [row for row in self.list_memories() if row['sensitivity'] != 'restricted']
        residence = bool(RESIDENCE_QUERY.search(query))
        for row in rows:
            row['relevance'] = len(terms & set(re.findall(r'\w+', row['content'].casefold() + ' ' + row['memory_key'].casefold())))
            if residence and (RESIDENCE_FACT.search(row['content'] + ' ' + row['source_quote'])
                              or re.search(r'(?:home|city|residen|address|location)', row['memory_key'], re.I)):
                row['relevance'] += 3
            if residence and TEMPORARY_LOCATION.search(row['content'] + ' ' + row['source_quote']):
                row['relevance'] = 0
        if semantic and self.embeddings and self.embeddings.name:
            try:
                vector = self.embeddings.encode([query])[0]
                with self.connect() as conn:
                    vectors = {r['memory_id']: json.loads(r['vector']) for r in conn.execute(
                        'SELECT e.* FROM memory_embeddings e JOIN personal_memories p ON p.id=e.memory_id WHERE p.owner=? AND e.model=?', (self.owner, self.embeddings.name))}
                for row in rows:
                    other = vectors.get(row['id'], [])
                    denom = math.sqrt(sum(x*x for x in vector)*sum(x*x for x in other))
                    score = sum(a*b for a,b in zip(vector, other))/denom if denom and len(vector)==len(other) else 0
                    if score >= .3:
                        row['relevance'] += score
            except Exception:
                pass  # Keyword matches remain usable; history reports semantic availability.
        return sorted((r for r in rows if r['relevance']), key=lambda r: (r['relevance'], r['updated_at']), reverse=True)[:limit]

    def search(self, query, after=None, before=None, limit=8, exact=False, exclude_message_id=None, user_only=False):
        if not self.settings()['history_search']:
            return {'status': 'disabled', 'results': []}
        self.enforce_retention()
        query = str(query).strip()[:2000]
        limit = max(1, min(int(limit), 20))
        if not query:
            raise ValueError('Search query is required')
        for date in (after, before):
            if date:
                datetime.fromisoformat(date.replace('Z', '+00:00'))
        terms = [t for t in re.findall(r'\w+', query.casefold()) if t not in STOP][:32]
        phrase = query.strip('"')
        match = '"' + phrase.replace('"', '""') + '"' if exact else ' OR '.join('"' + t + '"' for t in terms)
        where = '''s.owner=? AND s.excluded=0 AND m.id != ? AND (? IS NULL OR julianday(m.created_at)>=julianday(?))
                   AND (? IS NULL OR julianday(m.created_at)<julianday(?))'''
        if user_only:
            where += " AND m.role='user'"
        params = (self.owner, exclude_message_id or -1, after, after, before, before)
        ranked = {}
        mode = 'keyword'
        with self.connect() as conn:
            if match:
                rows = conn.execute(f'''SELECT m.*, bm25(message_search) AS rank FROM message_search
                    JOIN messages m ON m.id=message_search.rowid JOIN memory_chat_scope s ON s.chat_id=m.chat_id
                    WHERE message_search MATCH ? AND {where} ORDER BY rank LIMIT 200''', (match, *params)).fetchall()
                for index, row in enumerate(rows):
                    if self._allowed(conn, row['content'], row['id']) and (not exact or phrase.casefold() in row['content'].casefold()):
                        ranked[row['id']] = [dict(row), 1 / (60 + index + 1)]
            semantic_status = 'not_configured'
            if self.embeddings and self.embeddings.name and not exact:
                try:
                    vector = self.embeddings.encode([query])[0]
                    semantic = {}
                    rows = conn.execute(f'''SELECT m.*, e.vector, e.chunk_index FROM message_embeddings e JOIN messages m ON m.id=e.message_id
                        JOIN memory_chat_scope s ON s.chat_id=m.chat_id WHERE e.model=? AND {where}''', (self.embeddings.name, *params))
                    for row in rows:
                        stored = json.loads(row['vector'])
                        if len(stored) != len(vector) or not self._allowed(conn, row['content'], row['id']):
                            continue
                        denom = math.sqrt(sum(x*x for x in vector) * sum(x*x for x in stored))
                        score = sum(a*b for a,b in zip(vector, stored)) / denom if denom else 0
                        if score >= 0.3:
                            item = dict(row)
                            item.pop('vector', None)
                            if row['id'] not in semantic or score > semantic[row['id']][0]:
                                semantic[row['id']] = (score, item)
                    for index, (_, row) in enumerate(sorted(semantic.values(), key=lambda x: x[0], reverse=True)[:200]):
                        ranked.setdefault(row['id'], [row, 0])[1] += 1 / (60 + index + 1)
                    mode = 'hybrid'
                    pending = conn.execute('SELECT 1 FROM messages m JOIN memory_chat_scope s ON s.chat_id=m.chat_id WHERE s.owner=? AND s.excluded=0 AND NOT EXISTS (SELECT 1 FROM message_embeddings e WHERE e.message_id=m.id AND e.model=?) LIMIT 1', (self.owner, self.embeddings.name)).fetchone()
                    semantic_status = 'indexing' if pending else 'ready'
                except Exception:
                    semantic_status = 'unavailable'
            results = []
            def rank(item):
                row, score = item
                try:
                    stamp = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
                    age = max(0, (datetime.now(timezone.utc) - stamp.replace(tzinfo=stamp.tzinfo or timezone.utc)).days)
                except (TypeError, ValueError):
                    age = 3650
                return score * (1 + .04/(1 + age/180)) * (1.04 if row['role'] == 'user' else 1)
            for row, score in sorted(ranked.values(), key=rank, reverse=True)[:limit]:
                neighbors = conn.execute('SELECT * FROM messages WHERE chat_id=? AND id<? ORDER BY id DESC LIMIT 1', (row['chat_id'], row['id'])).fetchall()
                neighbors += conn.execute('SELECT * FROM messages WHERE chat_id=? AND id>? ORDER BY id LIMIT 1', (row['chat_id'], row['id'])).fetchall()
                context = [dict(r) for r in sorted(neighbors, key=lambda r: r['id'])
                           if self._allowed(conn, r['content'], r['id'])
                           and (not user_only or r['role'] == 'user')]
                row.pop('rank', None)
                full_text = row['content']
                position = min((full_text.casefold().find(t) for t in (terms or [phrase]) if t in full_text.casefold()), default=row.get('chunk_index', 0) * 700)
                start = max(0, position - 1500) if len(full_text) > 6000 else 0
                row['content'] = full_text[start:start+6000]
                row['content_start'] = start
                row['content_truncated'] = len(full_text) > len(row['content'])
                for item in context:
                    item['content'] = item['content'][:3000]
                results.append({**row, 'score': round(score, 6), 'context': context,
                                'reliability': 'user_statement' if row['role'] == 'user' else 'assistant_generated'})
        return {'status': 'ok' if results else 'not_found', 'mode': mode, 'semantic_status': semantic_status, 'results': results}

    def allow_topic(self, phrase):
        with self.connect() as conn:
            conn.execute('DELETE FROM memory_exclusions WHERE owner=? AND phrase=?', (self.owner, str(phrase).strip().casefold()))
        # Individual forgotten source messages remain hidden until their chat is
        # deleted; lifting a topic exclusion does not resurrect forgotten facts.

    def reindex(self):
        with self.connect() as conn:
            conn.execute('UPDATE memory_jobs SET indexed=0,attempts=0 WHERE message_id IN (SELECT m.id FROM messages m JOIN memory_chat_scope s ON s.chat_id=m.chat_id WHERE s.owner=? AND s.excluded=0)', (self.owner,))

    def index_pending(self, batch=16):
        """Resumable embedding-only work; never marks fact extraction complete.

        The file lock coordinates the live worker and the operator's backfill
        command. Each message commits independently after rechecking its source.
        """
        if not self.embeddings or not self.embeddings.name:
            raise RuntimeError('semantic_not_configured')
        if not self.settings()['history_search']:
            return 0
        with self.connect() as conn:
            path = conn.execute('PRAGMA database_list').fetchone()[2]
        with open(path + '.index.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.connect() as conn:
                rows = [dict(r) for r in conn.execute('''SELECT m.* FROM memory_jobs j
                    JOIN messages m ON m.id=j.message_id JOIN memory_chat_scope s ON s.chat_id=m.chat_id
                    WHERE s.owner=? AND s.excluded=0 AND j.indexed=0
                    ORDER BY m.id LIMIT ?''', (self.owner, batch))]
            for row in rows:
                with self.connect() as conn:
                    allowed = self._allowed(conn, row['content'], row['id'])
                vectors = self.embeddings.encode([row['content'][offset:offset+900]
                    for offset in range(0, max(1, len(row['content'])), 700)]) if allowed else []
                with self.connect() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    live = conn.execute('''SELECT 1 FROM messages m JOIN memory_chat_scope s ON s.chat_id=m.chat_id
                        WHERE m.id=? AND m.content=? AND s.owner=? AND s.excluded=0''',
                        (row['id'], row['content'], self.owner)).fetchone()
                    enabled = conn.execute('SELECT history_search FROM memory_settings WHERE owner=?', (self.owner,)).fetchone()
                    if live and (not enabled or enabled[0]):
                        conn.execute('DELETE FROM message_embeddings WHERE message_id=?', (row['id'],))
                        if vectors and self._allowed(conn, row['content'], row['id']):
                            conn.executemany('INSERT INTO message_embeddings VALUES (?,?,?,?)',
                                [(row['id'], i, self.embeddings.name, json.dumps(v)) for i, v in enumerate(vectors)])
                        conn.execute('UPDATE memory_jobs SET indexed=1 WHERE message_id=?', (row['id'],))
            return len(rows)

    def process_pending(self, extract=None, batch=16, indexing=True):
        """Bounded durable queue; failed model calls retry on subsequent worker ticks."""
        self.enforce_retention()
        settings = self.settings()
        with self.connect() as conn:
            jobs = [dict(r) for r in conn.execute('''SELECT m.*, j.indexed, j.consolidated FROM memory_jobs j JOIN messages m ON m.id=j.message_id
                JOIN memory_chat_scope s ON s.chat_id=m.chat_id WHERE s.owner=? AND s.excluded=0 AND j.attempts<3
                AND ((? AND j.indexed=0) OR j.consolidated=0) ORDER BY julianday(m.created_at) DESC,m.id DESC LIMIT ?''', (self.owner, indexing, batch))]
        for row in jobs:
            with self.connect() as conn:
                if not self._allowed(conn, row['content'], row['id']):
                    conn.execute('UPDATE memory_jobs SET indexed=1,consolidated=1 WHERE message_id=?', (row['id'],))
                    continue
            try:
                try:
                    if indexing and not row['indexed'] and self.embeddings and self.embeddings.name and settings['history_search']:
                        chunks = [row['content'][offset:offset+900] for offset in range(0, max(1, len(row['content'])), 700)]
                        vectors = self.embeddings.encode(chunks)
                        with self.connect() as conn:
                            # Recheck privacy and existence after the potentially slow model call.
                            conn.execute('BEGIN IMMEDIATE')
                            live = conn.execute('SELECT 1 FROM messages m JOIN memory_chat_scope s ON s.chat_id=m.chat_id WHERE m.id=? AND m.content=? AND s.owner=? AND s.excluded=0', (row['id'], row['content'], self.owner)).fetchone()
                            if live and self.settings()['history_search'] and self._allowed(conn, row['content'], row['id']):
                                conn.execute('DELETE FROM message_embeddings WHERE message_id=?', (row['id'],))
                                conn.executemany('INSERT INTO message_embeddings VALUES (?,?,?,?)', [(row['id'], index, self.embeddings.name, json.dumps(vector)) for index, vector in enumerate(vectors)])
                                conn.execute('UPDATE memory_jobs SET indexed=1 WHERE message_id=?', (row['id'],))
                except Exception:
                    with self.connect() as conn:
                        conn.execute('UPDATE memory_jobs SET attempts=attempts+1 WHERE message_id=?', (row['id'],))
                if not row['consolidated'] and settings['auto_memory'] and extract and row['role'] == 'user':
                    candidates = extract(row, self.search_memories(row['content']))
                    if not isinstance(candidates, list):
                        raise ValueError('Invalid extraction')
                    for candidate in candidates[:8]:
                        if (isinstance(candidate, dict) and candidate.get('durable') is True and candidate.get('sensitive') is False
                                and float(candidate.get('confidence', 0)) >= 0.85):
                            self.save(candidate['content'], candidate['category'], candidate.get('key'), row['id'],
                                      candidate.get('quote', ''), candidate['confidence'], automatic=True)
                with self.connect() as conn:
                    conn.execute('UPDATE memory_jobs SET consolidated=1 WHERE message_id=?', (row['id'],))
                    if not self.embeddings or not self.embeddings.name:
                        conn.execute('UPDATE memory_jobs SET indexed=1 WHERE message_id=?', (row['id'],))
            except Exception:
                with self.connect() as conn:
                    conn.execute('UPDATE memory_jobs SET attempts=attempts+1 WHERE message_id=?', (row['id'],))
        if self.embeddings and self.embeddings.name:
            with self.connect() as conn:
                facts = [dict(r) for r in conn.execute("SELECT p.* FROM personal_memories p WHERE p.owner=? AND p.status='active' AND NOT EXISTS (SELECT 1 FROM memory_embeddings e WHERE e.memory_id=p.id AND e.model=?) LIMIT ?", (self.owner, self.embeddings.name, batch))]
            for fact in facts:
                try:
                    vector = self.embeddings.encode([fact['content']])[0]
                    with self.connect() as conn:
                        conn.execute('BEGIN IMMEDIATE')
                        live = conn.execute("SELECT 1 FROM personal_memories WHERE id=? AND owner=? AND status='active' AND content=?", (fact['id'], self.owner, fact['content'])).fetchone()
                        if live and self._allowed(conn, fact['content'], fact['source_message_id']):
                            conn.execute('INSERT OR REPLACE INTO memory_embeddings VALUES (?,?,?)', (fact['id'], self.embeddings.name, json.dumps(vector)))
                except Exception:
                    break
        return len(jobs)
