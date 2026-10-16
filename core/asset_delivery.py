"""Select verified, prepared texture variants without changing source assets.

Requests never perform image compression. A changed source invalidates the
prepared variant immediately; authoring and ownership checks retain the source.
"""
import hashlib
import json
from pathlib import Path
from functools import lru_cache

REVISION = 'textures-2'


@lru_cache(maxsize=1024)
def _digest(path, size, modified):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def digest(path):
    stat = Path(path).stat()
    return _digest(str(path), stat.st_size, stat.st_mtime_ns)


def delivery_headers(source, prepared, source_digest=None):
    return {'Cache-Control': 'no-cache',
            'X-JNAIQ-Source-SHA256': source_digest or digest(source),
            'X-JNAIQ-Model-SHA256': digest(prepared)}


def variant_paths(source, tier='standard', *, revision=REVISION):
    if tier not in {'compact', 'standard'}:
        raise ValueError('Expected compact or standard')
    source = Path(source).resolve()
    stat = source.stat()
    signature = f'{revision}:{source.name}:{stat.st_size}:{stat.st_mtime_ns}'
    key = hashlib.sha256(signature.encode()).hexdigest()[:24]
    directory = source.parent / '.asset-quality' / tier
    return directory / (key + '.glb'), directory / (key + '.json')


def model_path(source, tier='standard'):
    source = Path(source)
    if tier == 'high':
        return str(source)
    choices = ('compact', 'standard') if tier == 'compact' else (tier,)
    for choice in choices:
        prepared, receipt = variant_paths(source, choice)
        try:
            report = json.loads(receipt.read_text(encoding='utf-8'))
            if (report['revision'] == REVISION and prepared.stat().st_size == report['bytes']
                    and digest(prepared) == report['sha256']):
                return str(prepared)
        except (OSError, ValueError, KeyError):
            pass
    return str(source)
