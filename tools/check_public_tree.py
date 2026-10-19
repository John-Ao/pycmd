"""Check source/distribution inputs and decoded fixture bytes for privacy hazards."""
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.venv', 'venv', '__pycache__', 'build', 'dist', '.pytest_cache'}
FORBIDDEN_DIRS = {'references', 'validator', 'results', 'picture', 'tupian'}
ALLOWED_SUFFIXES = {'.py', '.json', '.md', '.toml', '.in', '.bat', '.yml'}
PATTERNS = [
    re.compile(r'/(?:home|Users)/[\w.-]+'),
    re.compile(r'[A-Za-z]:[\\/]+Users[\\/]+[^\s\\/"\']+', re.I),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b'),
    re.compile(r'\b(?:DESKTOP|LAPTOP)-[A-Z0-9]{5,}\b', re.I),
]


def inspect_text(text, label, errors):
    for pattern in PATTERNS:
        if pattern.search(text):
            errors.append(f'{label}: possible private value ({pattern.pattern})')
    # Construct this name so the checker does not carry the excluded reference.
    if ('cal' + 'c.bat') in text.lower():
        errors.append(f'{label}: excluded application reference')


def inspect_json(value, label, errors):
    if isinstance(value, dict):
        for key, child in value.items():
            child_label = f'{label}:{key}'
            if isinstance(child, str) and (key == 'hex' or key.endswith('_hex')):
                try:
                    raw = bytes.fromhex(child)
                except ValueError:
                    errors.append(f'{child_label}: invalid hex fixture')
                else:
                    for encoding in ('utf-8', 'utf-16-le', 'cp936'):
                        inspect_text(raw.decode(encoding, errors='replace'), child_label, errors)
            inspect_json(child, child_label, errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            inspect_json(child, f'{label}[{index}]', errors)
    elif isinstance(value, str):
        inspect_text(value, label, errors)


def main():
    errors = []
    count = 0
    for path in sorted(ROOT.rglob('*')):
        relative = path.relative_to(ROOT)
        if any(part in SKIP or part.endswith('.egg-info') for part in relative.parts):
            continue
        if path.is_symlink():
            errors.append(f'{relative}: symlink requires review')
            continue
        if not path.is_file():
            continue
        count += 1
        if any(part in FORBIDDEN_DIRS for part in relative.parts[:-1]):
            errors.append(f'{relative}: excluded source directory')
        if path.suffix not in ALLOWED_SUFFIXES and path.name not in {'.gitignore', 'LICENSE'}:
            errors.append(f'{relative}: unexpected public file type')
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeError:
            errors.append(f'{relative}: non-text file requires review')
            continue
        inspect_text(text, str(relative), errors)
        if path.suffix == '.json':
            try:
                inspect_json(json.loads(text), str(relative), errors)
            except json.JSONDecodeError:
                errors.append(f'{relative}: invalid JSON')
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'Public source check passed: {count} files, including decoded JSON fixtures.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
