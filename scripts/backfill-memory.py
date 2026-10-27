#!/usr/bin/env python3
"""Index the existing archive without model calls, source edits, or credential access.

Resume by rerunning the same command. The live index worker shares its file lock.
Only derived vectors and indexed checkpoints are changed; fact jobs stay pending.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apollo_memory import LocalEmbeddings, MemoryStore

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--database', required=True)
parser.add_argument('--model', required=True)
parser.add_argument('--batch', type=int, default=16)
parser.add_argument('--max-batches', type=int, default=0)
args = parser.parse_args()
assert Path(args.database).is_file(), 'Database must already exist and be migrated'
def connect():
    conn = sqlite3.connect(args.database, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn
memory = MemoryStore(connect, embeddings=LocalEmbeddings(args.model))
if not memory.settings()['history_search']:
    raise SystemExit('History search is disabled; leaving the user setting unchanged')
started, processed, batches = time.monotonic(), 0, 0
while True:
    count = memory.index_pending(batch=max(1, min(64, args.batch)))
    processed += count
    batches += 1
    with memory.connect() as conn:
        pending = conn.execute('''SELECT count(*) FROM memory_jobs j JOIN messages m ON m.id=j.message_id
            JOIN memory_chat_scope s ON s.chat_id=m.chat_id WHERE s.owner='local' AND s.excluded=0 AND j.indexed=0''').fetchone()[0]
    print(json.dumps({'processed': processed, 'pending': pending, 'elapsed_seconds': round(time.monotonic()-started, 3)}), flush=True)
    if not pending or not count or (args.max_batches and batches >= args.max_batches):
        break
