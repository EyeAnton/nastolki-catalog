#!/usr/bin/env python3
"""
Download board game covers into covers/{bgg_id}.webp (fit into 300x300, WebP q=82).

Default source: Tesera.ru og:image (slug from the BGG URL, see SLUG_OVERRIDES).
Per-game sources in COVER_SOURCES pin the exact edition when Tesera gives the wrong
one (Russian instead of English, an unrelated game, a placeholder):
    ("tesera", slug)          Tesera game page
    ("bgg", None)             BGG primary image (api.geekdo.com, no key needed)
    ("bggversion", version)   image of a specific BGG version (e.g. Russian edition)

Usage:
    python download_bgg_covers.py                 # only games without a cover
    python download_bgg_covers.py --ids 1,2,3     # (re)download these ids, overwriting
    python download_bgg_covers.py --ids 1,2 --out /tmp/x   # write candidates elsewhere to compare

Always check new covers visually (contact sheet) before committing:
Tesera often has only the Russian edition, and slugs can point to another game.
Requires: pip install curl_cffi pillow
"""
import argparse, io, json, re, time
from pathlib import Path
from curl_cffi import requests as cffi_requests
from PIL import Image, ImageChops

ROOT         = Path(__file__).parent
CATALOG_HTML = ROOT / "index.html"
THUMB_SIZE   = (300, 300)
MIN_BYTES    = 2000

# Manual slug overrides: BGG slug -> Tesera slug
SLUG_OVERRIDES = {
    "mysterium":                        "mystery",
    "codenames-duet":                   "codenames",
    "catan":                            "the-settlers-of-catan",
    "gloomhaven-jaws-of-the-lion":      "gloomhaven-jaws-of-the-Lion",
    "splendor":                         "splendor-2012",
    "inis":                             "inis-2016",
    "keyflower":                        "keyflower-base",
    "rising-sun":                       "rising-sun-2018",
    "sleeping-gods":                    "Sleeping-Gods",
    "sleeping-gods-tides-of-ruin":      "Sleeping-Gods-Tides-of-Ruin",
    "sleeping-gods-dungeons":           "SleepingGodsDungeons",
    "paper-dungeons-a-dungeon-scrawler-game": "paper-dungeons",
    "tales-of-tails":                   "podzemelya-i-pesiki",
}

# Pinned sources by bgg_id (checked visually 2026-11-19)
COVER_SOURCES = {
    291457: ("bggversion", 577944),   # Gloomhaven: JotL - Russian edition (Tesera has a placeholder)
    255984: ("bgg", None),            # Sleeping Gods - English edition
    283766: ("bgg", None),            # Sleeping Gods: Tides of Ruin - English edition
    287670: ("bgg", None),            # Sleeping Gods: Dungeons - English edition
    16443:  ("tesera", "dungeoneer-dragons-of-the-forsaken-desert"),
    180974: ("tesera", "potion-explosion"),       # "Лаборатория" (Russian Potion Explosion)
    422437: ("tesera", "podzemelya-i-pesiki"),
    244918: ("tesera", "exit-the-game-the-mysterious-museum"),
    327076: ("tesera", "cartaventura-lhassa"),
    364073: ("tesera", "splendor-duel"),
}

session = cffi_requests.Session(impersonate="chrome131")


def get_bytes(url):
    r = session.get(url, timeout=30)
    if r.status_code == 200 and len(r.content) >= MIN_BYTES:
        return r.content
    return None


def from_tesera(slug):
    r = session.get(f"https://tesera.ru/game/{slug}/", timeout=15, headers={"Accept-Language": "ru,en"})
    if r.status_code != 200:
        raise RuntimeError(f"Tesera HTTP {r.status_code} ({slug})")
    og = re.search(r'og:image["\s]+content="([^"]+)"', r.text)
    if not og:
        raise RuntimeError("no og:image on Tesera page")
    url = og.group(1)
    if not re.search(r'\.(jpe?g|png|webp)$', url, re.I):
        raise RuntimeError("Tesera has no cover (placeholder)")
    return get_bytes(url.replace("200x200xpa", "600x600xpa")) or get_bytes(url)


def from_geekdo(objectid, objecttype):
    r = session.get("https://api.geekdo.com/api/geekitems",
                    params={"objectid": objectid, "objecttype": objecttype}, timeout=20)
    item = (r.json() or {}).get("item") or {}
    imgs = item.get("images") or {}
    url = imgs.get("original") or item.get("imageurl")
    if not url:
        raise RuntimeError(f"no image for BGG {objecttype} {objectid}")
    return get_bytes(url)


def trim_white(img):
    """Crop the near-white padding Tesera adds around boxes."""
    bg = Image.new("RGB", img.size, (255, 255, 255))
    diff = ImageChops.difference(img, bg).convert("L").point(lambda v: 255 if v > 12 else 0)
    box = diff.getbbox()
    return img.crop(box) if box else img


def save_cover(data, dest):
    img = Image.open(io.BytesIO(data))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    img = trim_white(img.convert("RGB"))
    img.thumbnail(THUMB_SIZE, Image.LANCZOS)
    img.save(dest, "WEBP", quality=82)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="comma-separated bgg ids to (re)download, overwriting")
    ap.add_argument("--out", default=str(ROOT / "covers"), help="output dir")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    raw = CATALOG_HTML.read_text(encoding="utf-8")
    bgg_data = json.loads(re.search(r'const BGG=(\{.*?\});', raw, re.DOTALL).group(1))
    games = {}
    for game_name, v in bgg_data.items():
        if not v.get("bgg_id"):
            continue
        m = re.search(r'/boardgame/\d+/([^/?#\s]+)', v.get("bgg_url") or "")
        games[int(v["bgg_id"])] = {"name": game_name, "slug": m.group(1) if m else None}

    if args.ids:
        want = {int(x) for x in args.ids.split(",") if x.strip()}
        todo = {b: games.get(b, {"name": str(b), "slug": None}) for b in want}
    else:
        todo = {b: i for b, i in games.items()
                if not (out / f"{b}.webp").exists() or (out / f"{b}.webp").stat().st_size < MIN_BYTES}
    print(f"Total: {len(games)} games, to download: {len(todo)}")

    ok = fail = 0
    for bid, info in sorted(todo.items(), key=lambda x: x[1]["name"]):
        name = info["name"]
        kind, arg = COVER_SOURCES.get(bid, ("tesera", None))
        if kind == "tesera" and not arg:
            arg = SLUG_OVERRIDES.get(info["slug"], info["slug"]) if info["slug"] else None
        try:
            if kind == "tesera":
                if not arg:
                    raise RuntimeError("no BGG URL slug")
                data = from_tesera(arg)
            elif kind == "bgg":
                data = from_geekdo(bid, "thing")
            else:
                data = from_geekdo(arg, "version")
            if not data:
                raise RuntimeError("image download failed")
            dest = out / f"{bid}.webp"
            save_cover(data, dest)
            print(f"  OK   [{name}] {kind}:{arg or bid} {dest.stat().st_size // 1024}KB")
            ok += 1
            time.sleep(0.3)
        except Exception as e:
            print(f" FAIL  [{name}] {kind}:{arg} {e}")
            fail += 1

    print(f"\nDone: {ok} saved, {fail} failed")


if __name__ == "__main__":
    main()
