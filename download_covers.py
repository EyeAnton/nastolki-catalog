#!/usr/bin/env python3
"""Download board game covers from BGG thumbnails embedded in index.html."""
import json, os, re, sys, time
import urllib.request

COVERS_DIR = os.path.join(os.path.dirname(__file__), "covers")
HTML_FILE  = os.path.join(os.path.dirname(__file__), "index.html")
MIN_BYTES  = 500

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "image/webp,image/avif,image/*,*/*;q=0.8",
    "Referer": "https://boardgamegeek.com/",
}

def load_bgg_data():
    with open(HTML_FILE, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r'const BGG=(\{.*?\});', html, re.DOTALL)
    if not m:
        sys.exit("ERROR: BGG data not found in index.html")
    return json.loads(m.group(1))

def pic_thumb_url(weserv_url):
    """Extract picXXXXX and return BGG thumbnail URL directly."""
    m = re.search(r'/(pic\d+)\.jpg', weserv_url)
    if m:
        return f"https://cf.geekdo-images.com/{m.group(1)}_thumb.jpg"
    return None

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()

def download_all():
    os.makedirs(COVERS_DIR, exist_ok=True)
    bgg = load_bgg_data()
    seen = {}
    for v in bgg.values():
        if v.get("bgg_id") and v.get("image"):
            seen[v["bgg_id"]] = v["image"]

    ok = fail = skip = 0
    for bgg_id, weserv_url in seen.items():
        dest = os.path.join(COVERS_DIR, f"{bgg_id}.webp")
        if os.path.exists(dest) and os.path.getsize(dest) >= MIN_BYTES:
            skip += 1
            continue

        data = None
        errors = []

        # Try 1: BGG direct thumbnail (picXXXXX_thumb.jpg)
        thumb_url = pic_thumb_url(weserv_url)
        if thumb_url:
            try:
                data = fetch(thumb_url)
            except Exception as e:
                errors.append(f"thumb={e}")

        # Try 2: weserv.nl proxy
        if not data or len(data) < MIN_BYTES:
            try:
                data = fetch(weserv_url)
            except Exception as e:
                errors.append(f"weserv={e}")

        if data and len(data) >= MIN_BYTES:
            with open(dest, "wb") as f:
                f.write(data)
            print(f"  OK  {bgg_id}.webp  ({len(data)} bytes)")
            ok += 1
        else:
            print(f" FAIL {bgg_id}  {' / '.join(errors)}")
            fail += 1

        time.sleep(0.1)

    print(f"\nDone: {ok} downloaded, {skip} skipped, {fail} failed")
    if fail:
        print("Re-run to retry failed downloads.")

if __name__ == "__main__":
    download_all()
