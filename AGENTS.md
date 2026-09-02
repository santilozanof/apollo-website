# Apollo review workflow

For every UI change, review only the current `dev` working tree:

1. Stop any existing process listening on the local preview port.
2. Start `python3 preview_local.py --port 8765` from this repository root.
3. Confirm `/__preview_meta__` reports branch `dev` and the current `HEAD` commit.
4. Confirm HTML, CSS, and JavaScript responses include `Cache-Control: no-store`.
5. Open a new browser tab at `http://127.0.0.1:8765/?preview=<full-current-commit>`.
6. Verify the rendered DOM and computed styles contain the intended current changes before presenting the preview.

Never use a `file://` URL, reuse an old local server, or reuse an old browser tab for UI review.
