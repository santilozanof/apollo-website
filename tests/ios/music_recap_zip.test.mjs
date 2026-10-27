import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('recap download-all creates a readable ZIP with all three PNGs', async () => {
  const source = readFileSync('apollo_music_insights.js', 'utf8');
  const start = source.indexOf('async function zipPngs(entries)');
  const end = source.indexOf('\n  async function loadRecap()', start);
  assert.ok(start >= 0 && end > start);
  const zipPngs = new Function(`${source.slice(start, end)}; return zipPngs;`)();
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==', 'base64');
  const archive = await zipPngs([
    {name: 'apollo-overview.png', blob: new Blob([png])},
    {name: 'apollo-top-songs.png', blob: new Blob([png])},
    {name: 'apollo-discoveries.png', blob: new Blob([png])},
  ]);
  const directory = mkdtempSync(join(tmpdir(), 'apollo-recap-zip-'));
  try {
    const file = join(directory, 'recap.zip');
    writeFileSync(file, Buffer.from(await archive.arrayBuffer()));
    execFileSync('unzip', ['-t', file]);
    for (const name of ['apollo-overview.png', 'apollo-top-songs.png', 'apollo-discoveries.png']) {
      assert.deepEqual(execFileSync('unzip', ['-p', file, name]), png);
    }
  } finally {
    rmSync(directory, {recursive: true, force: true});
  }
});
