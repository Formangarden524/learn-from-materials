"""Local, source-confirmed book covers embedded for offline HTML."""
import base64
import hashlib
from pathlib import Path


def load_cover(path, title, source_page=None):
    path = Path(path).expanduser()
    raw = path.read_bytes()
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('Cover image exceeds 8 MiB; use a smaller source image')
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        mime = 'image/png'
    elif raw.startswith(b'\xff\xd8\xff'):
        mime = 'image/jpeg'
    elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        mime = 'image/webp'
    else:
        raise ValueError('Cover must be a local PNG, JPEG or WebP image')
    if source_page is not None and (type(source_page) is not int or source_page < 1):
        raise ValueError('Cover source page must be a positive physical PDF page')
    return {'dataUrl': 'data:' + mime + ';base64,' + base64.b64encode(raw).decode('ascii'),
            'sha256': hashlib.sha256(raw).hexdigest(), 'alt': str(title) + ' · 原书封面',
            'sourcePage': source_page,
            'sourceLabel': '原书封面' + (' · PDF第' + str(source_page) + '页' if source_page else '')}
