#!/usr/bin/env python3
"""Compare deterministic routing/continuity cases against a Git baseline.

This is a synthetic, read-only evaluation. It does not grade model answer
quality or assert that external accounts are connected.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import time
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_source(label, source):
    with tempfile.NamedTemporaryFile('w', suffix='.py', prefix='apollo-eval-', delete=False) as file:
        file.write(source)
        path = Path(file.name)
    try:
        spec = importlib.util.spec_from_file_location(label, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        path.unlink(missing_ok=True)


def baseline_file(revision, name):
    result = subprocess.run(
        ['git', '-C', str(ROOT), 'show', f'{revision}:{name}'],
        capture_output=True, text=True, check=True, timeout=10,
    )
    return load_source('baseline_' + name.replace('.', '_'), result.stdout)


def measure(call):
    samples = []
    outcome = None
    for _ in range(30):
        start = time.perf_counter()
        outcome = call()
        samples.append((time.perf_counter() - start) * 1000)
    return outcome, round(sorted(samples)[len(samples) // 2], 4)


def spotify_case(module):
    class Spotify:
        def search(self, q, type, limit):
            if q.startswith('track:'):
                return {'tracks': {'items': []}}
            return {'tracks': {'items': [
                {'name': 'Unrelated song', 'id': 'wrong'},
                {'name': '#TETAS', 'id': 'verified',
                 'artists': [{'name': 'CA7RIEL & Paco Amoroso'}],
                 'album': {'name': 'Album', 'images': [
                     {'url': 'https://i.scdn.co/image/verified', 'width': 640, 'height': 640}]},
                 'external_urls': {'spotify': 'https://open.spotify.com/track/verified'}},
            ]}}
    with mock.patch.object(module, 'spotify_read', side_effect=lambda call, **_: call()):
        return module.entity_search(Spotify(), 'song', '#tetas')


def run(revision):
    old_media = baseline_file(revision, 'apollo_media.py')
    new_media = load_source('candidate_media', (ROOT / 'apollo_media.py').read_text())
    old_spotify = baseline_file(revision, 'spotify_curator_tool.py')
    new_spotify = load_source('candidate_spotify', (ROOT / 'spotify_curator_tool.py').read_text())
    old_intelligence = baseline_file(revision, 'apollo_intelligence.py')
    new_intelligence = load_source('candidate_intelligence', (ROOT / 'apollo_intelligence.py').read_text())
    conversation = [
        {'role': 'user', 'content': '#tetas'},
        {'role': 'assistant', 'content': '¿Te refieres a una canción?'},
        {'role': 'user', 'content': 'es una canción'},
        {'role': 'user', 'content': 'búscala'},
    ]
    cases = [
        ('Spanish multi-turn image subject', lambda m: m.visual_request('enséñame una foto', conversation),
         '#tetas', old_media, new_media),
        ('Unseen Spanish hashtag follow-up', lambda m: m.visual_request('enséñame una foto', [
            {'role': 'user', 'content': '#marea'},
            {'role': 'user', 'content': 'es una canción'},
            {'role': 'user', 'content': 'búscala'},
        ]), '#marea', old_media, new_media),
        ('General image follow-up', lambda m: m.visual_request(
            'Show me images of it', [{'role': 'user', 'content': 'FL Studio'}]),
         'fl-studio', old_media, new_media),
        ('Spanish generation intent', lambda m: bool(getattr(m, 'generation_request', lambda _: False)(
            'haz una imagen de un sigma looksmaxxer con toda la huzz')),
         True, old_media, new_media),
        ('Exact Spotify artwork lookup', spotify_case, 'verified', old_spotify, new_spotify),
        ('Named-month listening stats', lambda m: [
            m.personal_music_history_request('Show me my Spotify stats from September'),
            *[m.music_history_initial_args('Show me my Spotify stats from September', {
                'local_time': '2026-10-30T12:00:00+01:00',
                'time_zone': 'Europe/Zurich',
            })[key] for key in ('period', 'anchor')],
        ], [True, 'monthly', '2026-09-01'], old_intelligence, new_intelligence),
    ]
    results = []
    for title, function, expected, old, new in cases:
        old_value, old_ms = measure(lambda: function(old))
        new_value, new_ms = measure(lambda: function(new))
        if title == 'Exact Spotify artwork lookup':
            old_value = old_value.get('provider_id') if old_value else None
            new_value = new_value.get('provider_id') if new_value else None
        results.append({
            'case': title, 'expected': expected,
            'baseline': {'value': old_value, 'correct': old_value == expected,
                         'median_local_ms': old_ms},
            'candidate': {'value': new_value, 'correct': new_value == expected,
                          'median_local_ms': new_ms},
        })
    return {'baseline_revision': revision, 'evaluation': 'synthetic_deterministic',
            'results': results, 'baseline_correct': sum(item['baseline']['correct'] for item in results),
            'candidate_correct': sum(item['candidate']['correct'] for item in results)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', default='c231f0c78348923fa208c0a8810323ce5257d9f4')
    args = parser.parse_args()
    print(json.dumps(run(args.baseline), ensure_ascii=False, indent=2))
