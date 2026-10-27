#!/usr/bin/env bash
# Invoked by the existing main-branch deployment workflow after a prepared release.
set -euo pipefail
umask 077
revision=${1:?exact revision required}
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
cd /root/Apollo
# Preparation is intentionally separate: no unattended migration without verified
# backups, a restored rollback rehearsal, and the exact candidate/runtime checks.
python3 - "$revision" <<'PY'
import json,sys,pathlib,hashlib,subprocess
ready=json.loads(pathlib.Path('/root/apollo-deployment-ready.json').read_text())
assert ready['revision']==sys.argv[1], 'This revision has not completed deployment preflight'
assert ready['migration_rehearsal'] and ready['rollback_rehearsal']
backup=pathlib.Path(ready['backup'])
manifest=json.loads((backup/'manifest.json').read_text())
for name in manifest['files']:
 assert hashlib.file_digest((backup/name).open('rb'), 'sha256').hexdigest()==manifest['files'][name]['sha256'],name
assert hashlib.sha256(pathlib.Path('/opt/apollo/models/all-MiniLM-L6-v2/model.safetensors').read_bytes()).hexdigest()==ready['model_sha256']
assert subprocess.check_output(['git','status','--porcelain','--untracked-files=no']).strip()==b'', 'Preserve unexpected production edits before deploying'
PY
/opt/apollo/venv/bin/python -m pip check
/opt/apollo/venv/bin/python -c 'import PIL,pillow_heif,pywebpush,sentence_transformers,trafilatura'
systemctl is-active --quiet hermes-gateway
previous=$(git rev-parse HEAD)
if [[ "$previous" == "$revision" ]]; then
  systemctl is-active --quiet apollo-backend
  exit 0
fi
git merge-base --is-ancestor "$previous" "$revision"
if [[ -n "$(ss -Htn state established '( sport = :8765 )')" ]]; then
  echo 'Apollo has active HTTP requests; defer deployment until they finish.' >&2
  exit 1
fi
release_dir=/root/apollo-releases/$revision
mkdir -p "$release_dir"
printf '%s\n' "$previous" > "$release_dir/previous-revision"
systemctl show hermes-gateway -p MainPID --value > "$release_dir/hermes-pid"
override=/etc/systemd/system/apollo-backend.service.d/20-intelligence.conf
if [[ -e "$override" ]]; then cp -p "$override" "$release_dir/previous-override.conf"; fi
cat > "$release_dir/rollback.sh" <<'ROLLBACK'
#!/usr/bin/env bash
set -euo pipefail
release_dir=$(cd "$(dirname "$0")" && pwd)
previous=$(cat "$release_dir/previous-revision")
cd /root/Apollo
# Preserve all current conversations, settings and rotated OAuth credentials.
# Only code/runtime are rolled back; the additive database remains in place.
test -z "$(git status --porcelain --untracked-files=no)"
systemctl stop apollo-backend
git checkout --detach "$previous"
override=/etc/systemd/system/apollo-backend.service.d/20-intelligence.conf
if [[ -e "$release_dir/previous-override.conf" ]]; then
  cp -p "$release_dir/previous-override.conf" "$override"
else
  rm -f "$override"
fi
systemctl daemon-reload
systemctl start apollo-backend
for attempt in {1..30}; do
  if curl --fail --silent http://127.0.0.1:8765/api/chats >/dev/null; then
    test "$(systemctl show hermes-gateway -p MainPID --value)" = "$(cat "$release_dir/hermes-pid")"
    printf '%s\n' "$previous" > /root/apollo-active-release
    echo 'Rollback verified; the current database and credentials were retained.'
    exit 0
  fi
  sleep 1
done
exit 1
ROLLBACK
chmod 700 "$release_dir/rollback.sh"
trap 'status=$?; echo "Deployment verification failed; invoking rollback." >&2; bash "$release_dir/rollback.sh"; exit "$status"' ERR
systemctl stop apollo-backend
# Final consistent backup immediately before schema changes, with no live writer.
python3 - "$release_dir" <<'PY'
import sqlite3,sys,pathlib,json,hashlib
out=pathlib.Path(sys.argv[1]); source=sqlite3.connect('apollo.db'); copy=sqlite3.connect(out/'pre-migration.db'); source.backup(copy)
assert copy.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
checks={}
for table in ['chats','messages','app_state']:
 h=hashlib.sha256()
 for row in copy.execute('SELECT * FROM '+table+' ORDER BY rowid'):h.update(json.dumps(row,default=str).encode())
 checks[table]=h.hexdigest()
(out/'source-row-hashes.json').write_text(json.dumps(checks))
PY
git checkout main
git merge --ff-only "$revision"
mkdir -p "$(dirname "$override")"
cat > "$override" <<'UNIT'
[Service]
ExecStart=
ExecStart=/opt/apollo/venv/bin/python /root/Apollo/server.py
Environment=APOLLO_BASE_DIR=/root/Apollo
Environment=APOLLO_EMBEDDING_MODEL=/opt/apollo/models/all-MiniLM-L6-v2
Environment=APOLLO_WEB_EXTRACT_BACKEND=trafilatura
Environment=OMP_NUM_THREADS=1
Environment=MKL_NUM_THREADS=1
Environment=TOKENIZERS_PARALLELISM=false
Environment=HF_HUB_OFFLINE=1
Environment=PYTHONUNBUFFERED=1
UNIT
APOLLO_BASE_DIR=/root/Apollo /opt/apollo/venv/bin/python - "$release_dir" <<'PY'
import server,sqlite3,json,hashlib,sys,pathlib
server.init_db()
conn=sqlite3.connect('apollo.db')
assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
for table,expected in json.loads((pathlib.Path(sys.argv[1])/'source-row-hashes.json').read_text()).items():
 h=hashlib.sha256()
 for row in conn.execute('SELECT * FROM '+table+' ORDER BY rowid'):h.update(json.dumps(row,default=str).encode())
 assert h.hexdigest()==expected,table+' original records changed during migration'
PY
systemctl daemon-reload
systemctl start apollo-backend
for attempt in {1..30}; do
  if curl --fail --silent http://127.0.0.1:8765/api/memory >/dev/null; then break; fi
  sleep 1
done
curl --fail --silent http://127.0.0.1:8765/api/memory > "$release_dir/memory-health.json"
systemctl is-active --quiet apollo-backend apollo-web hermes-gateway
test "$(systemctl show hermes-gateway -p MainPID --value)" = "$(cat "$release_dir/hermes-pid")"
printf '%s\n' "$revision" > /root/apollo-active-release
trap - ERR
echo "Deployed $revision; Apollo restarted, Hermes and static web service retained."
