"""Restore the original CSV tables and verify their checksums."""
from pathlib import Path
import gzip
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
manifest = json.loads((DATA / 'compressed-manifest.json').read_text())
for item in manifest['files']:
    if Path(item['file']).name != item['file']:
        raise ValueError('Invalid table name')
    compressed = b''
    for part in item['parts']:
        content = (DATA / 'compressed' / part['name']).read_bytes()
        if hashlib.sha256(content).hexdigest() != part['sha256']:
            raise ValueError('Corrupt part: ' + part['name'])
        compressed += content
    content = gzip.decompress(compressed)
    if hashlib.sha256(content).hexdigest() != item['sha256']:
        raise ValueError('CSV checksum mismatch: ' + item['file'])
    destination = DATA / item['file']
    destination.write_bytes(content)
    print(item['file'])
