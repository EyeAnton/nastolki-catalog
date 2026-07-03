#!/usr/bin/env python3
"""
Download board game covers from Tesera.ru (accessible, no bot protection).
Uses BGG URL slug to construct Tesera game page URL.
Requires: pip install curl_cffi pillow
"""
import re, io, json, time
from pathlib import Path
from curl_cffi import requests as cffi_requests
from PIL import Image

CATALOG_HTML = Path(__file__).parent / "index.html"
COVERS_DIR   = Path(__file__).parent / "covers"
THUMB_SIZE   = (300, 300)
MIN_BYTES    = 2000

# ── load catalog ──────────────────────────────────────────────────────────────
with open(CATALOG_HTML, encoding="utf-8") as f:
    raw = f.read()
bgg_data = json.loads(re.search(r'const BGG=(\{.*?\});', raw, re.DOTALL).group(1))

games = {}
for game_name, v in bgg_data.items():
    bid = str(v.get("bgg_id", ""))
    if not bid:
        continue
    bgg_url = v.get("bgg_url", "")
    m = re.search(r'/boardgame/\d+/([^/?#\s]+)', bgg_url)
    slug = m.group(1) if m else None
    games[bid] = {"name": game_name, "slug": slug}

COVERS_DIR.mkdir(exist_ok=True)

to_download = {bid: info for bid, info in games.items()
               if not (COVERS_DIR / f"{bid}.webp").exists()
               or (COVERS_DIR / f"{bid}.webp").stat().st_size < MIN_BYTES}

print(f"Total: {len(games)} games, need covers: {len(to_download)}")

# Manual slug overrides: BGG slug -> Tesera slug
SLUG_OVERRIDES = {
    "mysterium":                        "mystery",
    "codenames-duet":                   "codenames",
    "catan":                            "the-settlers-of-catan",
    "gloomhaven-jaws-of-the-lion":      "gloomhaven-jaws-of-the-lion",
    "splendor":                         "splendor-2012",
    "inis":                             "inis-2016",
    "keyflower":                        "keyflower-base",
    "rising-sun":                       "rising-sun-2018",
}

session = cffi_requests.Session(impersonate="chrome131")

ok = fail = skip_no_slug = 0

for bid, info in sorted(to_download.items(), key=lambda x: x[1]["name"]):
    name = info["name"]
    slug = info["slug"]
    dest = COVERS_DIR / f"{bid}.webp"

    if not slug:
        print(f" SKIP  [{name}] no BGG URL slug")
        skip_no_slug += 1
        continue

    tesera_slug = SLUG_OVERRIDES.get(slug, slug)
    tesera_url = f"https://tesera.ru/game/{tesera_slug}/"

    try:
        r = session.get(tesera_url, timeout=15, headers={"Accept-Language": "ru,en"})

        if r.status_code == 404:
            print(f" 404   [{name}] not on Tesera ({slug})")
            fail += 1
            continue

        if r.status_code != 200:
            print(f" FAIL  [{name}] Tesera HTTP {r.status_code}")
            fail += 1
            continue

        # extract og:image URL
        og_m = re.search(r'og:image["\s]+content="([^"]+)"', r.text)
        if not og_m:
            print(f" FAIL  [{name}] no og:image on Tesera page")
            fail += 1
            continue

        og_url = og_m.group(1)
        # upgrade to 600x600
        img_url = og_url.replace("200x200xpa", "600x600xpa")

        r2 = session.get(img_url, timeout=15)
        if r2.status_code != 200 or len(r2.content) < MIN_BYTES:
            # fallback to 200x200
            r2 = session.get(og_url, timeout=15)

        if r2.status_code != 200 or len(r2.content) < MIN_BYTES:
            print(f" FAIL  [{name}] image HTTP {r2.status_code}")
            fail += 1
            continue

        img = Image.open(io.BytesIO(r2.content)).convert("RGB")
        img.thumbnail(THUMB_SIZE, Image.LANCZOS)
        img.save(dest, "WEBP", quality=82)
        kb = dest.stat().st_size // 1024
        print(f"  OK   [{name}] {kb}KB")
        ok += 1
        time.sleep(0.3)

    except Exception as e:
        print(f" ERR   [{name}] {e}")
        fail += 1

print(f"\nDone: {ok} saved, {fail} failed, {skip_no_slug} skipped (no slug)")
if fail:
    print("Re-run to retry failures.")
