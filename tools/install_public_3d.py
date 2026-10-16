"""Install the verified optional world assets into this public JNAIQ folder."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = 'JNAIQ-Builders-0.2.0-preview.1-world-01.zip'
URL = 'https://github.com/several-dozen-lizards/JNSQ-Builders/releases/download/v0.2.0-preview.1/'+ARCHIVE
SHA256 = 'ccf4110979ab92b3921a8c068a8c46f2a21a258a79efc8c5de628f4595448ff3'
APPLICATION = 'JNAIQ-Builders-0.2.0-preview.1-application-01.zip'
APPLICATION_SHA256 = 'b5aced654003ab2ecb00b18231928908a6001f2ca141da951359650964f1cfc1'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(4*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def install(root=ROOT, archive=None):
    root = Path(root).resolve()
    if not (root/'PUBLIC_WORLDS_CANDIDATE.json').is_file():
        raise ValueError('Run this installer from the new public JNAIQ package.')
    manifest = json.loads((root/'PUBLIC_3D_ASSETS.json').read_text(encoding='utf-8'))
    for rel in manifest:
        path = PurePosixPath(rel)
        if path.is_absolute() or '..' in path.parts or '\\' in rel or ':' in rel or not rel.startswith(('godot-room/assets/objects/','assets/jnaiq/island-workshop/textures/')):
            raise ValueError('Unsafe asset destination')
        destination = (root/rel).resolve()
        if not destination.is_relative_to(root):
            raise ValueError('Asset destination leaves this installation')
        if destination.exists() and sha(destination) != manifest[rel]:
            raise ValueError('Preserving modified asset: '+rel+'. Use a new installation folder.')
    supplied = Path(archive) if archive is not None else None
    cache = supplied.parent if supplied else root/'download-cache'
    cache.mkdir(exist_ok=True)
    for name, archive_sha, prefix in [
        (APPLICATION, APPLICATION_SHA256, 'assets/'),
        (ARCHIVE, SHA256, 'godot-room/'),
    ]:
        archive = supplied if supplied and name == ARCHIVE else cache/name
        if not archive.exists() or sha(archive) != archive_sha:
            if supplied:
                raise ValueError('Supply the verified world ZIP with its application ZIP in the same folder: '+name)
            if shutil.disk_usage(root).free < 1_400_000_000:
                raise ValueError('About 1.4 GB free space is needed for download and extraction.')
            print('Downloading optional assets: '+name, flush=True)
            partial = archive.with_suffix('.partial')
            with urllib.request.urlopen(URL.rsplit('/',1)[0]+'/'+name, timeout=120) as response, partial.open('wb') as output:
                shutil.copyfileobj(response, output, 4*1024*1024)
            if sha(partial) != archive_sha:
                raise ValueError('Download checksum mismatch; rerun to retry.')
            partial.replace(archive)
        with zipfile.ZipFile(archive) as package:
            # Resolve only manifest-listed files; ignore every other ZIP member.
            for rel, digest in manifest.items():
                if not rel.startswith(prefix):continue
                target = root/rel
                if target.exists():continue
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name+'.installing')
                with package.open('JNAIQ-Builders/'+rel) as source, temporary.open('wb') as output:
                    shutil.copyfileobj(source, output)
                if sha(temporary) != digest:
                    raise ValueError('Extracted asset checksum mismatch: '+rel)
                temporary.replace(target)
    (root/'PUBLIC_3D_INSTALLED.json').write_text(json.dumps({'archive_sha256':SHA256,'files':len(manifest)}),encoding='utf-8')
    print('Optional 3D assets verified. Restart this public JNAIQ installation, then open Worlds.',flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='Reuse a previously downloaded verified world ZIP')
    install(archive=parser.parse_args().archive)
