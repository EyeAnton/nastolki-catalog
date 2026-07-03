#!/usr/bin/env python3
"""Fix BGG mismatches and add missing game entries."""
import re, json, sys, io, time
from pathlib import Path
from curl_cffi import requests as cffi_requests
from PIL import Image

sys.stdout.reconfigure(encoding='utf-8')
HTML = Path(__file__).parent / "index.html"
COVERS = Path(__file__).parent / "covers"

html = HTML.read_text(encoding='utf-8')
bgg_m = re.search(r'const BGG=(\{.*?\});', html, re.DOTALL)
d_m   = re.search(r'const D=(\[.*?\]);', html, re.DOTALL)
bgg = json.loads(bgg_m.group(1))
D   = json.loads(d_m.group(1))

# ── 1. Restore Terraforming Mars ──────────────────────────────────────────────
bgg["Terraforming Mars"] = {
    "bgg_id": 167791, "bgg_name": "Terraforming Mars", "rating": 8.4,
    "min_players": 1, "max_players": 5, "min_playtime": 120, "max_playtime": 120,
    "categories": ["Engine Building", "Science Fiction"],
    "image": "https://cf.geekdo-images.com/wg9oOLcsKvDesSUdZQ4rxw__thumb/img/uKFYkFkDcFcFN9NmrCJeBTMzOuA=/fit-in/200x150/filters:strip_icc()/pic4695386.jpg",
    "bgg_url": "https://boardgamegeek.com/boardgame/167791/terraforming-mars"
}
print("Restored: Terraforming Mars")

# ── 2. Add new games ──────────────────────────────────────────────────────────
NEW_GAMES = {
    "Hoplomachus Victorum": {
        "bgg_id": 250458, "bgg_name": "Hoplomachus Victorum", "rating": 7.4,
        "min_players": 1, "max_players": 4, "min_playtime": 45, "max_playtime": 90,
        "categories": ["Fighting", "Fantasy"],
        "image": "https://cf.geekdo-images.com/",
        "bgg_url": "https://boardgamegeek.com/boardgame/250458/hoplomachus-victorum"
    },
    "Unmatched: Cobble and Fog": {
        "bgg_id": 329826, "bgg_name": "Unmatched: Cobble & Fog", "rating": 7.9,
        "min_players": 2, "max_players": 4, "min_playtime": 20, "max_playtime": 40,
        "categories": ["Card Game", "Fighting"],
        "image": "https://cf.geekdo-images.com/",
        "bgg_url": "https://boardgamegeek.com/boardgame/329826/unmatched-cobble-fog"
    },
    "Unmatched: Jurassic Park": {
        "bgg_id": 296928, "bgg_name": "Unmatched: Jurassic Park", "rating": 7.7,
        "min_players": 2, "max_players": 2, "min_playtime": 20, "max_playtime": 40,
        "categories": ["Card Game", "Fighting"],
        "image": "https://cf.geekdo-images.com/",
        "bgg_url": "https://boardgamegeek.com/boardgame/296928/unmatched-jurassic-park-ingen-vs-raptors"
    },
    "Unmatched: Little Red vs Beowulf": {
        "bgg_id": 299665, "bgg_name": "Unmatched: Little Red Riding Hood vs. Beowulf", "rating": 7.6,
        "min_players": 2, "max_players": 2, "min_playtime": 20, "max_playtime": 40,
        "categories": ["Card Game", "Fighting"],
        "image": "https://cf.geekdo-images.com/",
        "bgg_url": "https://boardgamegeek.com/boardgame/299665/unmatched-little-red-riding-hood-vs-beowulf"
    },
}
for name, data in NEW_GAMES.items():
    bgg[name] = data
    print(f"Added:    {name}")

# ── 3. Fix Imperium→Imperiums typo in D ──────────────────────────────────────
fixed_d = 0
for item in D:
    if item['t'] == 'Imperium: Horizons':
        item['t'] = 'Imperiums: Horizons'
        fixed_d += 1
print(f"Fixed D typo: Imperium→Imperiums ({fixed_d} items)")

# ── 4. Download covers for new games via Yandex ───────────────────────────────
import html as html_module

session = cffi_requests.Session(impersonate="chrome131")

def yandex_image(query):
    r = session.get("https://yandex.ru/images/search",
        params={"text": query},
        headers={"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"},
        timeout=15)
    if r.status_code != 200:
        return None
    matches = re.findall(r'&quot;origUrl&quot;:&quot;(https?://[^&]+)&quot;', r.text)
    skip = ("instagram.com","facebook.com","twitter.com","vk.com","pinterest.com","tiktok.com")
    for raw_url in matches[:10]:
        img_url = html_module.unescape(raw_url)
        if any(d in img_url for d in skip):
            continue
        try:
            r2 = session.get(img_url, timeout=10)
            if r2.status_code == 200 and len(r2.content) >= 8000:
                return r2.content
        except Exception:
            pass
    return None

for name, data in NEW_GAMES.items():
    bid = str(data['bgg_id'])
    dest = COVERS / f"{bid}.webp"
    if dest.exists() and dest.stat().st_size >= 8000:
        print(f"  cover exists: {name}")
        continue
    content = yandex_image(f"{name} board game box")
    if content:
        try:
            img = Image.open(io.BytesIO(content)).convert("RGB")
            img.thumbnail((300, 300), Image.LANCZOS)
            img.save(dest, "WEBP", quality=82)
            print(f"  cover OK: {name} ({dest.stat().st_size//1024}KB)")
        except Exception as e:
            print(f"  cover ERR: {name} {e}")
    else:
        print(f"  cover FAIL: {name}")
    time.sleep(1.5)

# ── 5. Also restore TM cover ─────────────────────────────────────────────────
tm_cover = COVERS / "167791.webp"
if not tm_cover.exists():
    content = yandex_image("Terraforming Mars board game box")
    if content:
        img = Image.open(io.BytesIO(content)).convert("RGB")
        img.thumbnail((300, 300), Image.LANCZOS)
        img.save(tm_cover, "WEBP", quality=82)
        print(f"  TM cover: {tm_cover.stat().st_size//1024}KB")

# ── 6. Write updated HTML ─────────────────────────────────────────────────────
new_bgg = json.dumps(bgg, ensure_ascii=False, separators=(',', ':'))
new_d   = json.dumps(D,   ensure_ascii=False, separators=(',', ':'))
html = html[:bgg_m.start(1)] + new_bgg + html[bgg_m.end(1):]
# re-find D position after BGG replacement
d_m2 = re.search(r'const D=(\[.*?\]);', html, re.DOTALL)
html = html[:d_m2.start(1)] + new_d + html[d_m2.end(1):]
HTML.write_text(html, encoding='utf-8')
print(f"\nDone. BGG entries: {len(bgg)}, D items: {len(D)}")
