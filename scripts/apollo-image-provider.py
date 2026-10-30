#!/usr/bin/env python3
"""Call Apollo's already installed Hermes image provider in an isolated process.

The installed plugin hosts gpt-image-2 through a Codex chat model. Its pinned
gpt-5.5 host is unsupported for this account; Apollo selects a verified host
in this process without editing or restarting the Hermes gateway.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

HERMES_ROOT = Path('/usr/local/lib/hermes-agent')
PLUGIN = HERMES_ROOT / 'plugins/image_gen/openai-codex/__init__.py'


def main():
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError('Image request is too large')
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError('Invalid image request')
        prompt = str(request.get('prompt') or '').strip()
        if not 1 <= len(prompt) <= 4000:
            raise ValueError('Image prompt must be 1–4000 characters')
        references = request.get('references') or []
        if not isinstance(references, list) or len(references) > 4:
            raise ValueError('Invalid image references')
        upload_root = (Path(os.environ.get('APOLLO_BASE_DIR', '/root/Apollo')) / 'chat_uploads').resolve()
        safe_references = []
        for value in references:
            if not isinstance(value, str):
                raise ValueError('Invalid image reference')
            path = Path(value).resolve()
            if not path.is_relative_to(upload_root) or not path.is_file() or path.stat().st_size > 25_000_000:
                raise ValueError('Image reference is unavailable')
            safe_references.append(str(path))
        host_model = os.environ.get('APOLLO_IMAGE_HOST_MODEL', 'gpt-5.6-luna')
        if not re.fullmatch(r'gpt-[a-z0-9.-]{3,40}', host_model):
            raise ValueError('Invalid image host model')
        sys.path.insert(0, str(HERMES_ROOT))
        spec = importlib.util.spec_from_file_location('apollo_existing_image_provider', PLUGIN)
        if not spec or not spec.loader:
            raise RuntimeError('Image provider is unavailable')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module._CODEX_CHAT_MODEL = host_model
        result = module.OpenAICodexImageGenProvider().generate(
            prompt, aspect_ratio='square', reference_image_urls=safe_references
        )
        if result.get('success') is not True:
            error = str(result.get('error') or '')
            kind = str(result.get('error_type') or 'provider_error')
            if 'HTTP 429' in error:
                kind = 'rate_limited'
            elif 'HTTP 400' in error:
                kind = 'provider_rejected'
            print(json.dumps({'success': False, 'error_type': kind}))
            return 1
        image = Path(str(result.get('image') or '')).resolve()
        cache_root = Path('/root/.hermes/cache/images').resolve()
        if not image.is_relative_to(cache_root) or not image.is_file() or image.stat().st_size > 25_000_000:
            raise RuntimeError('Provider returned an invalid image file')
        with image.open('rb') as source:
            if source.read(8) != b'\x89PNG\r\n\x1a\n':
                raise RuntimeError('Provider returned a non-PNG file')
        print(json.dumps({'success': True, 'image_path': str(image),
                          'image_bytes': image.stat().st_size,
                          'edited': bool(safe_references)}))
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, TypeError) as error:
        print(json.dumps({'success': False, 'error_type': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
