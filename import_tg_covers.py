#!/usr/bin/env python3
"""
Parse Telegram chat export, extract board game covers by BGG ID, compress to WebP.
Matches by: 1) BGG URL  2) Hashtag  3) Game name in text
Requires: pillow  (pip install pillow)
"""
import re, json
from pathlib import Path

EXPORT_DIR   = Path(r"C:\Users\Asus ProArt\Downloads\Telegram Desktop\ChatExport_2026-07-01")
CATALOG_HTML = Path(__file__).parent / "index.html"
COVERS_DIR   = Path(__file__).parent / "covers"
THUMB_SIZE   = (300, 300)

# ── load catalog ──────────────────────────────────────────────────────────────
with open(CATALOG_HTML, encoding="utf-8") as f:
    raw = f.read()
bgg_data = json.loads(re.search(r'const BGG=(\{.*?\});', raw, re.DOTALL).group(1))
catalog_ids = {str(v["bgg_id"]) for v in bgg_data.values() if v.get("bgg_id")}
id_to_name  = {str(v["bgg_id"]): k for k, v in bgg_data.items() if v.get("bgg_id")}

# ── slug → bgg_id map ─────────────────────────────────────────────────────────
def to_slug(name):
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')

slug_to_id = {}
for game_name, v in bgg_data.items():
    bid = str(v.get("bgg_id", ""))
    if not bid:
        continue
    for candidate in [game_name, v.get("bgg_name", "")]:
        slug_to_id[to_slug(candidate)] = bid
    m = re.search(r'/boardgame/\d+/([^/?#\s]+)', v.get("bgg_url", ""))
    if m:
        slug_to_id[m.group(1).replace('-', '_')] = bid

# ── name → bgg_id map for text matching (longer names first to avoid short word conflicts) ─
# Only use names ≥ 5 chars to avoid false matches like "Root", "Inis", "Canvas"
SHORT_NAMES = {"Root", "Inis", "Canvas", "Dixit", "Catan"}   # handle manually
name_patterns = []
for game_name, v in bgg_data.items():
    bid = str(v.get("bgg_id", ""))
    if not bid:
        continue
    names_to_try = [game_name, v.get("bgg_name", "")]
    for nm in names_to_try:
        if nm and (len(nm) >= 8 or nm in SHORT_NAMES):
            # escape for regex
            pat = re.compile(re.escape(nm), re.IGNORECASE)
            name_patterns.append((pat, bid, nm))
# sort by pattern length desc so longer/more-specific names match first
name_patterns.sort(key=lambda x: len(x[2]), reverse=True)

print(f"Catalog: {len(catalog_ids)} games, {len(slug_to_id)} slugs, {len(name_patterns)} name patterns")

# ── regex patterns ────────────────────────────────────────────────────────────
MSG_SPLIT  = re.compile(r'<div class="message default clearfix(?P<joined> joined)?" id="message\d+">')
PHOTO_RE   = re.compile(r'href="(photos/photo_[^"]+\.(?:jpg|png))"')
BGG_RE     = re.compile(r'boardgamegeek\.com/boardgame/(\d+)')
HASHTAG_RE = re.compile(r'ShowHashtag\(&quot;([^&"]+)&quot;\)')

def strip_html(s):
    return re.sub(r'<[^>]+>', ' ', s)

results = {}   # bgg_id_str -> first photo Path

def process_group(block_html):
    photos = PHOTO_RE.findall(block_html)
    if not photos:
        return

    first_photo = EXPORT_DIR / photos[0]
    bgg_ids = set()

    # 1. BGG direct links
    bgg_ids.update(BGG_RE.findall(block_html))

    # 2. Hashtags
    for tag in HASHTAG_RE.findall(block_html):
        slug = tag.replace('-', '_')
        if slug in slug_to_id:
            bid = slug_to_id[slug]
            if bid:
                bgg_ids.add(bid)

    # 3. Game name in plain text
    plain = strip_html(block_html)
    for pat, bid, _ in name_patterns:
        if pat.search(plain):
            bgg_ids.add(bid)

    for bid in bgg_ids:
        if bid in catalog_ids and bid not in results:
            results[bid] = first_photo

for fname in ["messages.html", "messages2.html"]:
    fpath = EXPORT_DIR / fname
    if not fpath.exists():
        continue
    print(f"Parsing {fname}...")
    content = fpath.read_text(encoding="utf-8", errors="replace")

    positions = [(m.start(), m.group("joined") is not None) for m in MSG_SPLIT.finditer(content)]
    positions.append((len(content), False))

    group_html = []
    for i, (pos, is_joined) in enumerate(positions[:-1]):
        next_pos = positions[i + 1][0]
        block = content[pos:next_pos]
        if not is_joined:
            if group_html:
                process_group("".join(group_html))
            group_html = [block]
        else:
            group_html.append(block)
    if group_html:
        process_group("".join(group_html))

print(f"Matched {len(results)}/{len(catalog_ids)} catalog games")

# ── compress and save ─────────────────────────────────────────────────────────
COVERS_DIR.mkdir(exist_ok=True)
from PIL import Image

ok = skip = fail = 0
for bgg_id, src in sorted(results.items()):
    dest = COVERS_DIR / f"{bgg_id}.webp"
    if dest.exists() and dest.stat().st_size > 500:
        skip += 1
        continue
    if not src.exists():
        print(f" MISS  {bgg_id}: {src.name}")
        fail += 1
        continue
    try:
        img = Image.open(src).convert("RGB")
        img.thumbnail(THUMB_SIZE, Image.LANCZOS)
        img.save(dest, "WEBP", quality=82)
        kb = dest.stat().st_size // 1024
        game = id_to_name.get(bgg_id, bgg_id)
        print(f"  OK   {bgg_id}.webp  {kb}KB  [{game}]  <- {src.name}")
        ok += 1
    except Exception as e:
        print(f" FAIL  {bgg_id}: {e}")
        fail += 1

print(f"\nDone: {ok} saved, {skip} skipped, {fail} failed")
unmatched = catalog_ids - set(results.keys())
if unmatched:
    print(f"\nNo TG photo for {len(unmatched)} games:")
    for n in sorted(id_to_name.get(bid, bid) for bid in unmatched):
        print(f"  - {n}")
