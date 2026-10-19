"""Build distributions, remove host ownership metadata and audit their contents."""
import gzip
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

from check_public_tree import ROOT, inspect_json, inspect_text, main as check_source
import json


def normalize_sdist(path):
    with tarfile.open(path, 'r:gz') as source:
        files = [(member, source.extractfile(member).read() if member.isfile() else None)
                 for member in source.getmembers()]
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.PAX_FORMAT) as archive:
        for member, data in files:
            if not (member.isfile() or member.isdir()):
                raise ValueError(f'Unexpected archive entry: {member.name}')
            member.uid = member.gid = member.mtime = 0
            member.uname = member.gname = ''
            member.mode = 0o755 if member.isdir() else 0o644
            member.pax_headers = {}
            archive.addfile(member, io.BytesIO(data) if data is not None else None)
    # No source filename, owner, host timestamps or platform attributes in gzip.
    with path.open('wb') as output:
        with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as archive:
            archive.write(buffer.getvalue())


def audit(path):
    errors = []
    if path.suffix == '.whl':
        with zipfile.ZipFile(path) as archive:
            entries = [(name, archive.read(name)) for name in archive.namelist()]
            if not all(name.startswith('pycmd/') or '.dist-info/' in name for name, _ in entries):
                errors.append('wheel contains files outside the runtime package/metadata')
    else:
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                if member.uid or member.gid or member.uname or member.gname:
                    errors.append('sdist contains host ownership metadata')
            entries = [(member.name, archive.extractfile(member).read())
                       for member in archive.getmembers() if member.isfile()]
    for name, raw in entries:
        parts = Path(name).parts
        if any(part in {'references', 'validator', 'results', '__pycache__', '.git'} for part in parts):
            errors.append(f'{name}: excluded archive content')
        text = raw.decode('utf-8')
        inspect_text(text, name, errors)
        if name.endswith('.json'):
            inspect_json(json.loads(text), name, errors)
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'Archive check passed: {path.name} ({len(entries)} files)')


def main():
    if check_source():
        return 1
    env = dict(os.environ, SOURCE_DATE_EPOCH='315532800')
    subprocess.run([sys.executable, '-m', 'build'], cwd=ROOT, env=env, check=True)
    for path in sorted((ROOT/'dist').iterdir()):
        if path.name.endswith('.tar.gz'):
            normalize_sdist(path)
            audit(path)
        elif path.suffix == '.whl':
            audit(path)
        else:
            raise SystemExit(f'Unexpected distribution: {path.name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
