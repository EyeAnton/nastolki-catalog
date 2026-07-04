#!/usr/bin/env python3
"""
Auto-add or update a game listing from Telegram message.
Called by GitHub Actions with parsed data from Make.

Usage:
  python auto_add.py \
    --title "Spirit Island" \
    --price 25000 \
    --lang ENG \
    --msg_id 5123 \
    --seller "username" \
    --note "Complete, all promos"
"""
import argparse, json, re, io, time, sys, html as html_module
from pathlib import Path
from datetime import date

sys.stdout.reconfigure(encoding='utf-8')
ROOT   = Path(__file__).parent
HTML   = ROOT / "index.html"
COVERS = ROOT / "covers"
BLACKLIST_FILE = ROOT / "blacklist.json"

# ── Args ───────────────────────────────────────────────────────────────────────
p = argparse.ArgumentParser()
p.add_argument('--title',  required=True)
p.add_argument('--price',  type=int, default=None)
p.add_argument('--lang',   default='ENG')
p.add_argument('--msg_id', type=int, required=True)
p.add_argument('--seller', default='')
p.add_argument('--note',   default='')
p.add_argument('--exchange', action='store_true')
args = p.parse_args()

# ── Blacklist ─────────────────────────────────────────────────────────────────
blacklist = json.loads(BLACKLIST_FILE.read_text(encoding='utf-8'))
seller_lower = args.seller.lower().lstrip('@')
for blocked in blacklist:
    if seller_lower == blocked.lower().lstrip('@'):
        print(f"BLOCKED: seller '{args.seller}' is in blacklist")
        sys.exit(0)

# ── Load HTML ─────────────────────────────────────────────────────────────────
src = HTML.read_text(encoding='utf-8')
bgg_m = re.search(r'const BGG=(\{.*?\});', src, re.DOTALL)
d_m   = re.search(r'const D=(\[.*?\]);',   src, re.DOTALL)
BGG = json.loads(bgg_m.group(1))
D   = json.loads(d_m.group(1))

today = date.today().strftime('%d.%m.%Y')

# ── Deduplication: update existing listing if same title + seller ──────────────
for item in D:
    same_title  = item['t'].lower() == args.title.lower()
    same_seller = item.get('s','').lower().lstrip('@') == seller_lower
    if same_title and (same_seller or not args.seller):
        # Update price, date, msg_id, note if changed
        changed = []
        if args.price and item.get('p') != args.price:
            item['p'] = args.price; changed.append('price')
        if item.get('m') != args.msg_id:
            item['m'] = args.msg_id; changed.append('msg_id')
        if args.note and item.get('n') != args.note:
            item['n'] = args.note; changed.append('note')
        item['d'] = today
        if args.exchange:
            item['x'] = True
        print(f"UPDATED '{args.title}': {', '.join(changed) or 'date only'}")
        _updated = True
        break
else:
    _updated = False

if _updated:
    pass  # skip BGG lookup, just save
else:
    # ── New listing: look up BGG + download cover ──────────────────────────────
    print(f"NEW listing: '{args.title}'")

    try:
        from curl_cffi import requests as cffi_requests
        from PIL import Image
        session = cffi_requests.Session(impersonate="chrome131")
    except ImportError:
        session = None

    bgg_id   = None
    bgg_data = {}

    # BGG search
    if session:
        try:
            r = session.get(
                'https://boardgamegeek.com/xmlapi2/search',
                params={'query': args.title, 'type': 'boardgame', 'exact': 1},
                timeout=10)
            m = re.search(r'<item.*?id="(\d+)"', r.text)
            if not m:  # try non-exact
                r = session.get(
                    'https://boardgamegeek.com/xmlapi2/search',
                    params={'query': args.title, 'type': 'boardgame'},
                    timeout=10)
                m = re.search(r'<item.*?id="(\d+)"', r.text)
            if m:
                bgg_id = int(m.group(1))
                # Fetch details
                r2 = session.get(
                    f'https://boardgamegeek.com/xmlapi2/thing',
                    params={'id': bgg_id, 'stats': 1},
                    timeout=10)
                t2 = r2.text
                rating_m  = re.search(r'<average value="([\d.]+)"', t2)
                minp_m    = re.search(r'minplayers value="(\d+)"', t2)
                maxp_m    = re.search(r'maxplayers value="(\d+)"', t2)
                mint_m    = re.search(r'minplaytime value="(\d+)"', t2)
                maxt_m    = re.search(r'maxplaytime value="(\d+)"', t2)
                img_m     = re.search(r'<image>(.*?)</image>', t2)
                cats      = re.findall(r'boardgamecategory[^>]+value="([^"]+)"', t2)
                bgg_data = {
                    'bgg_id':      bgg_id,
                    'bgg_name':    args.title,
                    'rating':      round(float(rating_m.group(1)), 1) if rating_m else None,
                    'min_players': int(minp_m.group(1)) if minp_m else None,
                    'max_players': int(maxp_m.group(1)) if maxp_m else None,
                    'min_playtime':int(mint_m.group(1)) if mint_m else None,
                    'max_playtime':int(maxt_m.group(1)) if maxt_m else None,
                    'categories':  cats[:3],
                    'image':       img_m.group(1).strip() if img_m else '',
                    'bgg_url':     f'https://boardgamegeek.com/boardgame/{bgg_id}',
                }
                print(f"BGG found: {bgg_id}, rating={bgg_data.get('rating')}")
        except Exception as e:
            print(f"BGG lookup failed: {e}")

    # Add to BGG if not present
    if args.title not in BGG and bgg_data:
        BGG[args.title] = bgg_data
        print(f"BGG entry added: {args.title}")
    elif args.title not in BGG:
        BGG[args.title] = {
            'bgg_id': bgg_id or 0, 'bgg_name': args.title,
            'rating': None, 'min_players': None, 'max_players': None,
            'min_playtime': None, 'max_playtime': None,
            'categories': [], 'image': '', 'bgg_url': ''
        }

    # Download cover
    if session and bgg_id:
        bgg_slug = args.title.lower().replace(' ','-').replace(':','').replace("'",'')
        cover_saved = False

        # Try Tesera first
        try:
            r = session.get(f'https://tesera.ru/game/{bgg_slug}/',
                            headers={'Accept-Language':'ru,en'}, timeout=10)
            og = re.search(r'og:image["\s]+content="([^"]+)"', r.text)
            if og and 'p404' not in r.url:
                url = og.group(1).replace('200x200xpa','600x600xpa').replace('200x200','600x600')
                r2 = session.get(url, timeout=10)
                if r2.status_code == 200 and len(r2.content) > 5000:
                    img = Image.open(io.BytesIO(r2.content)).convert('RGB')
                    img.thumbnail((300,300), Image.LANCZOS)
                    img.save(COVERS / f'{bgg_id}.webp', 'WEBP', quality=82)
                    cover_saved = True
                    print(f"Cover: Tesera OK")
        except Exception as e:
            print(f"Tesera failed: {e}")

        # Fallback: Yandex
        if not cover_saved:
            try:
                SKIP = ('instagram','facebook','twitter','vk.com','pinterest','tiktok','amazon','ebay')
                r = session.get('https://yandex.ru/images/search',
                    params={'text': f'{args.title} board game box'},
                    headers={'Accept-Language':'ru-RU,ru;q=0.9,en;q=0.8'}, timeout=15)
                matches = re.findall(r'&quot;origUrl&quot;:&quot;(https?://[^&]+)&quot;', r.text)
                for raw in matches[:10]:
                    url = html_module.unescape(raw)
                    if any(d in url for d in SKIP): continue
                    r2 = session.get(url, timeout=10)
                    if r2.status_code == 200 and len(r2.content) >= 10000:
                        img = Image.open(io.BytesIO(r2.content)).convert('RGB')
                        if max(img.size)/min(img.size) < 2.5:
                            img.thumbnail((300,300), Image.LANCZOS)
                            img.save(COVERS / f'{bgg_id}.webp', 'WEBP', quality=82)
                            cover_saved = True
                            print(f"Cover: Yandex OK")
                            break
            except Exception as e:
                print(f"Yandex failed: {e}")

    # Add D listing
    new_entry = {
        't': args.title,
        's': args.seller,
        'p': args.price,
        'l': args.lang,
        'n': args.note,
        'd': today,
        'm': args.msg_id,
    }
    if args.exchange:
        new_entry['x'] = True
    D.append(new_entry)
    print(f"D entry added: {args.title} — {args.price} ֏ ({args.lang})")

# ── Save HTML ─────────────────────────────────────────────────────────────────
new_bgg = json.dumps(BGG, ensure_ascii=False, separators=(',',':'))
new_d   = json.dumps(D,   ensure_ascii=False, separators=(',',':'))
out = src[:bgg_m.start(1)] + new_bgg + src[bgg_m.end(1):]
d2  = re.search(r'const D=(\[.*?\]);', out, re.DOTALL)
out = out[:d2.start(1)] + new_d + out[d2.end(1):]
HTML.write_text(out, encoding='utf-8')
print(f"Saved. BGG={len(BGG)}, D={len(D)}")
