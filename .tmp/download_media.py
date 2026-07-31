from charts.models import Artist, NewsArticle, Release
from django.conf import settings
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time

CLOUD_NAME = 'dziftdkyo'
MEDIA_ROOT = Path(settings.MEDIA_ROOT)

items = []
seen = set()

def add(kind, pk, name):
    name = str(name or '').strip()
    if not name or name.startswith(('http://', 'https://')):
        return
    key = name.replace('\\', '/')
    if key in seen:
        return
    seen.add(key)
    target = MEDIA_ROOT / key
    if target.exists() and target.stat().st_size > 0:
        return
    url = f"https://res.cloudinary.com/{CLOUD_NAME}/image/upload/v1/{quote(key, safe='/')}"
    items.append((kind, pk, key, target, url))

for artist in Artist.objects.exclude(image=''):
    add('artist', artist.id, artist.image.name)
for release in Release.objects.exclude(cover_image=''):
    add('release', release.id, release.cover_image.name)
for article in NewsArticle.objects.exclude(cover_image=''):
    add('news', article.id, article.cover_image.name)

start = time.time()

def download(item):
    kind, pk, key, target, url = item
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + '.tmp')
    req = Request(url, headers={'User-Agent': 'NgomaChartsLocalSync/1.0'})
    with urlopen(req, timeout=30) as response:
        data = response.read()
    if not data:
        raise RuntimeError('empty response')
    tmp.write_bytes(data)
    tmp.replace(target)
    return key, len(data)

ok = 0
failed = []
bytes_written = 0
workers = 12
with ThreadPoolExecutor(max_workers=workers) as executor:
    futures = {executor.submit(download, item): item for item in items}
    for i, future in enumerate(as_completed(futures), 1):
        item = futures[future]
        try:
            _, size = future.result()
            ok += 1
            bytes_written += size
        except Exception as exc:
            failed.append({'kind': item[0], 'id': item[1], 'path': item[2], 'error': str(exc)[:180]})
        if i % 100 == 0:
            print(json.dumps({'processed': i, 'ok': ok, 'failed': len(failed)}, ensure_ascii=False), flush=True)

print(json.dumps({
    'attempted': len(items),
    'downloaded': ok,
    'failed': len(failed),
    'bytes_written': bytes_written,
    'seconds': round(time.time() - start, 1),
    'failed_sample': failed[:20],
}, ensure_ascii=False, indent=2))
