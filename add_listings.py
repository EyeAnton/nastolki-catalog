#!/usr/bin/env python3
"""Add game listings from spreadsheet + fetch missing covers."""
import re, json, io, sys, time, html as html_module
from pathlib import Path
from curl_cffi import requests as cffi_requests
from PIL import Image

sys.stdout.reconfigure(encoding='utf-8')
HTML   = Path(__file__).parent / "index.html"
COVERS = Path(__file__).parent / "covers"

html_src = HTML.read_text(encoding='utf-8')
bgg_m = re.search(r'const BGG=(\{.*?\});', html_src, re.DOTALL)
d_m   = re.search(r'const D=(\[.*?\]);',   html_src, re.DOTALL)
BGG = json.loads(bgg_m.group(1))
D   = json.loads(d_m.group(1))

MSG_ID = 4916
DATE   = "03.07.2026"

# ── New BGG entries to add ─────────────────────────────────────────────────────
# Format: key → {bgg_id, rating, players, playtime, categories, bgg_url, bgg_name}
NEW_BGG = {
    "Nemesis: Aftermath": {
        "bgg_id": 371942, "bgg_name": "Nemesis: Aftermath", "rating": 8.4,
        "min_players": 1, "max_players": 5, "min_playtime": 90, "max_playtime": 180,
        "categories": ["Cooperative", "Horror", "Science Fiction"],
        "bgg_url": "https://boardgamegeek.com/boardgame/371942/nemesis-aftermath",
    },
    "The Lord of the Rings: Fate of the Fellowship": {
        "bgg_id": 353218, "bgg_name": "The Lord of the Rings: Fate of the Fellowship", "rating": 8.3,
        "min_players": 2, "max_players": 4, "min_playtime": 60, "max_playtime": 120,
        "categories": ["Cooperative", "Fantasy"],
        "bgg_url": "https://boardgamegeek.com/boardgame/353218/the-lord-of-the-rings-fate-of-the-fellowship",
    },
    "Zombicide: Undead or Alive": {
        "bgg_id": 325494, "bgg_name": "Zombicide: Undead or Alive", "rating": 8.0,
        "min_players": 1, "max_players": 6, "min_playtime": 60, "max_playtime": 120,
        "categories": ["Cooperative", "Zombies", "Western"],
        "bgg_url": "https://boardgamegeek.com/boardgame/325494/zombicide-undead-or-alive",
    },
    "Zombicide: Undead or Alive – Steam Age": {
        "bgg_id": 345453, "bgg_name": "Zombicide: Undead or Alive – Steam Age", "rating": 8.2,
        "min_players": 1, "max_players": 6, "min_playtime": 60, "max_playtime": 120,
        "categories": ["Cooperative", "Zombies", "Steampunk"],
        "bgg_url": "https://boardgamegeek.com/boardgame/345453/zombicide-undead-or-alive-steam-age",
    },
    "Cthulhu: Death May Die – Season 4": {
        "bgg_id": 389102, "bgg_name": "Cthulhu: Death May Die – Season 4", "rating": 8.9,
        "min_players": 1, "max_players": 5, "min_playtime": 90, "max_playtime": 150,
        "categories": ["Cooperative", "Horror", "Lovecraftian"],
        "bgg_url": "https://boardgamegeek.com/boardgame/389102/cthulhu-death-may-die-season-4",
    },
    "Eldritch Horror: The Dreamlands": {
        "bgg_id": 205691, "bgg_name": "Eldritch Horror: The Dreamlands", "rating": 8.5,
        "min_players": 1, "max_players": 8, "min_playtime": 120, "max_playtime": 240,
        "categories": ["Cooperative", "Horror", "Lovecraftian"],
        "bgg_url": "https://boardgamegeek.com/boardgame/205691/eldritch-horror-the-dreamlands",
    },
    "Spirit Island: Jagged Earth": {
        "bgg_id": 278254, "bgg_name": "Spirit Island: Jagged Earth", "rating": 9.3,
        "min_players": 1, "max_players": 6, "min_playtime": 90, "max_playtime": 180,
        "categories": ["Cooperative", "Area Control"],
        "bgg_url": "https://boardgamegeek.com/boardgame/278254/spirit-island-jagged-earth",
    },
    "Carnegie": {
        "bgg_id": 310873, "bgg_name": "Carnegie", "rating": 8.0,
        "min_players": 1, "max_players": 4, "min_playtime": 120, "max_playtime": 200,
        "categories": ["Euro", "Worker Placement"],
        "bgg_url": "https://boardgamegeek.com/boardgame/310873/carnegie",
    },
    "Dune: Imperium – Bloodlines": {
        "bgg_id": 432083, "bgg_name": "Dune: Imperium – Bloodlines", "rating": 8.7,
        "min_players": 1, "max_players": 4, "min_playtime": 60, "max_playtime": 120,
        "categories": ["Deck Building", "Worker Placement"],
        "bgg_url": "https://boardgamegeek.com/boardgame/432083/dune-imperium-bloodlines",
    },
    "Dune: Imperium – Rise of Ix": {
        "bgg_id": 334382, "bgg_name": "Dune: Imperium – Rise of Ix", "rating": 8.8,
        "min_players": 1, "max_players": 4, "min_playtime": 60, "max_playtime": 120,
        "categories": ["Deck Building", "Worker Placement"],
        "bgg_url": "https://boardgamegeek.com/boardgame/334382/dune-imperium-rise-of-ix",
    },
    "Paleo: A New Beginning": {
        "bgg_id": 374990, "bgg_name": "Paleo: A New Beginning", "rating": 8.2,
        "min_players": 2, "max_players": 4, "min_playtime": 45, "max_playtime": 75,
        "categories": ["Cooperative", "Survival"],
        "bgg_url": "https://boardgamegeek.com/boardgame/374990/paleo-a-new-beginning",
    },
    "Unmatched: Adventures, vol. 1": {
        "bgg_id": 363752, "bgg_name": "Unmatched Adventures: Tales to Amaze", "rating": 7.7,
        "min_players": 1, "max_players": 4, "min_playtime": 20, "max_playtime": 40,
        "categories": ["Card Game", "Cooperative"],
        "bgg_url": "https://boardgamegeek.com/boardgame/363752/unmatched-adventures-tales-to-amaze",
    },
    "Dice Throne": {
        "bgg_id": 245423, "bgg_name": "Dice Throne", "rating": 7.6,
        "min_players": 2, "max_players": 6, "min_playtime": 20, "max_playtime": 40,
        "categories": ["Dice", "Fighting"],
        "bgg_url": "https://boardgamegeek.com/boardgame/245423/dice-throne",
    },
}

# Add image placeholder (will be replaced with actual BGG CDN or local cover)
for k, v in NEW_BGG.items():
    v["image"] = f"https://boardgamegeek.com/boardgame/{v['bgg_id']}/"

for key, data in NEW_BGG.items():
    if key not in BGG:
        BGG[key] = data
        print(f"BGG added: {key}")
    else:
        print(f"BGG exists: {key}")

# ── New D listings ─────────────────────────────────────────────────────────────
# (title, lang, price_AMD, note)
NEW_LISTINGS = [
    ("Hoplomachus Victorum",                   "ENG", 44000, ""),
    ("Nemesis: Aftermath",                      "ENG", 19000, ""),
    ("The Lord of the Rings: Fate of the Fellowship", "ENG", 32000, ""),
    ("Imperiums: Horizons",                     "ENG", 21000, ""),
    ("Zombicide: Undead or Alive",              "РУС", 35000, ""),
    ("Zombicide: Undead or Alive – Steam Age",  "РУС", 12000, ""),
    ("Cthulhu: Death May Die – Season 4",       "ENG", 24000, ""),
    ("Eldritch Horror",                         "РУС", 18000, ""),
    ("Eldritch Horror: The Dreamlands",         "РУС", 12000, ""),
    ("The Great Western Trail",                 "РУС", 17000, ""),
    ("Spirit Island",                           "РУС", 25000, ""),
    ("Spirit Island: Jagged Earth",             "РУС", 22000, ""),
    ("Carnegie",                                "РУС", 22000, ""),
    ("Lost Ruins of Arnak",                     "РУС", 19000, ""),
    ("Dune: Imperium – Bloodlines",             "ENG", 13000, ""),
    ("Dune: Imperium – Rise of Ix",             "РУС", 14000, ""),
    ("Paleo",                                   "РУС", 13000, ""),
    ("Paleo: A New Beginning",                  "РУС",  7000, ""),
    ("Castles of Burgundy",                     "ENG", 21000, ""),
    ("Underwater Cities",                       "ENG", 22000, ""),
    ("Unmatched: Cobble and Fog",               "РУС", 13000, ""),
    ("Unmatched: Adventures, vol. 1",           "РУС", 16000, ""),
    ("Dice Throne",                             "ENG", 11000, "2 boxes left"),
]

added = 0
for title, lang, price, note in NEW_LISTINGS:
    if title not in BGG:
        print(f"  WARNING: no BGG entry for '{title}' — skipping")
        continue
    D.append({"t": title, "s": "", "p": price, "l": lang, "n": note, "d": DATE, "m": MSG_ID})
    added += 1
    print(f"D added: {title} — {price:,} ֏ ({lang})")

print(f"\nAdded {added} listings, D total: {len(D)}")

# ── Download covers for new BGG entries ───────────────────────────────────────
session = cffi_requests.Session(impersonate="chrome131")
SKIP = ("instagram.com","facebook.com","twitter.com","vk.com","pinterest.com","tiktok.com","youtube.com")

def yandex_cover(query):
    r = session.get("https://yandex.ru/images/search",
        params={"text": query},
        headers={"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"}, timeout=15)
    if r.status_code != 200:
        return None
    matches = re.findall(r'&quot;origUrl&quot;:&quot;(https?://[^&]+)&quot;', r.text)
    for raw in matches[:10]:
        url = html_module.unescape(raw)
        if any(d in url for d in SKIP):
            continue
        try:
            r2 = session.get(url, timeout=10)
            if r2.status_code == 200 and len(r2.content) >= 8000:
                return r2.content
        except Exception:
            pass
    return None

print("\nDownloading covers for new games...")
for key, data in NEW_BGG.items():
    bid = str(data["bgg_id"])
    dest = COVERS / f"{bid}.webp"
    if dest.exists() and dest.stat().st_size >= 5000:
        print(f"  exists: {key}")
        continue
    content = yandex_cover(f"{data['bgg_name']} board game box")
    if content:
        try:
            img = Image.open(io.BytesIO(content)).convert("RGB")
            img.thumbnail((300, 300), Image.LANCZOS)
            img.save(dest, "WEBP", quality=82)
            print(f"  OK: {key} ({dest.stat().st_size//1024}KB)")
        except Exception as e:
            print(f"  ERR: {key} — {e}")
    else:
        print(f"  FAIL: {key}")
    time.sleep(1.5)

# ── Write updated HTML ─────────────────────────────────────────────────────────
new_bgg = json.dumps(BGG, ensure_ascii=False, separators=(',', ':'))
new_d   = json.dumps(D,   ensure_ascii=False, separators=(',', ':'))
out = html_src[:bgg_m.start(1)] + new_bgg + html_src[bgg_m.end(1):]
d_m2 = re.search(r'const D=(\[.*?\]);', out, re.DOTALL)
out = out[:d_m2.start(1)] + new_d + out[d_m2.end(1):]
HTML.write_text(out, encoding='utf-8')
print(f"\nSaved index.html — BGG: {len(BGG)}, D: {len(D)}")
