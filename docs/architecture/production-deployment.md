# Prepared production releases

Apollo keeps the existing Git `main` → SSH → systemd deployment mechanism. The workflow now deploys an exact, preflight-approved revision through `scripts/deploy-production.sh`. It refuses an unprepared revision, unexpected tracked server edits, missing dependencies, an invalid backup/model fingerprint, or active Apollo HTTP requests.

Production runtime: `/opt/apollo/venv/bin/python` (tested Python 3.11 CPU environment). Embedding model: `/opt/apollo/models/all-MiniLM-L6-v2`, pinned revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. Do not install CUDA Torch on this CPU host. Dependencies are `requirements.txt` plus `requirements-memory.txt`; provision the model with `scripts/provision-memory-model.py` before activating a release.

Before pushing a release to `main`, stage and verify its files and runtime, create a consistent SQLite backup plus private file/configuration/Git backups, restore and verify those backups, and run the migration twice on the restored database. Verify the previous backend can still serve the migrated database without modifying original records. Record the exact release SHA, verified backup directory, migration/rollback rehearsal booleans, and model SHA256 in `/root/apollo-deployment-ready.json`. This operator-owned gate is required for each new revision; future unprepared pushes stop safely.

Deployment takes one final SQLite backup with Apollo stopped, applies additive migrations, verifies the original chat/message/app-state row hashes, and starts Apollo with the dedicated runtime and local model. Existing VAPID/OAuth credentials remain unchanged. Hermes and the static web server are not restarted. A failed migration/startup check invokes rollback automatically.

The rollback command is `/root/apollo-releases/<release SHA>/rollback.sh`. It restores the previous tracked code and backend runtime override, then verifies the old HTTP endpoint. **It keeps the current database**, including new conversations and rotated OAuth credentials. The old backend was rehearsed against the additive schema. Never restore an old whole database merely to roll back code: that would lose newer conversations and may invalidate rotating credentials. Private disaster-recovery backups require a separately reviewed data-restoration plan.

Complete or resume semantic indexing with:

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false \
/opt/apollo/venv/bin/python /root/Apollo/scripts/backfill-memory.py \
  --database /root/Apollo/apollo.db \
  --model /opt/apollo/models/all-MiniLM-L6-v2
```

The index-only command shares a file lock with the live index worker, commits each source independently, rechecks privacy/source content, and leaves fact-consolidation jobs untouched. Original messages and dates are never rewritten. Re-running resumes pending messages; the embedding primary key prevents duplicates. The live index worker is independent of slower fact extraction. Full semantic coverage does not mean every historical message has been converted into a durable personal fact.

`APOLLO_WEB_EXTRACT_BACKEND=trafilatura` enables Apollo's public-page backend. Hermes continues to search through its existing provider; Apollo fetches up to three source pages and, for current release/news questions, up to two observed collection links to check for newer information before synthesis. [Trafilatura's documented extraction API](https://trafilatura.readthedocs.io/en/latest/usage-python.html) supplies main text. Requests use validated, pinned public IPs, TLS hostname verification, per-redirect validation, byte limits, and no account credentials/cookies or JavaScript. Denied pages, unsupported media and missing content remain explicit failures. If full pages cannot support a response, search-excerpt answers retain their disclosure. This is not a bypass for paywalls, logins, bot protection or dynamic-only pages.

Operational checks must distinguish `done` from HTTP EOF. Title generation runs after persistence in a background thread so it cannot keep the chat connection open. Provider first-token delays remain independently measurable in response timings. Do not reduce reasoning budgets or introduce a global cancellation deadline to conceal provider latency.
