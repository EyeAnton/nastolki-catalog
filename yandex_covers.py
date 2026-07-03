#!/usr/bin/env python3
"""Download board game covers via Yandex Images search for games missing from Tesera."""
import re, io, json, time, sys, html as html_module
from pathlib import Path
from curl_cffi import requests as cffi_requests
from PIL import Image

sys.stdout.reconfigure(encoding='utf-8')

CATALOG_HTML = Path(__file__).parent / "index.html"
COVERS_DIR   = Path(__file__).parent / "covers"
THUMB_SIZE   = (300, 300)
MIN_BYTES    = 8000

with open(CATALOG_HTML, encoding='utf-8') as f:
    raw = f.read()
bgg_data = json.loads(re.search(r'const BGG=(\{.*?\});', raw, re.DOTALL).group(1))

# Only process games with no cover yet
to_download = {}
for name, v in bgg_data.items():
    bid = str(v.get('bgg_id', ''))
    if not bid:
        continue
    dest = COVERS_DIR / f"{bid}.webp"
    if dest.exists() and dest.stat().st_size >= MIN_BYTES:
        continue
    to_download[bid] = name

print(f"Games needing covers: {len(to_download)}\n")

session = cffi_requests.Session(impersonate="chrome131")
COVERS_DIR.mkdir(exist_ok=True)

# Domains to skip (low quality / ads / social media)
SKIP_DOMAINS = ("instagram.com", "facebook.com", "twitter.com", "vk.com",
                "youtube.com", "amazon.com", "aliexpress.com", "ebay.com",
                "wikimedia.org", "wikipedia.org", "pinterest.com", "tiktok.com")

def search_yandex_image(query):
    """Return image bytes from first usable Yandex Images result."""
    url = "https://yandex.ru/images/search"
    params = {"text": query, "isize": "large"}
    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    r = session.get(url, params=params, headers=headers, timeout=15)
    if r.status_code != 200:
        return None, None

    matches = re.findall(r'&quot;origUrl&quot;:&quot;(https?://[^&]+)&quot;', r.text)
    if not matches:
        return None, None

    for raw_url in matches[:10]:
        img_url = html_module.unescape(raw_url)
        if any(d in img_url for d in SKIP_DOMAINS):
            continue
        try:
            r2 = session.get(img_url, timeout=12)
            if r2.status_code == 200 and len(r2.content) >= MIN_BYTES:
                return r2.content, img_url
        except Exception:
            continue
    return None, None

ok = fail = 0

for bid, name in sorted(to_download.items(), key=lambda x: x[1]):
    dest = COVERS_DIR / f"{bid}.webp"
    # Try English query first, then with "board game" in Russian
    for query in [
        f"{name} board game box",
        f"{name} настольная игра коробка",
    ]:
        content, src_url = search_yandex_image(query)
        if content:
            break

    if not content:
        print(f" FAIL  [{name}]")
        fail += 1
        time.sleep(1)
        continue

    try:
        img = Image.open(io.BytesIO(content)).convert("RGB")
        w, h = img.size
        # Skip if image looks wrong (e.g. wide banner, not a box cover)
        ratio = max(w, h) / min(w, h)
        if ratio > 3:
            print(f" SKIP  [{name}] bad ratio {w}x{h}")
            fail += 1
            time.sleep(1)
            continue
        img.thumbnail(THUMB_SIZE, Image.LANCZOS)
        img.save(dest, "WEBP", quality=82)
        kb = dest.stat().st_size // 1024
        print(f"  OK   [{name}] {kb}KB  ({w}x{h} from {src_url[:60]}...)")
        ok += 1
    except Exception as e:
        print(f" ERR   [{name}] {e}")
        fail += 1

    time.sleep(1.5)

print(f"\nDone: {ok} saved, {fail} failed")
